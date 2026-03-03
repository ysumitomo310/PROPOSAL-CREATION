from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ModuleClassification(Base):
    __tablename__ = "module_classification"

    scope_item_prefix: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. "1B4"
    module: Mapped[str] = mapped_column(String(20))  # e.g. "SD"
    module_name_ja: Mapped[str] = mapped_column(String(100))  # e.g. "販売管理"
    business_domain: Mapped[str] = mapped_column(String(100))  # e.g. "Sales"
    product: Mapped[str] = mapped_column(String(50))  # "SAP" or "GRANDIT"
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
