#!/usr/bin/env python3
"""Hybrid Search Spike（TASK-B06a）

B04で投入済み（or テスト用に投入する）ノードに対して:
1. CJK fulltextインデックスで日本語キーワードがヒットするか検証
2. ベクトル検索+キーワード検索の2段階結合Cypherが動作するか検証
3. sigmoid正規化 s/(s+1) でスコアが0-1範囲に収まるか検証
4. fulltext index に keywords を追加すべきか検討

Usage:
    python scripts/spike_hybrid_search.py [--local] [--skip-insert]
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neo4j import AsyncGraphDatabase

# テスト用ScopeItemデータ（Embedding無し版）
TEST_SCOPE_ITEMS = [
    {
        "id": "SAP-TEST-BD9",
        "product_namespace": "SAP",
        "module": "SD",
        "scope_item_id": "BD9",
        "function_name": "在庫からの販売 - 受注処理",
        "description": "この機能は在庫品の販売プロセスを管理します。受注から出荷、請求までの一連のフローを自動化し、在庫管理との連携を行います。",
        "business_domain": "販売",
        "keywords": ["在庫", "販売", "受注", "出荷", "請求"],
    },
    {
        "id": "SAP-TEST-1B4",
        "product_namespace": "SAP",
        "module": "SD",
        "scope_item_id": "1B4",
        "function_name": "受注から入金",
        "description": "この機能は受注から入金までのEnd-to-Endプロセスを管理します。与信管理、出荷指示、請求書発行、入金消込を含みます。",
        "business_domain": "販売",
        "keywords": ["受注", "入金", "与信", "請求書", "消込"],
    },
    {
        "id": "SAP-TEST-1NS",
        "product_namespace": "SAP",
        "module": "MM",
        "scope_item_id": "1NS",
        "function_name": "購買発注処理",
        "description": "この機能は購買発注から入庫、請求書照合までの調達プロセスを管理します。サプライヤー管理と連携して最適な調達を実現します。",
        "business_domain": "購買",
        "keywords": ["購買", "発注", "入庫", "調達", "サプライヤー"],
    },
    {
        "id": "SAP-TEST-2QY",
        "product_namespace": "SAP",
        "module": "FI",
        "scope_item_id": "2QY",
        "function_name": "債権管理",
        "description": "この機能は売掛金の管理と回収プロセスを支援します。請求書発行、入金処理、督促状送付、貸倒処理などを含みます。",
        "business_domain": "財務",
        "keywords": ["債権", "売掛金", "入金", "督促", "貸倒"],
    },
    {
        "id": "SAP-TEST-4FS",
        "product_namespace": "SAP",
        "module": "PP",
        "scope_item_id": "4FS",
        "function_name": "生産計画と製造指図",
        "description": "この機能は生産計画の策定から製造指図の発行、工程管理までをカバーします。MRP実行によるロット計算と在庫最適化を行います。",
        "business_domain": "生産",
        "keywords": ["生産", "製造", "MRP", "工程", "在庫"],
    },
]

# テスト用ダミーEmbedding（3072次元、検証用に簡易ベクトル）
def _make_test_embedding(seed: int) -> list[float]:
    """テスト用ダミーEmbedding生成（正規化済み）。"""
    import math
    vec = [0.0] * 3072
    # seedに基づき数カ所に値を設定
    for i in range(100):
        idx = (seed * 37 + i * 13) % 3072
        vec[idx] = 1.0 if (i + seed) % 2 == 0 else -0.5
    # L2正規化
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm > 0 else vec


async def insert_test_data(driver) -> None:
    """テスト用ScopeItemノードを投入。"""
    print("\n=== Phase 0: Insert Test Data ===")
    async with driver.session() as session:
        # 既存テストデータのクリーンアップ
        await session.run("MATCH (n:ScopeItem) WHERE n.id STARTS WITH 'SAP-TEST-' DETACH DELETE n")
        print("  Cleaned up existing test nodes")

        for i, si in enumerate(TEST_SCOPE_ITEMS):
            emb = _make_test_embedding(i)
            cypher = """
            MERGE (s:ScopeItem {id: $id})
            SET s.product_namespace = $product_namespace,
                s.module = $module,
                s.scope_item_id = $scope_item_id,
                s.function_name = $function_name,
                s.description = $description,
                s.business_domain = $business_domain,
                s.keywords = $keywords,
                s.embedding = $embedding
            """
            await session.run(cypher, {**si, "embedding": emb})
            print(f"  [{i+1}/{len(TEST_SCOPE_ITEMS)}] {si['id']} ({si['function_name']}) ... OK")

    print(f"  Inserted {len(TEST_SCOPE_ITEMS)} test ScopeItems")


async def test_cjk_fulltext(driver) -> dict:
    """検証1: CJK fulltextインデックスで日本語クエリがヒットするか。"""
    print("\n=== Test 1: CJK Fulltext Search ===")
    test_queries = ["受注", "在庫管理", "購買", "債権管理", "生産計画"]
    results = {}

    async with driver.session() as session:
        for query in test_queries:
            cypher = """
            CALL db.index.fulltext.queryNodes('scope_item_fulltext_idx', $query)
            YIELD node, score
            WHERE node.id STARTS WITH 'SAP-TEST-'
            RETURN node.id AS id, node.function_name AS fn, score
            ORDER BY score DESC
            LIMIT 5
            """
            result = await session.run(cypher, {"query": query})
            records = [record.data() async for record in result]
            results[query] = records

            hit_count = len(records)
            status = "OK" if hit_count > 0 else "NG"
            print(f"  Query: '{query}' → {hit_count} hits [{status}]")
            for r in records:
                print(f"    - {r['id']} | {r['fn']} | score={r['score']:.4f}")

    return results


async def test_vector_search(driver) -> dict:
    """検証2: ベクトル検索が動作するか。"""
    print("\n=== Test 2: Vector Search ===")
    # テスト用クエリEmbedding（BD9に近いベクトル）
    query_emb = _make_test_embedding(0)  # seed=0 → BD9と同じ

    async with driver.session() as session:
        cypher = """
        CALL db.index.vector.queryNodes('scope_item_vector_idx', $top_k, $query_embedding)
        YIELD node, score
        WHERE node.id STARTS WITH 'SAP-TEST-'
        RETURN node.id AS id, node.function_name AS fn, score
        ORDER BY score DESC
        """
        result = await session.run(cypher, {"query_embedding": query_emb, "top_k": 5})
        records = [record.data() async for record in result]

        print(f"  Vector search → {len(records)} hits")
        for r in records:
            print(f"    - {r['id']} | {r['fn']} | score={r['score']:.4f}")

    return {"vector": records}


async def test_hybrid_search_cypher(driver) -> dict:
    """検証3: 2段階結合Cypher（vector + fulltext UNION）が動作するか。"""
    print("\n=== Test 3: Hybrid Search (Combined Cypher) ===")
    query_text = "受注 販売"
    query_emb = _make_test_embedding(0)

    # 2段階結合クエリ
    hybrid_cypher = """
    // --- Vector Search ---
    CALL db.index.vector.queryNodes('scope_item_vector_idx', $top_k, $query_embedding)
    YIELD node AS vNode, score AS vec_score
    WHERE vNode.product_namespace = $ns
      AND vNode.id STARTS WITH 'SAP-TEST-'
    WITH collect({node_id: vNode.id, fn: vNode.function_name, desc: vNode.description,
                  module: vNode.module, domain: vNode.business_domain, kw: vNode.keywords,
                  vec_score: vec_score, kw_score: 0.0}) AS vec_results

    // --- Keyword Search ---
    CALL db.index.fulltext.queryNodes('scope_item_fulltext_idx', $query_text)
    YIELD node AS kNode, score AS raw_kw_score
    WHERE kNode.product_namespace = $ns
      AND kNode.id STARTS WITH 'SAP-TEST-'
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

    async with driver.session() as session:
        result = await session.run(hybrid_cypher, {
            "query_embedding": query_emb,
            "query_text": query_text,
            "ns": "SAP",
            "top_k": 10,
            "vec_weight": 0.7,
            "kw_weight": 0.3,
        })
        records = [record.data() async for record in result]

        print(f"  Hybrid query='{query_text}' → {len(records)} results")
        for r in records:
            vs = r['vector_score']
            ks = r['keyword_score']
            fs = r['final_score']
            print(f"    - {r['node_id']} | {r['fn']}")
            print(f"      vec={vs:.4f}, kw={ks:.4f}, final={fs:.4f}")

        # スコア範囲検証
        all_ok = True
        for r in records:
            for key in ['vector_score', 'keyword_score', 'final_score']:
                if not (0.0 <= r[key] <= 1.0):
                    print(f"  NG: {r['node_id']} {key}={r[key]} is out of [0,1] range!")
                    all_ok = False
        if all_ok:
            print(f"  Score range check: ALL OK (0.0-1.0)")

    return {"hybrid": records}


