from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Case(Base):
    __tablename__ = "case"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    product: Mapped[str] = mapped_column(String(50))  # "SAP" or "GRANDIT"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    column_mapping: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    excel_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="created")  # created/mapping/completed
    total_requirements: Mapped[int] = mapped_column(Integer, default=0)
    completed_requirements: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    functional_requirements: Mapped[list["FunctionalRequirement"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


# Avoid circular import: FunctionalRequirement is defined in requirement.py
from app.models.requirement import FunctionalRequirement  # noqa: E402, F401
