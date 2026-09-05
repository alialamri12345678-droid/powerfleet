"""PowerSetpoint model — optional base-load / fixed-power targets per panel."""

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class PowerSetpoint(Base, TenantMixin, TimestampMixin):
    __tablename__ = "power_setpoints"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sites.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    panel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("panels.id", ondelete="CASCADE"),
        index=True, nullable=False, unique=True,
    )

    target_kw_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0,
        comment="Fixed-power kW target as % of rated",
    )
    target_kvar_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0,
        comment="Fixed reactive power kVAr target as % of rated",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    # Relationships
    panel = relationship("Panel", back_populates="power_setpoint")

    def __repr__(self) -> str:
        return (
            f"<PowerSetpoint panel={self.panel_id!r} "
            f"kw={self.target_kw_pct}% kvar={self.target_kvar_pct}%>"
        )
