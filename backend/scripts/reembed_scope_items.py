#!/usr/bin/env python3
"""ScopeItem Embedding 再生成スクリプト

Neo4j上の既存ScopeItemプロパティ（function_name, description, module, business_domain, keywords）
から新しいEmbeddingテキストを構築し、OpenAI Embeddingを再生成してNeo4jを更新する。

BPD再パースやLLM description再生成は不要。Embedding再計算のみ。

Usage:
    python scripts/reembed_scope_items.py --local
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.core.embedding import EmbeddingService
from app.core.neo4j_client import Neo4jClient


def build_embed_text(node: dict) -> str:
    """ScopeItem用Embeddingテキストを構築（loader.pyと同じロジック）。"""
    parts = [node.get("function_name", ""), node.get("description", "")]
    if node.get("module"):
        parts.append(node["module"])
    if node.get("business_domain"):
        parts.append(node["business_domain"])
    keywords = node.get("keywords")
    if keywords:
        if isinstance(keywords, list):
            parts.append(" ".join(keywords))
        else:
            parts.append(str(keywords))
    return " ".join(parts)


async def run(args: argparse.Namespace) -> None:
    if args.local:
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5435"
        os.environ["NEO4J_URI"] = "bolt://localhost:7688"

    settings = get_settings()
    start = time.time()

    neo4j = Neo4jClient(
        uri=settings.NEO4J_URI,
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD,
    )

    embedding_service = EmbeddingService(
        api_key=settings.OPENAI_API_KEY,
        model=settings.EMBEDDING_MODEL,
    )

    # 1. 全ScopeItemを取得
    print("Fetching all ScopeItems from Neo4j...")
    records = await neo4j.execute_query(
        "MATCH (s:ScopeItem) RETURN s.id AS id, s.function_name AS function_name, "
        "s.description AS description, s.module AS module, "
        "s.business_domain AS business_domain, s.keywords AS keywords "
        "ORDER BY s.id"
    )
    print(f"  Found {len(records)} ScopeItems")

    if not records:
        print("No ScopeItems found. Exiting.")
        await neo4j.close()
        return

    # 2. Embeddingテキスト構築
    texts = [build_embed_text(r) for r in records]
    ids = [r["id"] for r in records]

    # サンプル表示
    print(f"\nSample embed text (first 3):")
    for i in range(min(3, len(texts))):
        print(f"  [{ids[i]}] {texts[i][:100]}...")

    # 3. Embedding一括生成
    print(f"\nGenerating embeddings ({len(texts)} items, batch_size=50)...")
    embeddings = await embedding_service.embed_batch(texts, batch_size=50)
    print(f"  Generated {len(embeddings)} embeddings (dim={len(embeddings[0])})")

    # 4. Neo4jに書き戻し
    print(f"\nUpdating Neo4j embeddings...")
    for i, (node_id, emb) in enumerate(zip(ids, embeddings)):
        await neo4j.execute_write(
            "MATCH (s:ScopeItem {id: $id}) SET s.embedding = $embedding",
            {"id": node_id, "embedding": emb},
        )
        if (i + 1) % 100 == 0:
            print(f"  [{i + 1}/{len(ids)}] updated...")

    elapsed = time.time() - start
    print(f"\nDone. {len(ids)} ScopeItems re-embedded in {elapsed:.1f}s")

    await neo4j.close()


def main():
    parser = argparse.ArgumentParser(description="ScopeItem Embedding再生成")
    parser.add_argument("--local", action="store_true", help="ローカル実行（localhost接続）")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