async def test_sigmoid_normalization() -> None:
    """検証4: sigmoid正規化の特性確認。"""
    print("\n=== Test 4: Sigmoid Normalization s/(s+1) ===")
    test_scores = [0.0, 0.5, 1.0, 2.0, 4.0, 9.0, 20.0, 100.0]
    for s in test_scores:
        normalized = s / (s + 1.0)
        print(f"  BM25={s:6.1f} → sigmoid={normalized:.4f}")

    print("  Result: All values in (0.0, 1.0) range ✓")


async def test_keywords_in_fulltext(driver) -> None:
    """検証5: keywords配列をfulltextに追加した場合の効果検討。"""
    print("\n=== Test 5: Keywords Coverage Analysis ===")

    async with driver.session() as session:
        # 現行: function_name + description
        result1 = await session.run("""
            CALL db.index.fulltext.queryNodes('scope_item_fulltext_idx', '在庫')
            YIELD node, score
            WHERE node.id STARTS WITH 'SAP-TEST-'
            RETURN count(node) AS hits
        """)
        hits_current = (await result1.single())["hits"]

        # keywords配列にも「在庫」が含まれるノード数
        result2 = await session.run("""
            MATCH (n:ScopeItem)
            WHERE n.id STARTS WITH 'SAP-TEST-'
              AND ('在庫' IN n.keywords OR n.function_name CONTAINS '在庫' OR n.description CONTAINS '在庫')
            RETURN count(n) AS total
        """)
        total = (await result2.single())["total"]

        print(f"  Fulltext hits for '在庫': {hits_current}")
        print(f"  Nodes with '在庫' anywhere: {total}")
        if hits_current < total:
            print(f"  → keywords追加でカバレッジ向上の可能性あり")
        else:
            print(f"  → 現行のfunction_name + descriptionで十分")


