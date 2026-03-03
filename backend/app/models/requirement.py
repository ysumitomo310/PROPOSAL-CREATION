from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class FunctionalRequirement(Base):
    __tablename__ = "functional_requirement"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("case.id", ondelete="CASCADE"))
    sequence_number: Mapped[int] = mapped_column(Integer)
    business_category: Mapped[str | None] = mapped_column(String(500), nullable=True)
    business_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    function_name: Mapped[str] = mapped_column(String(500))
    requirement_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    importance: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Must/Should/Could
    original_row_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped["Case"] = relationship(back_populates="functional_requirements")
    mapping_result: Mapped["MappingResult | None"] = relationship(
        back_populates="functional_requirement", uselist=False, cascade="all, delete-orphan"
    )


# Avoid circular import
from app.models.case import Case  # noqa: E402, F401
from app.models.mapping_result import MappingResult  # noqa: E402, F401
