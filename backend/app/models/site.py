"""Site model — one per customer installation."""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, generate_uuid


class Site(Base, TimestampMixin):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC"
    )
    max_parallel_units: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None,
        comment="Optional cap on how many generators can run simultaneously",
    )

    # Relationships
    panels = relationship("Panel", back_populates="site", cascade="all, delete-orphan")
    thresholds = relationship("Threshold", back_populates="site", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="site", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Site id={self.id!r} name={self.name!r}>"
