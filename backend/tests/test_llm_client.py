"""LLMクライアントのテスト（TASK-A05）

実際のLLM APIは呼ばず、リトライロジックと並行制御をテストする。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.llm_client import LLMClient, is_retryable_llm_error


class TestIsRetryableLlmError:
    def test_429_is_retryable(self):
        assert is_retryable_llm_error(Exception("Error 429: Rate limit exceeded"))

    def test_500_is_retryable(self):
        assert is_retryable_llm_error(Exception("500 Internal Server Error"))

    def test_502_is_retryable(self):
        assert is_retryable_llm_error(Exception("502 Bad Gateway"))

    def test_503_is_retryable(self):
        assert is_retryable_llm_error(Exception("503 Service Unavailable"))

    def test_529_is_retryable(self):
        assert is_retryable_llm_error(Exception("Error 529: Overloaded"))

    def test_timeout_is_retryable(self):
        assert is_retryable_llm_error(Exception("Connection timeout"))

    def test_rate_limit_is_retryable(self):
        assert is_retryable_llm_error(Exception("Rate limit reached"))

    def test_400_not_retryable(self):
        assert not is_retryable_llm_error(Exception("400 Bad Request"))

    def test_auth_error_not_retryable(self):
        assert not is_retryable_llm_error(Exception("401 Unauthorized"))

    def test_generic_error_not_retryable(self):
        assert not is_retryable_llm_error(ValueError("Invalid input"))


class TestLLMClientConcurrency:
    @patch("app.core.llm_client.init_chat_model")
    def test_initial_concurrency(self, mock_init):
        mock_init.return_value = MagicMock()
        settings = Settings(MAPPING_MAX_CONCURRENCY=5)
        client = LLMClient(settings)
        assert client.max_concurrency == 5

    @patch("app.core.llm_client.init_chat_model")
    def test_rate_limit_reduces_concurrency(self, mock_init):
        mock_init.return_value = MagicMock()
        settings = Settings(MAPPING_MAX_CONCURRENCY=5)
        client = LLMClient(settings)

        client._on_rate_limit()
        assert client.max_concurrency == 4

        client._on_rate_limit()
        assert client.max_concurrency == 3

    @patch("app.core.llm_client.init_chat_model")
    def test_rate_limit_floor_at_one(self, mock_init):
        mock_init.return_value = MagicMock()
        settings = Settings(MAPPING_MAX_CONCURRENCY=1)
        client = LLMClient(settings)

        client._on_rate_limit()
        assert client.max_concurrency == 1

    @patch("app.core.llm_client.init_chat_model")
    def test_success_recovery(self, mock_init):
        mock_init.return_value = MagicMock()
        settings = Settings(MAPPING_MAX_CONCURRENCY=5)
        client = LLMClient(settings)

        # 並行数を下げる
        client._on_rate_limit()
        client._on_rate_limit()
        assert client.max_concurrency == 3

        # 10回連続成功で1回復
        for _ in range(10):
            client._on_success()
        assert client.max_concurrency == 4

        # さらに10回成功で元に戻る
        for _ in range(10):
            client._on_success()
        assert client.max_concurrency == 5

    @patch("app.core.llm_client.init_chat_model")
    def test_no_recovery_beyond_initial(self, mock_init):
        mock_init.return_value = MagicMock()
        settings = Settings(MAPPING_MAX_CONCURRENCY=3)
        client = LLMClient(settings)

        # 初期値で10回成功しても増えない
        for _ in range(20):
            client._on_success()
        assert client.max_concurrency == 3


class TestLLMClientCallWithRetry:
    @pytest.mark.asyncio
    @patch("app.core.llm_client.init_chat_model")
    async def test_successful_call(self, mock_init):
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(return_value="response")
        mock_init.return_value = mock_model

        settings = Settings(MAPPING_MAX_CONCURRENCY=2)
        client = LLMClient(settings)

        result = await client.call_with_retry(mock_model, [{"role": "user", "content": "test"}])
        assert result == "response"
        mock_model.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.core.llm_client.init_chat_model")
    async def test_non_retryable_error_raises_immediately(self, mock_init):
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(side_effect=ValueError("400 Bad Request"))
        mock_init.return_value = mock_model

        settings = Settings(MAPPING_MAX_CONCURRENCY=2)
        client = LLMClient(settings)

        with pytest.raises(ValueError, match="400"):
            await client.call_with_retry(mock_model, [])
        assert mock_model.ainvoke.call_count == 1
