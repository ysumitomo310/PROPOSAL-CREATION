"""KnowledgeLoader + EmbeddingService テスト（TASK-B04）"""

from dataclasses import field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.embedding import EmbeddingService
from app.services.knowledge.loader import KnowledgeLoader, LoadResult
from app.services.knowledge.parser import ModuleOverviewData, ScopeItemData


# ─── Fixtures ───


def _make_scope_item(
    prefix: str = "1B4",
    module: str = "SD",
    relations: dict | None = None,
) -> ScopeItemData:
    return ScopeItemData(
        id=f"SAP-{prefix}",
        product="SAP S/4HANA Cloud",
        product_namespace="SAP",
        module=module,
        scope_item_id=prefix,
        function_name=f"テスト機能 {prefix}",
        description=f"テスト説明 {prefix}",
        description_en=f"Test description {prefix}",
        business_domain="販売",
        capability_level="standard",
        keywords=["テスト", "販売"],
        source_doc=f"{prefix}_S4CLD2602_BPD_JA_JP.docx",
        product_version="S4CLD2602",
        relations=relations or {},
    )


def _make_module_overview(
    module: str = "SD",
    covers: list[str] | None = None,
) -> ModuleOverviewData:
    return ModuleOverviewData(
        id=f"MO-{module}-test",
        product="SAP S/4HANA Cloud",
        product_namespace="SAP",
        module=module,
        module_name=f"{module}テストモジュール",
        summary="テスト概要サマリー",
        source_doc="test.pdf",
        page_count=10,
        covers_scope_items=covers or [],
    )


@pytest.fixture
def mock_neo4j():
    client = AsyncMock()
    client.execute_write = AsyncMock(return_value=None)
    return client


@pytest.fixture
def mock_embedding():
    service = AsyncMock(spec=EmbeddingService)
    service.embed_batch = AsyncMock(
        return_value=[[0.1] * 3072, [0.2] * 3072]
    )
    return service


# ─── LoadResult Tests ───


class TestLoadResult:
    def test_defaults(self):
        r = LoadResult()
        assert r.scope_items_loaded == 0
        assert r.scope_item_relations_created == 0
        assert r.module_overviews_loaded == 0
        assert r.covers_relations_created == 0
        assert r.warnings == []
        assert r.duration_seconds == 0.0


# ─── KnowledgeLoader Unit Tests ───


class TestKnowledgeLoader:

    @pytest.mark.asyncio
    async def test_load_scope_item_without_embedding(self, mock_neo4j):
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)
        si = _make_scope_item("1B4")
        await loader.load_scope_item(si)

        mock_neo4j.execute_write.assert_called_once()
        call_args = mock_neo4j.execute_write.call_args
        cypher = call_args[0][0]
        params = call_args[0][1]

        assert "MERGE (s:ScopeItem {id: $id})" in cypher
        assert "embedding" not in cypher
        assert params["id"] == "SAP-1B4"
        assert params["function_name"] == "テスト機能 1B4"

    @pytest.mark.asyncio
    async def test_load_scope_item_with_embedding(self, mock_neo4j):
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)
        si = _make_scope_item("BD9")
        emb = [0.5] * 3072
        await loader.load_scope_item(si, embedding=emb)

        call_args = mock_neo4j.execute_write.call_args
        cypher = call_args[0][0]
        params = call_args[0][1]

        assert "s.embedding = $embedding" in cypher
        assert params["embedding"] == emb

    @pytest.mark.asyncio
    async def test_load_module_overview_without_embedding(self, mock_neo4j):
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)
        mo = _make_module_overview("SD")
        await loader.load_module_overview(mo)

        call_args = mock_neo4j.execute_write.call_args
        cypher = call_args[0][0]
        params = call_args[0][1]

        assert "MERGE (m:ModuleOverview {id: $id})" in cypher
        assert "embedding" not in cypher
        assert params["id"] == "MO-SD-test"

    @pytest.mark.asyncio
    async def test_load_module_overview_with_embedding(self, mock_neo4j):
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)
        mo = _make_module_overview("MM")
        emb = [0.3] * 3072
        await loader.load_module_overview(mo, embedding=emb)

        call_args = mock_neo4j.execute_write.call_args
        cypher = call_args[0][0]
        assert "m.embedding = $embedding" in cypher

    @pytest.mark.asyncio
    async def test_build_embed_text_si(self, mock_neo4j):
        loader = KnowledgeLoader(mock_neo4j)
        si = _make_scope_item("1B4")
        text = loader._build_embed_text_si(si)
        assert "テスト機能 1B4" in text
        assert "テスト説明 1B4" in text
        assert "テスト" in text
        assert "販売" in text

    @pytest.mark.asyncio
    async def test_build_embed_text_si_includes_module_and_domain(self, mock_neo4j):
        """_build_embed_text_si が module と business_domain を含むこと。"""
        loader = KnowledgeLoader(mock_neo4j)
        si = _make_scope_item("1B4", module="SD")
        text = loader._build_embed_text_si(si)
        # module と business_domain が明示的にテキストに含まれる
        assert "SD" in text
        assert "販売" in text
        assert "テスト機能 1B4" in text
        assert "テスト" in text  # keywords

    @pytest.mark.asyncio
    async def test_build_embed_text_mo(self, mock_neo4j):
        loader = KnowledgeLoader(mock_neo4j)
        mo = _make_module_overview("SD")
        text = loader._build_embed_text_mo(mo)
        assert "SDテストモジュール" in text
        assert "テスト概要サマリー" in text


# ─── Bulk Load Tests ───


