"""FastAPI アプリケーション エントリポイント（TASK-A02 + D01/D02/D03）"""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cases import router as cases_router
from app.api.knowledge import router as knowledge_router
from app.api.mapping import router as mapping_router
from app.core.config import get_settings
from app.core.database import create_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.session_factory = create_session_factory(settings)

    # LangSmith 環境変数セット（D03）
    if settings.langsmith_enabled:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
        logger.info("LangSmith tracing enabled: project=%s", settings.LANGCHAIN_PROJECT)

    # マッピングエンジン依存の初期化はマッピングAPI初回使用時に遅延ロード
    # （テスト時にNeo4j/LLM接続が不要なため）
    app.state.active_batch_processors = {}

    yield


app = FastAPI(
    title="ProposalCreation API",
    description="ERP Proposal Creation Support System",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cases_router)
app.include_router(knowledge_router)
app.include_router(mapping_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
