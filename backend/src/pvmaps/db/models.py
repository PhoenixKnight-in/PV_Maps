"""SQLAlchemy models — ARCHITECTURE.md 6.

Two disciplines are enforced here rather than left to reviewers:

1. **CRS.** Geometry is stored in EPSG:4326 and every area or distance is
   computed in EPSG:32644 (UTM 44N, which covers Vellore at 79.13 deg E).
   Skipping the transform silently inflates every roof area.

2. **Bands.** Anything inferred is stored as five columns via
   `estimate_columns()`, never as a bare number. ARCHITECTURE.md 7 -- the API
   must never present an estimate as an observed fact, and it cannot if the
   database has nowhere to put a bare one.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from pvmaps.crs import UTM_44N, WGS84

__all__ = [
    "UTM_44N",
    "WGS84",
    "Address",
    "Base",
    "Building",
    "RoofAnalysis",
    "SizingRun",
    "SubsidyScheduleRow",
    "TariffScheduleRow",
]

# WGS84 and UTM_44N are defined in pvmaps.crs and re-exported here, because both
# planes need them and the pipeline image does not install geoalchemy2.


class Base(DeclarativeBase):
    pass


def estimate_columns(name: str) -> list[str]:
    """The five column names for one inferred quantity.

    Anything inferred is stored as value / lo / hi / source / confidence rather
    than as a bare Float, so that NFR-2 is a property of the schema. If a value
    is genuinely known, write lo == value == hi with source != 'inferred'; the
    Estimate type enforces that pairing on the way out.

    Named in one place so migrations and the row-to-Estimate mapper agree.
    """
    return [name, f"{name}_lo", f"{name}_hi", f"{name}_source", f"{name}_confidence"]


class Address(Base):
    """Pre-geocoded pilot addresses.

    ARCHITECTURE.md 9.3: search resolves against this table, not against a
    live geocoder. One less thing that can fail on stage, and it is why
    `GET /v1/search` has no network dependency.
    """

    __tablename__ = "addresses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    normalized_address: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    geom = mapped_column(Geometry("POINT", srid=WGS84), nullable=False)
    ward: Mapped[str | None] = mapped_column(String(64))

    buildings: Mapped[list[Building]] = relationship(back_populates="address")

    __table_args__ = (
        # pg_trgm index; created in the migration, declared here for clarity.
        Index(
            "ix_addresses_normalized_trgm",
            "normalized_address",
            postgresql_using="gin",
            postgresql_ops={"normalized_address": "gin_trgm_ops"},
        ),
        Index("ix_addresses_geom", "geom", postgresql_using="gist"),
    )


class Building(Base):
    """One extracted roof. Written by the offline pipeline only."""

    __tablename__ = "buildings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    address_id: Mapped[str | None] = mapped_column(ForeignKey("addresses.id"))
    geom = mapped_column(Geometry("POLYGON", srid=WGS84), nullable=False)

    roof_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    usable_area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    obstruction_geojson: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    typology: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    analysed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    address: Mapped[Address | None] = relationship(back_populates="buildings")
    analyses: Mapped[list[RoofAnalysis]] = relationship(back_populates="building")

    __table_args__ = (
        CheckConstraint("usable_area_m2 <= roof_area_m2", name="ck_usable_within_roof"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_confidence_unit"),
        Index("ix_buildings_geom", "geom", postgresql_using="gist"),
    )


class RoofAnalysis(Base):
    """pvlib output for one building under one model version.

    Versioned rather than overwritten so a result can be reproduced later
    (NFR-4) -- a number shown to a user must stay explicable after the model
    that produced it has moved on.
    """

    __tablename__ = "roof_analyses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)

    # The five-column Estimate shape, written out. This is what
    # estimate_columns() documents; see NFR-2 in the module docstring.
    annual_yield_kwh_per_kwp: Mapped[float] = mapped_column(Float, nullable=False)
    annual_yield_kwh_per_kwp_lo: Mapped[float] = mapped_column(Float, nullable=False)
    annual_yield_kwh_per_kwp_hi: Mapped[float] = mapped_column(Float, nullable=False)
    annual_yield_kwh_per_kwp_source: Mapped[str] = mapped_column(String(16), nullable=False)
    annual_yield_kwh_per_kwp_confidence: Mapped[float] = mapped_column(Float, nullable=False)

    monthly_yield_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    loss_assumptions_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    building: Mapped[Building] = relationship(back_populates="analyses")

    __table_args__ = (
        UniqueConstraint("building_id", "version", name="uq_analysis_version"),
        CheckConstraint(
            "annual_yield_kwh_per_kwp_lo <= annual_yield_kwh_per_kwp "
            "AND annual_yield_kwh_per_kwp <= annual_yield_kwh_per_kwp_hi",
            name="ck_yield_band_ordered",
        ),
    )


class TariffScheduleRow(Base):
    """Mirror of config/tariffs/*.json.

    The JSON files stay the source of truth -- they version with the code and
    the pure engine reads them without a database. This table exists so a
    sizing_run can record exactly which rules produced it, and so the UI can
    serve `GET /v1/tariffs/current` without loading the calculation package.
    """

    __tablename__ = "tariff_schedules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(48), nullable=False)

    __table_args__ = (UniqueConstraint("category", "version", name="uq_tariff_version"),)


class SubsidyScheduleRow(Base):
    __tablename__ = "subsidy_schedules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    verification_status: Mapped[str] = mapped_column(String(48), nullable=False)

    __table_args__ = (UniqueConstraint("category", "version", name="uq_subsidy_version"),)


class ConfirmedConnection(Base):
    """A service connection whose rooftop a household has confirmed.

    This table exists so that "locate by service number" survives a restart.
    It is deliberately shaped to hold as little as possible about a person.

    WHY THE NUMBER IS NOT STORED. ARCHITECTURE.md 8 says "do not log consumer
    numbers, names, addresses". A row of (service number -> rooftop) is a record
    of which household lives at which roof, which is precisely what that line
    exists to prevent. So the lookup key is an HMAC of the number under a
    server-side key, never the number itself: a lookup hashes its input and
    matches, and the table cannot be read back into a list of connections.

    Plain SHA-256 would not be enough. A TNEB service number is short and
    heavily structured -- region, section and distribution codes come from small
    sets -- so an unsalted digest of every possible number is cheap to
    precompute. The HMAC key is what makes the digest useless without the
    server.

    There is no consumer_name, no address and no section column here, and as on
    `sizing_runs`, no column to add one to.
    """

    __tablename__ = "confirmed_connections"

    service_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    """HMAC-SHA256 of the normalised service number, hex. Not reversible."""

    meter_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    """Same construction for the meter number, so either identifier resolves."""

    geom = mapped_column(Geometry("POINT", srid=WGS84), nullable=False)
    """The confirmed service point. A coordinate IS personal data, which is why
    it is reachable only by someone who already knows the connection number."""

    accuracy_meters: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    geocode_level: Mapped[str] = mapped_column(String(16), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_conn_confidence_unit"),
        CheckConstraint("accuracy_meters > 0", name="ck_conn_accuracy_positive"),
    )


class SizingRun(Base):
    """One recommendation, as returned to one browser.

    ARCHITECTURE.md 6: "A bill upload is not the source of truth. The confirmed
    profile submitted to the sizing endpoint is the calculation input. Persist
    only the minimum confirmed values needed for a user-requested result."

    ARCHITECTURE.md 8: the id is a short-lived opaque token, never a sequential
    database key, so a run cannot be enumerated. There is deliberately no
    consumer number, name, address or bill image column on this table -- and no
    column to add one to.
    """

    __tablename__ = "sizing_runs"

    id: Mapped[str] = mapped_column(String(43), primary_key=True)  # token_urlsafe(32)
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), nullable=False)

    tariff_version: Mapped[str] = mapped_column(String(64), nullable=False)
    subsidy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    assumptions_version: Mapped[str] = mapped_column(String(64), nullable=False)

    input_profile_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """Confirmed monthly units, occupancy archetype, sanctioned load,
    modifiers. Nothing that identifies a person."""

    roof_max_kwp: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    sanctioned_load_max_kwp: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    recommended_kwp: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)

    self_consumed_kwh_range_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    exported_kwh_range_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    savings_range_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payback_range_years_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    curve_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "recommended_kwp IS NULL OR recommended_kwp <= sanctioned_load_max_kwp",
            name="ck_recommendation_within_sanctioned_load",
        ),
        CheckConstraint(
            "recommended_kwp IS NULL OR recommended_kwp <= roof_max_kwp",
            name="ck_recommendation_within_roof",
        ),
        Index("ix_sizing_runs_expires_at", "expires_at"),
    )
