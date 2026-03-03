"""TraverseGraph ノード（TASK-C06）

上位マッチノードに対し1-hop探索（RELATED/COVERS）。
ModuleOverviewコンテキスト取得。COVERS未接続時はモジュール名で補完。

改善点:
- PREREQUISITE/FOLLOW_ON は Neo4j に存在しないため削除（警告を排除）
- module_overview_context が空の場合、モジュール名で補完クエリを実行
"""

import logging

from app.core.neo4j_client import Neo4jClient
from app.services.mapping.state import MappingState

logger = logging.getLogger(__name__)

_TRAVERSE_CYPHER = """
MATCH (s:ScopeItem {id: $node_id})
OPTIONAL MATCH (s)-[:RELATED]->(rel:ScopeItem)
OPTIONAL MATCH (mo:ModuleOverview)-[:COVERS]->(s)
RETURN
    s.module AS source_module,
    collect(DISTINCT {id: rel.id, function_name: rel.function_name,
                      description: rel.description}) AS related,
    collect(DISTINCT {id: mo.id, module_name: mo.module_name,
                      summary: mo.summary}) AS module_overviews
"""

# ModuleOverview が COVERS で繋がっていない場合の補完クエリ
_MODULE_OVERVIEW_FALLBACK_CYPHER = """
MATCH (mo:ModuleOverview {module: $module_name})
RETURN mo.module_name AS module_name, mo.summary AS summary
LIMIT 1
"""


def build_traverse_graph_node(neo4j_client: Neo4jClient, top_n: int = 3):
    """TraverseGraph ノード関数を生成。"""

    async def traverse_graph_node(state: MappingState) -> dict:
        search_results = state.get("search_results", [])
        top_results = search_results[:top_n]

        traversed_nodes: list[dict] = []
        module_overviews_seen: set[str] = set()
        module_overview_texts: list[str] = []
        modules_seen: set[str] = set()

        for sr in top_results:
            node_id = sr.get("node_id", "")
            if not node_id:
                continue

            records = await neo4j_client.execute_query(
                _TRAVERSE_CYPHER, {"node_id": node_id}
            )

            if not records:
                continue

            record = records[0]
            source_module = record.get("source_module", "") or ""

            # Noneフィルタ
            related = [r for r in record.get("related", []) if r.get("id")]
            mo_list = [m for m in record.get("module_overviews", []) if m.get("id")]

            traversed_nodes.append({
                "source_id": node_id,
                "source_module": source_module,
                "related": related,
                "module_overviews": mo_list,
            })

            # ModuleOverview テキスト収集（重複排除）
            for mo in mo_list:
                mo_id = mo.get("id", "")
                if mo_id and mo_id not in module_overviews_seen:
                    module_overviews_seen.add(mo_id)
                    module_overview_texts.append(
                        f"{mo.get('module_name', '')}: {mo.get('summary', '')}"
                    )

            # 補完クエリ用にモジュール名を収集
            if source_module and source_module not in modules_seen:
                modules_seen.add(source_module)

        # ModuleOverview が未取得の場合、モジュール名で補完クエリを実行
        if not module_overview_texts and modules_seen:
            for module_name in modules_seen:
                try:
                    fallback_records = await neo4j_client.execute_query(
                        _MODULE_OVERVIEW_FALLBACK_CYPHER,
                        {"module_name": module_name},
                    )
                    if fallback_records:
                        r = fallback_records[0]
                        text = f"{r.get('module_name', module_name)}: {r.get('summary', '')}"
                        module_overview_texts.append(text)
                        logger.info(
                            "ModuleOverview補完: module=%s", module_name
                        )
                except Exception as e:
                    logger.warning(
                        "ModuleOverview補完クエリ失敗: module=%s, error=%s",
                        module_name,
                        e,
                    )

        module_overview_context = (
            "\n".join(module_overview_texts) if module_overview_texts else ""
        )

        return {
            "traversed_nodes": traversed_nodes,
            "module_overview_context": module_overview_context,
        }

    return traverse_graph_node
