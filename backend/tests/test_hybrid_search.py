"""HybridSearchService テスト（TASK-B06）"""

from unittest.mock import AsyncMock

import pytest

from app.services.knowledge.search import HybridSearchService, SearchResult


# ─── Fixtures ───


@pytest.fixture
def mock_neo4j():
    client = AsyncMock()
    return client


@pytest.fixture
def mock_embedding():
    service = AsyncMock()
    service.embed_single = AsyncMock(return_value=[0.1] * 3072)
    return service


def _make_search_records() -> list[dict]:
    """Neo4jが返すレコードのモック。"""
    return [
        {
            "node_id": "SAP-BD9",
            "fn": "在庫からの販売",
            "desc": "在庫品の販売プロセス",
            "module": "SD",
            "domain": "販売",
            "kw": ["在庫", "販売"],
            "vector_score": 0.95,
            "keyword_score": 0.65,
            "final_score": 0.86,
        },
        {
            "node_id": "SAP-1B4",
            "fn": "受注から入金",
            "desc": "受注から入金までのE2E",
            "module": "SD",
            "domain": "販売",
            "kw": ["受注", "入金"],
            "vector_score": 0.80,
            "keyword_score": 0.45,
            "final_score": 0.695,
        },
    ]


# ─── SearchResult Tests ───


class TestSearchResult:
    def test_defaults(self):
        r = SearchResult(
            node_id="SAP-1B4",
            function_name="テスト",
            description="テスト説明",
            module="SD",
            business_domain="販売",
        )
        assert r.score == 0.0
        assert r.vector_score == 0.0
        assert r.keyword_score == 0.0
        assert r.keywords == []

    def test_full(self):
        r = SearchResult(
            node_id="SAP-BD9",
            function_name="在庫販売",
            description="在庫品販売",
            module="SD",
            business_domain="販売",
            keywords=["在庫", "販売"],
            score=0.86,
            vector_score=0.95,
            keyword_score=0.65,
        )
        assert r.node_id == "SAP-BD9"
        assert r.score == 0.86


# ─── HybridSearchService Tests ───


class TestHybridSearchService:

    @pytest.mark.asyncio
    async def test_search_returns_results(self, mock_neo4j, mock_embedding):
        """正常系: 検索結果が返される。"""
        mock_neo4j.execute_query = AsyncMock(return_value=_make_search_records())

        service = HybridSearchService(mock_neo4j, mock_embedding)
        results = await service.search("受注 販売")

        assert len(results) == 2
        assert results[0].node_id == "SAP-BD9"
        assert results[0].score == 0.86
        assert results[1].node_id == "SAP-1B4"

    @pytest.mark.asyncio
    async def test_search_generates_embedding(self, mock_neo4j, mock_embedding):
        """query_embedding未指定時にEmbeddingが自動生成される。"""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        service = HybridSearchService(mock_neo4j, mock_embedding)
        await service.search("テスト")

        mock_embedding.embed_single.assert_called_once_with("テスト")

    @pytest.mark.asyncio
    async def test_search_uses_provided_embedding(self, mock_neo4j, mock_embedding):
        """query_embedding指定時は自動生成しない。"""
        mock_neo4j.execute_query = AsyncMock(return_value=[])
        custom_emb = [0.5] * 3072

        service = HybridSearchService(mock_neo4j, mock_embedding)
        await service.search("テスト", query_embedding=custom_emb)

        mock_embedding.embed_single.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_passes_correct_params(self, mock_neo4j, mock_embedding):
        """Cypherパラメータが正しく構築される。"""
        mock_neo4j.execute_query = AsyncMock(return_value=_make_search_records())

        service = HybridSearchService(mock_neo4j, mock_embedding)
        await service.search(
            "受注",
            product_namespace="SAP",
            top_k=5,
            keyword_weight=0.4,
            vector_weight=0.6,
        )

        # Hybrid検索（1回目の呼び出し）のパラメータを検証
        call_args = mock_neo4j.execute_query.call_args_list[0]
        params = call_args[0][1]
        assert params["query_text"] == "受注"
        assert params["ns"] == "SAP"
        assert params["top_k"] == 5
        assert params["vec_top_k"] == 10  # top_k * 2
        assert params["vec_weight"] == 0.6
        assert params["kw_weight"] == 0.4
        assert len(params["query_embedding"]) == 3072

    @pytest.mark.asyncio
    async def test_search_empty_hybrid_falls_back_to_vector(self, mock_neo4j, mock_embedding):
        """Hybrid検索が空の場合、ベクトルのみフォールバックが実行される。"""
        fallback_result = [{
            "node_id": "SAP-FB1",
            "fn": "フォールバック機能",
            "desc": "ベクトル検索で発見",
            "module": "FI",
            "domain": "財務",
            "kw": ["フォールバック"],
            "vector_score": 0.75,
            "keyword_score": 0.0,
            "final_score": 0.75,
        }]
        # 1回目（Hybrid）は空、2回目（Vector-only）は結果あり
        mock_neo4j.execute_query = AsyncMock(side_effect=[[], fallback_result])

        service = HybridSearchService(mock_neo4j, mock_embedding)
        results = await service.search("存在しないクエリ")

        assert len(results) == 1
        assert results[0].node_id == "SAP-FB1"
        assert mock_neo4j.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_search_empty_both_hybrid_and_vector(self, mock_neo4j, mock_embedding):
        """Hybrid・ベクトル両方とも空の場合。"""
        mock_neo4j.execute_query = AsyncMock(return_value=[])

        service = HybridSearchService(mock_neo4j, mock_embedding)
        results = await service.search("全くマッチしない")

        assert results == []
        assert mock_neo4j.execute_query.call_count == 2  # Hybrid + Vector fallback

    @pytest.mark.asyncio
    async def test_search_result_fields_mapping(self, mock_neo4j, mock_embedding):
        """レコードからSearchResultへのフィールドマッピング。"""
        mock_neo4j.execute_query = AsyncMock(return_value=[{
            "node_id": "SAP-TEST",
            "fn": "テスト機能",
            "desc": "テスト説明",
            "module": "FI",
            "domain": "財務",
            "kw": ["テスト", "財務"],
            "vector_score": 0.90,
            "keyword_score": 0.70,
            "final_score": 0.84,
        }])

        service = HybridSearchService(mock_neo4j, mock_embedding)
        results = await service.search("テスト")

        r = results[0]
        assert r.node_id == "SAP-TEST"
        assert r.function_name == "テスト機能"
        assert r.description == "テスト説明"
        assert r.module == "FI"
        assert r.business_domain == "財務"
        assert r.keywords == ["テスト", "財務"]
        assert r.score == 0.84
        assert r.vector_score == 0.90
        assert r.keyword_score == 0.70

    @pytest.mark.asyncio
    async def test_search_handles_none_keywords(self, mock_neo4j, mock_embedding):
        """keywords が None の場合も空リストになる。"""
        mock_neo4j.execute_query = AsyncMock(return_value=[{
            "node_id": "SAP-TEST",
            "fn": "テスト",
            "desc": "テスト",
            "module": "SD",
            "domain": "販売",
            "kw": None,
            "vector_score": 0.5,
            "keyword_score": 0.3,
            "final_score": 0.44,
        }])

        service = HybridSearchService(mock_neo4j, mock_embedding)
        results = await service.search("テスト")

        assert results[0].keywords == []
