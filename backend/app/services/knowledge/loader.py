"""Neo4j ナレッジローダー（TASK-B04）

パーサーが生成した構造化データをNeo4jに投入する。
4フェーズ順序制約付きバルクロード + OpenAI Embedding生成。
"""

import logging
import time
from dataclasses import dataclass, field

from app.core.embedding import EmbeddingService
from app.core.neo4j_client import Neo4jClient
from app.services.knowledge.parser import ModuleOverviewData, ScopeItemData

logger = logging.getLogger(__name__)


@dataclass
class LoadResult:
    """バルクロード結果。"""

    scope_items_loaded: int = 0
    scope_item_relations_created: int = 0
    module_overviews_loaded: int = 0
    covers_relations_created: int = 0
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class KnowledgeLoader:
    """Neo4jへのナレッジデータ投入。"""

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self._neo4j = neo4j_client
        self._embedding = embedding_service

    async def load_scope_item(
        self, data: ScopeItemData, embedding: list[float] | None = None
    ) -> None:
        """ScopeItemノードをNeo4jに投入（MERGE on id）。"""
        params: dict = {
            "id": data.id,
            "product": data.product,
            "product_namespace": data.product_namespace,
            "module": data.module,
            "scope_item_id": data.scope_item_id,
            "function_name": data.function_name,
            "description": data.description,
            "description_en": data.description_en,
            "business_domain": data.business_domain,
            "capability_level": data.capability_level,
            "keywords": data.keywords,
            "source_doc": data.source_doc,
            "product_version": data.product_version,
        }

        if embedding:
            params["embedding"] = embedding
            cypher = """
            MERGE (s:ScopeItem {id: $id})
            SET s.product = $product,
                s.product_namespace = $product_namespace,
                s.module = $module,
                s.scope_item_id = $scope_item_id,
                s.function_name = $function_name,
                s.description = $description,
                s.description_en = $description_en,
                s.business_domain = $business_domain,
                s.capability_level = $capability_level,
                s.keywords = $keywords,
                s.source_doc = $source_doc,
                s.product_version = $product_version,
                s.embedding = $embedding
            """
        else:
            cypher = """
            MERGE (s:ScopeItem {id: $id})
            SET s.product = $product,
                s.product_namespace = $product_namespace,
                s.module = $module,
                s.scope_item_id = $scope_item_id,
                s.function_name = $function_name,
                s.description = $description,
                s.description_en = $description_en,
                s.business_domain = $business_domain,
                s.capability_level = $capability_level,
                s.keywords = $keywords,
                s.source_doc = $source_doc,
                s.product_version = $product_version
            """

        await self._neo4j.execute_write(cypher, params)

    async def load_module_overview(
        self, data: ModuleOverviewData, embedding: list[float] | None = None
    ) -> None:
        """ModuleOverviewノードをNeo4jに投入。"""
        params: dict = {
            "id": data.id,
            "product": data.product,
            "product_namespace": data.product_namespace,
            "module": data.module,
            "module_name": data.module_name,
            "summary": data.summary,
            "source_doc": data.source_doc,
            "page_count": data.page_count,
        }

        if embedding:
            params["embedding"] = embedding
            cypher = """
            MERGE (m:ModuleOverview {id: $id})
            SET m.product = $product,
                m.product_namespace = $product_namespace,
                m.module = $module,
                m.module_name = $module_name,
                m.summary = $summary,
                m.source_doc = $source_doc,
                m.page_count = $page_count,
                m.embedding = $embedding
            """
        else:
            cypher = """
            MERGE (m:ModuleOverview {id: $id})
            SET m.product = $product,
                m.product_namespace = $product_namespace,
                m.module = $module,
                m.module_name = $module_name,
                m.summary = $summary,
                m.source_doc = $source_doc,
                m.page_count = $page_count
            """

        await self._neo4j.execute_write(cypher, params)

    async def _create_si_relation(
        self, source_id: str, target_id: str, rel_type: str
    ) -> None:
        """ScopeItem間リレーションを作成。"""
        cypher = f"""
        MATCH (a:ScopeItem {{id: $source_id}})
        MATCH (b:ScopeItem {{id: $target_id}})
        MERGE (a)-[:{rel_type}]->(b)
        """
        await self._neo4j.execute_write(
            cypher, {"source_id": source_id, "target_id": target_id}
        )

    async def _create_covers_relation(
        self, mo_id: str, si_id: str
    ) -> None:
        """ModuleOverview→ScopeItem COVERS リレーションを作成。"""
        cypher = """
        MATCH (m:ModuleOverview {id: $mo_id})
        MATCH (s:ScopeItem {id: $si_id})
        MERGE (m)-[:COVERS]->(s)
        """
        await self._neo4j.execute_write(
            cypher, {"mo_id": mo_id, "si_id": si_id}
        )

    def _build_embed_text_si(self, si: ScopeItemData) -> str:
        """ScopeItem用Embeddingテキストを構築。"""
        parts = [si.function_name, si.description]
        if si.module:
            parts.append(si.module)
        if si.business_domain:
            parts.append(si.business_domain)
        if si.keywords:
            parts.append(" ".join(si.keywords))
        return " ".join(parts)

    def _build_embed_text_mo(self, mo: ModuleOverviewData) -> str:
        """ModuleOverview用Embeddingテキストを構築。"""
        return f"{mo.module_name} {mo.summary}"

    async def bulk_load(
        self,
        scope_items: list[ScopeItemData],
        module_overviews: list[ModuleOverviewData],
        batch_size: int = 50,
    ) -> LoadResult:
        """4フェーズ順序制約付きバルクロード。

        Phase 1: ScopeItemノード作成（プロパティ + Embedding）
        Phase 2: ScopeItem間リレーション（PREREQUISITE / RELATED / FOLLOW_ON）
        Phase 3: ModuleOverviewノード作成
        Phase 4: COVERSリレーション
        """
        result = LoadResult()
        start = time.time()

        all_si_ids = {si.id for si in scope_items}

        # ============ Phase 1: ScopeItem ノード ============
        logger.info("Phase 1: Loading %d ScopeItem nodes...", len(scope_items))
        si_embeddings: list[list[float]] | None = None
        if self._embedding and scope_items:
            si_texts = [self._build_embed_text_si(si) for si in scope_items]
            si_embeddings = await self._embedding.embed_batch(si_texts, batch_size)

        for i, si in enumerate(scope_items):
            emb = si_embeddings[i] if si_embeddings else None
            await self.load_scope_item(si, emb)
            result.scope_items_loaded += 1

        logger.info("Phase 1 complete: %d nodes", result.scope_items_loaded)

        # ============ Phase 2: ScopeItem リレーション ============
        logger.info("Phase 2: Creating ScopeItem relations...")
        rel_type_map = {
            "prerequisite": "PREREQUISITE",
            "related": "RELATED",
            "follow_on": "FOLLOW_ON",
        }

        for si in scope_items:
            for rel_key, target_ids in si.relations.items():
                neo4j_rel = rel_type_map.get(rel_key, rel_key.upper())
                for target_prefix in target_ids:
                    full_target = f"SAP-{target_prefix}" if not target_prefix.startswith("SAP-") else target_prefix
                    if full_target not in all_si_ids:
                        result.warnings.append(
                            f"{si.id} -> {full_target} ({neo4j_rel}): target not found, skipped"
                        )
                        continue
                    await self._create_si_relation(si.id, full_target, neo4j_rel)
                    result.scope_item_relations_created += 1

        logger.info("Phase 2 complete: %d relations", result.scope_item_relations_created)

        # ============ Phase 3: ModuleOverview ノード ============
        logger.info("Phase 3: Loading %d ModuleOverview nodes...", len(module_overviews))
        mo_embeddings: list[list[float]] | None = None
        if self._embedding and module_overviews:
            mo_texts = [self._build_embed_text_mo(mo) for mo in module_overviews]
            mo_embeddings = await self._embedding.embed_batch(mo_texts, batch_size)

        for i, mo in enumerate(module_overviews):
            emb = mo_embeddings[i] if mo_embeddings else None
            await self.load_module_overview(mo, emb)
            result.module_overviews_loaded += 1

        logger.info("Phase 3 complete: %d nodes", result.module_overviews_loaded)

        # ============ Phase 4: COVERS リレーション ============
        logger.info("Phase 4: Creating COVERS relations...")
        for mo in module_overviews:
            for si_id in mo.covers_scope_items:
                if si_id not in all_si_ids:
                    result.warnings.append(
                        f"{mo.id} -> {si_id} (COVERS): target not found, skipped"
                    )
                    continue
                await self._create_covers_relation(mo.id, si_id)
                result.covers_relations_created += 1

        logger.info("Phase 4 complete: %d relations", result.covers_relations_created)

        result.duration_seconds = time.time() - start
        return result