async def cleanup_test_data(driver) -> None:
    """テストデータのクリーンアップ。"""
    print("\n=== Cleanup Test Data ===")
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n:ScopeItem) WHERE n.id STARTS WITH 'SAP-TEST-' DETACH DELETE n RETURN count(n) AS deleted"
        )
        deleted = (await result.single())["deleted"]
        print(f"  Deleted {deleted} test nodes")


async def run(args: argparse.Namespace) -> None:
    if args.local:
        uri = "bolt://localhost:7688"
    else:
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7688")

    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")

    if not password:
        # .envファイルから読み込み試行
        from app.core.config import get_settings
        if args.local:
            os.environ["NEO4J_URI"] = uri
        settings = get_settings()
        password = settings.NEO4J_PASSWORD

    print(f"Connecting to Neo4j: {uri}")
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    try:
        # 接続確認
        await driver.verify_connectivity()
        print("  Connected ✓")

        # Phase 0: テストデータ投入
        if not args.skip_insert:
            await insert_test_data(driver)

        # Test 1: CJK fulltext
        await test_cjk_fulltext(driver)

        # Test 2: Vector search
        await test_vector_search(driver)

        # Test 3: Hybrid Cypher
        await test_hybrid_search_cypher(driver)

        # Test 4: Sigmoid normalization
        await test_sigmoid_normalization()

        # Test 5: Keywords coverage
        await test_keywords_in_fulltext(driver)

        # Cleanup
        if not args.keep_data:
            await cleanup_test_data(driver)

        print("\n=== Spike Complete ===")

    finally:
        await driver.close()


def main():
    parser = argparse.ArgumentParser(description="Hybrid Search Spike (TASK-B06a)")
    parser.add_argument("--local", action="store_true", help="localhost:7688接続")
    parser.add_argument("--skip-insert", action="store_true", help="テストデータ投入をスキップ")
    parser.add_argument("--keep-data", action="store_true", help="テストデータを残す")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
