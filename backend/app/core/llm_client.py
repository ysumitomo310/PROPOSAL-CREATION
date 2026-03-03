"""LLMクライアント抽象化 + リトライラッパー

design.md 仕様:
- init_chat_model() でプロバイダ自動判定
- 軽量(light) / 高性能(heavy) の2インスタンス
- tenacity による指数バックオフリトライ
- 429 Rate Limit 時の Semaphore 動的縮小
"""

import asyncio
import logging

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings

logger = logging.getLogger(__name__)

# リトライ対象の HTTP ステータスコード
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


def is_retryable_llm_error(exc: BaseException) -> bool:
    """リトライすべきLLMエラーかどうかを判定する。"""
    exc_str = str(exc).lower()
    # ステータスコードベースの判定
    for code in _RETRYABLE_STATUS_CODES:
        if str(code) in exc_str:
            return True
    # 一般的なネットワーク/タイムアウトエラー
    if any(keyword in exc_str for keyword in ("timeout", "connection", "rate limit")):
        return True
    return False


class LLMClient:
    """LLM呼び出しの抽象レイヤー。

    - light: 高速・低コスト（分類・評価用）
    - heavy: 高精度（最終判定用）
    - Semaphore による並行制御 + 429 時の動的縮小
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._initial_concurrency = settings.MAPPING_MAX_CONCURRENCY
        self._max_concurrency = settings.MAPPING_MAX_CONCURRENCY
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._consecutive_successes = 0

        # API キーを明示的に渡す（pydantic_settings は os.environ にセットしないため）
        light_kwargs: dict = {}
        heavy_kwargs: dict = {}
        if "gpt" in settings.LLM_LIGHT_MODEL or "o1" in settings.LLM_LIGHT_MODEL:
            light_kwargs["api_key"] = settings.OPENAI_API_KEY
        elif "claude" in settings.LLM_LIGHT_MODEL:
            light_kwargs["api_key"] = settings.ANTHROPIC_API_KEY
        if "gpt" in settings.LLM_HEAVY_MODEL or "o1" in settings.LLM_HEAVY_MODEL:
            heavy_kwargs["api_key"] = settings.OPENAI_API_KEY
        elif "claude" in settings.LLM_HEAVY_MODEL:
            heavy_kwargs["api_key"] = settings.ANTHROPIC_API_KEY

        self.light: BaseChatModel = init_chat_model(
            settings.LLM_LIGHT_MODEL, **light_kwargs
        )
        self.heavy: BaseChatModel = init_chat_model(
            settings.LLM_HEAVY_MODEL, **heavy_kwargs
        )

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    def _on_rate_limit(self) -> None:
        """429 検知時: 並行数を1減らす。"""
        old = self._max_concurrency
        self._max_concurrency = max(1, self._max_concurrency - 1)
        self._consecutive_successes = 0
        if old != self._max_concurrency:
            logger.warning(
                "Rate limit detected. Reducing concurrency: %d -> %d",
                old,
                self._max_concurrency,
            )

    def _on_success(self) -> None:
        """成功時: 連続10回で並行数を1回復。"""
        self._consecutive_successes += 1
        if (
            self._consecutive_successes >= 10
            and self._max_concurrency < self._initial_concurrency
        ):
            self._max_concurrency = min(
                self._initial_concurrency, self._max_concurrency + 1
            )
            self._consecutive_successes = 0
            logger.info(
                "Concurrency recovered to %d", self._max_concurrency
            )

    async def call_with_retry(
        self,
        model: BaseChatModel,
        messages: list,
        **kwargs,
    ):
        """リトライ付きLLM呼び出し。

        Semaphore でレート制御しつつ、429 時に動的に並行数を縮小する。
        """

        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=2, min=5, max=90),
            retry=retry_if_exception(is_retryable_llm_error),
            reraise=True,
        )
        async def _invoke():
            try:
                result = await model.ainvoke(messages, **kwargs)
                self._on_success()
                return result
            except Exception as e:
                if "429" in str(e) or "rate limit" in str(e).lower():
                    self._on_rate_limit()
                raise

        async with self._semaphore:
            return await _invoke()

    async def call_light(self, messages: list, **kwargs):
        """軽量モデルでの呼び出し。"""
        return await self.call_with_retry(self.light, messages, **kwargs)

    async def call_heavy(self, messages: list, **kwargs):
        """高性能モデルでの呼び出し。"""
        return await self.call_with_retry(self.heavy, messages, **kwargs)

    async def call_light_structured(self, messages: list, schema, **kwargs):
        """軽量モデル + structured output。"""
        structured = self.light.with_structured_output(schema)
        return await self.call_with_retry(structured, messages, **kwargs)

    async def call_heavy_structured(self, messages: list, schema, **kwargs):
        """高性能モデル + structured output。"""
        structured = self.heavy.with_structured_output(schema)
        return await self.call_with_retry(structured, messages, **kwargs)
