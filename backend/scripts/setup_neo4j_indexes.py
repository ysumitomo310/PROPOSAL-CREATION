#!/usr/bin/env python3
"""Neo4j インデックス作成スクリプト

design.md で定義された5つのインデックスを作成する。
べき等（IF NOT EXISTS）なので再実行可能。

Usage:
    python scripts/setup_neo4j_indexes.py [--recreate-fulltext]
"""

import argparse
import asyncio
import os
import sys

from neo4j import AsyncGraphDatabase

INDEXES = [
    # 1. ScopeItem ベクトルインデックス（OpenAI text-embedding-3-large: 3072次元）
    """CREATE VECTOR INDEX scope_item_vector_idx IF NOT EXISTS
       FOR (n:ScopeItem) ON n.embedding
       OPTIONS {indexConfig: {
         `vector.dimensions`: 3072,
         `vector.similarity_function`: 'cosine'
       }}""",
    # 2. ModuleOverview ベクトルインデックス
    """CREATE VECTOR INDEX module_overview_vector_idx IF NOT EXISTS
       FOR (n:ModuleOverview) ON n.embedding
       OPTIONS {indexConfig: {
         `vector.dimensions`: 3072,
         `vector.similarity_function`: 'cosine'
       }}""",
    # 3. ScopeItem 全文検索インデックス（CJK Analyzer: 日本語バイグラム対応）
    #    function_name, description, keywords に加え module, business_domain も検索対象
    """CREATE FULLTEXT INDEX scope_item_fulltext_idx IF NOT EXISTS
       FOR (n:ScopeItem)
       ON EACH [n.function_name, n.description, n.keywords, n.module, n.business_domain]
       OPTIONS {indexConfig: {
         `fulltext.analyzer`: 'cjk'
       }}""",
    # 4. ScopeItem ID レンジインデックス
    """CREATE RANGE INDEX scope_item_id_idx IF NOT EXISTS
       FOR (n:ScopeItem) ON (n.id)""",
    # 5. ScopeItem product_namespace レンジインデックス
    """CREATE RANGE INDEX scope_item_ns_idx IF NOT EXISTS
       FOR (n:ScopeItem) ON (n.product_namespace)""",
]

INDEX_NAMES = [
    "scope_item_vector_idx",
    "module_overview_vector_idx",
    "scope_item_fulltext_idx",
    "scope_item_id_idx",
    "scope_item_ns_idx",
]


async def setup_indexes(
    uri: str, user: str, password: str, *, recreate_fulltext: bool = False
) -> None:
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    try:
        if recreate_fulltext:
            print("Dropping fulltext index for recreation...")
            async with driver.session() as session:
                await session.run("DROP INDEX scope_item_fulltext_idx IF EXISTS")
            print("  scope_item_fulltext_idx dropped.")

        async with driver.session() as session:
            for i, cypher in enumerate(INDEXES):
                await session.run(cypher)
                print(f"  [{i + 1}/{len(INDEXES)}] {INDEX_NAMES[i]} ... OK")

        # 検証: 作成されたインデックスを表示
        print("\n=== SHOW INDEXES ===")
        async with driver.session() as session:
            result = await session.run("SHOW INDEXES YIELD name, type, labelsOrTypes, properties")
            async for record in result:
                print(f"  {record['name']:40s} | {record['type']:10s} | {record['labelsOrTypes']} | {record['properties']}")
    finally:
        await driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Neo4j インデックス作成")
    parser.add_argument(
        "--recreate-fulltext",
        action="store_true",
        help="fulltextインデックスを削除して再作成（フィールド変更時に必要）",
    )
    args = parser.parse_args()

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7688")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")

    if not password:
        print("ERROR: NEO4J_PASSWORD is required. Set via environment variable or .env file.")
        sys.exit(1)

    print(f"Connecting to Neo4j: {uri}")
    asyncio.run(setup_indexes(uri, user, password, recreate_fulltext=args.recreate_fulltext))
    print("\nDone. All indexes created/verified.")


if __name__ == "__main__":
    main()