class TestBulkLoad:

    @pytest.mark.asyncio
    async def test_bulk_load_no_embedding(self, mock_neo4j):
        """Embedding無しでの4フェーズバルクロード。"""
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)

        si1 = _make_scope_item("1B4", relations={"prerequisite": ["BD9"]})
        si2 = _make_scope_item("BD9")
        mo = _make_module_overview("SD", covers=["SAP-1B4", "SAP-BD9"])

        result = await loader.bulk_load([si1, si2], [mo])

        assert result.scope_items_loaded == 2
        assert result.scope_item_relations_created == 1
        assert result.module_overviews_loaded == 1
        assert result.covers_relations_created == 2
        assert result.warnings == []
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_bulk_load_with_embedding(self, mock_neo4j, mock_embedding):
        """Embedding付きでの4フェーズバルクロード。"""
        mock_embedding.embed_batch = AsyncMock(
            side_effect=[
                [[0.1] * 3072, [0.2] * 3072],  # Phase 1: 2 ScopeItems
                [[0.3] * 3072],                  # Phase 3: 1 ModuleOverview
            ]
        )
        loader = KnowledgeLoader(mock_neo4j, embedding_service=mock_embedding)

        si1 = _make_scope_item("1B4")
        si2 = _make_scope_item("BD9")
        mo = _make_module_overview("SD", covers=["SAP-1B4"])

        result = await loader.bulk_load([si1, si2], [mo])

        assert result.scope_items_loaded == 2
        assert result.module_overviews_loaded == 1
        assert mock_embedding.embed_batch.call_count == 2

    @pytest.mark.asyncio
    async def test_bulk_load_missing_relation_target(self, mock_neo4j):
        """存在しないScopeItemへのリレーションはwarning。"""
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)

        si = _make_scope_item("1B4", relations={"prerequisite": ["NONEXISTENT"]})

        result = await loader.bulk_load([si], [])

        assert result.scope_items_loaded == 1
        assert result.scope_item_relations_created == 0
        assert len(result.warnings) == 1
        assert "NONEXISTENT" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_bulk_load_missing_covers_target(self, mock_neo4j):
        """COVERSリレーションの対象が存在しない場合のwarning。"""
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)

        mo = _make_module_overview("SD", covers=["SAP-MISSING"])

        result = await loader.bulk_load([], [mo])

        assert result.module_overviews_loaded == 1
        assert result.covers_relations_created == 0
        assert len(result.warnings) == 1
        assert "MISSING" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_bulk_load_relation_with_sap_prefix(self, mock_neo4j):
        """SAP-プレフィックス付きrelationターゲットの処理。"""
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)

        si1 = _make_scope_item("1B4", relations={"related": ["SAP-BD9"]})
        si2 = _make_scope_item("BD9")

        result = await loader.bulk_load([si1, si2], [])

        assert result.scope_item_relations_created == 1
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_bulk_load_empty_inputs(self, mock_neo4j):
        """空入力での実行。"""
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)

        result = await loader.bulk_load([], [])

        assert result.scope_items_loaded == 0
        assert result.module_overviews_loaded == 0
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_bulk_load_multiple_relation_types(self, mock_neo4j):
        """複数種類のリレーション。"""
        loader = KnowledgeLoader(mock_neo4j, embedding_service=None)

        si1 = _make_scope_item(
            "1B4",
            relations={
                "prerequisite": ["BD9"],
                "related": ["2EL"],
                "follow_on": ["BD9"],
            },
        )
        si2 = _make_scope_item("BD9")
        si3 = _make_scope_item("2EL")

        result = await loader.bulk_load([si1, si2, si3], [])

        assert result.scope_items_loaded == 3
        # prerequisite→BD9, related→2EL, follow_on→BD9 = 3
        assert result.scope_item_relations_created == 3


# ─── EmbeddingService Tests (mocked OpenAI) ───


class TestEmbeddingService:

    @pytest.mark.asyncio
    async def test_embed_single(self):
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 3072)]

        with patch("app.core.embedding.AsyncOpenAI") as MockOpenAI:
            mock_client = AsyncMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            MockOpenAI.return_value = mock_client

            service = EmbeddingService(api_key="test-key")
            result = await service.embed_single("テスト")

            assert len(result) == 3072
            mock_client.embeddings.create.assert_called_once_with(
                input="テスト", model="text-embedding-3-large"
            )

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1] * 3072),
            MagicMock(embedding=[0.2] * 3072),
        ]

        with patch("app.core.embedding.AsyncOpenAI") as MockOpenAI:
            mock_client = AsyncMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            MockOpenAI.return_value = mock_client

            service = EmbeddingService(api_key="test-key")
            result = await service.embed_batch(["テスト1", "テスト2"], batch_size=50)

            assert len(result) == 2
            assert len(result[0]) == 3072

    @pytest.mark.asyncio
    async def test_embed_batch_multiple_batches(self):
        mock_response_1 = MagicMock()
        mock_response_1.data = [MagicMock(embedding=[0.1] * 3072)] * 2
        mock_response_2 = MagicMock()
        mock_response_2.data = [MagicMock(embedding=[0.2] * 3072)]

        with patch("app.core.embedding.AsyncOpenAI") as MockOpenAI:
            mock_client = AsyncMock()
            mock_client.embeddings.create = AsyncMock(
                side_effect=[mock_response_1, mock_response_2]
            )
            MockOpenAI.return_value = mock_client

            service = EmbeddingService(api_key="test-key")
            result = await service.embed_batch(
                ["テスト1", "テスト2", "テスト3"], batch_size=2
            )

            assert len(result) == 3
            assert mock_client.embeddings.create.call_count == 2

    def test_dimensions_default(self):
        with patch("app.core.embedding.AsyncOpenAI"):
            service = EmbeddingService(api_key="test-key")
            assert service.dimensions == 3072
