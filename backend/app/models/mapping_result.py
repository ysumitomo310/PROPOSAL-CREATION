from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class MappingResult(Base):
    __tablename__ = "mapping_result"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    functional_requirement_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("functional_requirement.id", ondelete="CASCADE"), unique=True
    )
    judgment_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(50), nullable=True)  # High/Medium/Low
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0-1.0
    proposal_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)  # 旧フォーマット（後方互換）
    scope_item_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)  # ScopeItem適合根拠
    gap_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)        # ギャップ・課題
    judgment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)     # 判定結論
    matched_scope_items: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    related_nodes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    search_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    search_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    langsmith_trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending/processing/completed/error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    functional_requirement: Mapped["FunctionalRequirement"] = relationship(back_populates="mapping_result")


from app.models.requirement import FunctionalRequirement  # noqa: E402, F401
