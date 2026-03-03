"""Hybrid検索サービス（TASK-B06）

ベクトル類似度+CJKキーワード検索を2段階Cypherクエリで実行する。
design.md COMP-SEARCH 準拠。
"""

import logging
from dataclasses import dataclass, field

from app.core.embedding import EmbeddingService
from app.core.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

# Lucene 特殊文字のエスケープ
_LUCENE_SPECIAL_CHARS = r'+-&|!(){}[]^"~*?:\/'


def _escape_lucene_query(text: str) -> str:
    """Lucene fulltext クエリの特殊文字をエスケープする。"""
    result = []
    for ch in text:
        if ch in _LUCENE_SPECIAL_CHARS:
            result.append("\\")
        result.append(ch)
    return "".join(result)

# B06a Spike で検証済みの Hybrid Search Cypher
_HYBRID_CYPHER = """
// --- Vector Search ---
CALL db.index.vector.queryNodes('scope_item_vector_idx', $vec_top_k, $query_embedding)
YIELD node AS vNode, score AS vec_score
WHERE vNode.product_namespace = $ns
WITH collect({node_id: vNode.id, fn: vNode.function_name, desc: vNode.description,
              module: vNode.module, domain: vNode.business_domain, kw: vNode.keywords,
              vec_score: vec_score, kw_score: 0.0}) AS vec_results

// --- Keyword Search ---
CALL db.index.fulltext.queryNodes('scope_item_fulltext_idx', $query_text)
YIELD node AS kNode, score AS raw_kw_score
WHERE kNode.product_namespace = $ns
WITH vec_results,
     collect({node_id: kNode.id, fn: kNode.function_name, desc: kNode.description,
              module: kNode.module, domain: kNode.business_domain, kw: kNode.keywords,
              vec_score: 0.0, kw_score: raw_kw_score / (raw_kw_score + 1.0)}) AS kw_results

// --- Merge & Score ---
WITH vec_results + kw_results AS all_results
UNWIND all_results AS r
WITH r.node_id AS node_id, r.fn AS fn, r.desc AS desc,
     r.module AS module, r.domain AS domain, r.kw AS kw,
     max(r.vec_score) AS vector_score,
     max(r.kw_score) AS keyword_score
WITH node_id, fn, desc, module, domain, kw, vector_score, keyword_score,
     ($vec_weight * vector_score + $kw_weight * keyword_score) AS final_score
RETURN node_id, fn, desc, module, domain, kw, vector_score, keyword_score, final_score
ORDER BY final_score DESC
LIMIT $top_k
"""

# Vector-only フォールバッククエリ（Hybrid検索が0件の場合に使用）
_VECTOR_ONLY_CYPHER = """
CALL db.index.vector.queryNodes('scope_item_vector_idx', $top_k, $query_embedding)
YIELD node AS vNode, score AS vec_score
WHERE vNode.product_namespace = $ns
RETURN vNode.id AS node_id, vNode.function_name AS fn, vNode.description AS desc,
       vNode.module AS module, vNode.business_domain AS domain, vNode.keywords AS kw,
       vec_score AS vector_score, 0.0 AS keyword_score, vec_score AS final_score
ORDER BY vec_score DESC
LIMIT $top_k
"""


@dataclass
class SearchResult:
    """Hybrid検索結果。"""

    node_id: str  # "SAP-1B4"
    function_name: str
    description: str
    module: str
    business_domain: str
    keywords: list[str] = field(default_factory=list)
    score: float = 0.0  # combined final_score 0.0-1.0
    vector_score: float = 0.0  # cosine similarity 0.0-1.0
    keyword_score: float = 0.0  # sigmoid正規化済み 0.0-1.0


class HybridSearchService:
    """ベクトル+キーワードのHybrid検索。"""

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        embedding_service: EmbeddingService,
    ) -> None:
        self._neo4j = neo4j_client
        self._embedding = embedding_service

    async def search(
        self,
        query_text: str,
        query_embedding: list[float] | None = None,
        product_namespace: str = "SAP",
        top_k: int = 10,
        keyword_weight: float = 0.3,
        vector_weight: float = 0.7,
    ) -> list[SearchResult]:
        """Hybrid Searchを2段階Cypherクエリで実行。

        Args:
            query_text: 検索クエリテキスト（日本語可）
            query_embedding: クエリのEmbedding（省略時は自動生成）
            product_namespace: 製品フィルタ（default: "SAP"）
            top_k: 返却件数上限
            keyword_weight: キーワードスコアの重み
            vector_weight: ベクトルスコアの重み

        Returns:
            SearchResult のリスト（final_score降順）
        """
        # クエリEmbedding生成（未指定時）
        if query_embedding is None:
            query_embedding = await self._embedding.embed_single(query_text)

        # Lucene特殊文字をエスケープ
        escaped_query = _escape_lucene_query(query_text)

        params = {
            "query_embedding": query_embedding,
            "query_text": escaped_query,
            "ns": product_namespace,
            "top_k": top_k,
            "vec_top_k": top_k * 2,  # ベクトル検索は多めに取得してマージ
            "vec_weight": vector_weight,
            "kw_weight": keyword_weight,
        }

        logger.info(
            "Hybrid search: query='%s', ns=%s, top_k=%d, weights=(%.1f, %.1f)",
            query_text[:50],
            product_namespace,
            top_k,
            vector_weight,
            keyword_weight,
        )

        records = await self._neo4j.execute_query(_HYBRID_CYPHER, params)

        results = self._parse_results(records)

        # フォールバック: Hybrid検索が0件の場合、ベクトル検索のみで再試行
        if not results:
            logger.warning(
                "Hybrid search returned 0 results for query='%s', falling back to vector-only",
                query_text[:50],
            )
            fallback_params = {
                "query_embedding": query_embedding,
                "ns": product_namespace,
                "top_k": top_k,
            }
            fallback_records = await self._neo4j.execute_query(
                _VECTOR_ONLY_CYPHER, fallback_params
            )
            results = self._parse_results(fallback_records)
            logger.info("Vector-only fallback returned %d results", len(results))
        else:
            logger.info("Hybrid search returned %d results", len(results))

        return results

    @staticmethod
    def _parse_results(records: list[dict]) -> list["SearchResult"]:
        """Neo4jクエリ結果をSearchResultリストに変換。"""
        return [
            SearchResult(
                node_id=r["node_id"],
                function_name=r["fn"],
                description=r["desc"],
                module=r["module"],
                business_domain=r["domain"],
                keywords=r.get("kw") or [],
                score=r["final_score"],
                vector_score=r["vector_score"],
                keyword_score=r["keyword_score"],
            )
            for r in records
        ]
