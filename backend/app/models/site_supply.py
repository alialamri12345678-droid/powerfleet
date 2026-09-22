"""Latest externally commissioned facility power measurements and plan."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SiteSupply(Base):
    __tablename__ = "site_supply"
    site_id: Mapped[str] = mapped_column(String(36), ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reading: Mapped[dict] = mapped_column(JSON, nullable=False)
    plan: Mapped[dict | None] = mapped_column(JSON)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
