"""Embedding サービス（TASK-B04）

OpenAI text-embedding-3-large を使用した3072次元ベクトル生成。
KnowledgeLoader と HybridSearchService の両方で再利用される。
"""

import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class EmbeddingService:
    """OpenAI Embedding APIラッパー。"""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-large",
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self.dimensions = 3072

    async def embed_single(self, text: str) -> list[float]:
        """単一テキストのEmbeddingを生成。"""
        response = await self._client.embeddings.create(
            input=text,
            model=self._model,
        )
        return response.data[0].embedding

    async def embed_batch(
        self, texts: list[str], batch_size: int = 50
    ) -> list[list[float]]:
        """バッチEmbedding生成。

        OpenAI APIはバッチサイズ制限があるため、batch_size単位で分割して呼び出す。
        """
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            logger.info(
                "Embedding batch %d/%d (%d items)",
                i // batch_size + 1,
                (len(texts) + batch_size - 1) // batch_size,
                len(batch),
            )
            response = await self._client.embeddings.create(
                input=batch,
                model=self._model,
            )
            all_embeddings.extend([item.embedding for item in response.data])
        return all_embeddings
