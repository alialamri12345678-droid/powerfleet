"""Panel model — one per DSE controller at a site."""

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class Panel(Base, TenantMixin, TimestampMixin):
    __tablename__ = "panels"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sites.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Modbus connection details
    transport_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="tcp",
        comment="'tcp' or 'rtu'",
    )
    address: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="IP:port for TCP, serial port path for RTU",
    )
    unit_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Modbus unit/slave ID",
    )

    # Rated capacity
    rated_kw: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0,
    )
    rated_kvar: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0,
    )

    # Backup priority (lower = higher priority when choosing which backup starts first)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100,
        comment="Lower value = higher backup priority",
    )
    
    lead_rotation_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100,
        comment="Order of preference for being the lead generator (lower = more preferred)",
    )

    maintenance_mode: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="If True, panel is skipped in rotation and backup selection",
    )

    # Relationships
    site = relationship("Site", back_populates="panels")
    schedules = relationship("Schedule", back_populates="panel", cascade="all, delete-orphan")
    power_setpoint = relationship("PowerSetpoint", back_populates="panel", uselist=False, cascade="all, delete-orphan")
    overrides = relationship("Override", back_populates="panel", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Panel id={self.id!r} name={self.name!r} site={self.site_id!r}>"
