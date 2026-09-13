"""Initial schema — ARCHITECTURE.md 6.

Revision ID: 0001
Revises:
Create Date: 2026-09-11
"""

from __future__ import annotations

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

WGS84 = 4326


def upgrade() -> None:
    # PostGIS for geometry; pg_trgm for address search without a live geocoder
    # (ARCHITECTURE.md 9.3).
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "addresses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("normalized_address", sa.String(512), nullable=False),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.Geometry("POINT", srid=WGS84, spatial_index=False),
            nullable=False,
        ),
        sa.Column("ward", sa.String(64)),
    )
    op.create_index(
        "ix_addresses_normalized_trgm",
        "addresses",
        ["normalized_address"],
        postgresql_using="gin",
        postgresql_ops={"normalized_address": "gin_trgm_ops"},
    )
    op.create_index("ix_addresses_geom", "addresses", ["geom"], postgresql_using="gist")

    op.create_table(
        "buildings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("address_id", sa.String(64), sa.ForeignKey("addresses.id")),
        sa.Column(
            "geom",
            geoalchemy2.Geometry("POLYGON", srid=WGS84, spatial_index=False),
            nullable=False,
        ),
        sa.Column("roof_area_m2", sa.Float, nullable=False),
        sa.Column("usable_area_m2", sa.Float, nullable=False),
        sa.Column("obstruction_geojson", sa.dialects.postgresql.JSONB),
        sa.Column("typology", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("analysed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("usable_area_m2 <= roof_area_m2", name="ck_usable_within_roof"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_confidence_unit"),
    )
    op.create_index("ix_buildings_geom", "buildings", ["geom"], postgresql_using="gist")

    op.create_table(
        "roof_analyses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("building_id", sa.String(64), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        # The five-column Estimate shape -- NFR-2. See db.models.estimate_columns.
        sa.Column("annual_yield_kwh_per_kwp", sa.Float, nullable=False),
        sa.Column("annual_yield_kwh_per_kwp_lo", sa.Float, nullable=False),
        sa.Column("annual_yield_kwh_per_kwp_hi", sa.Float, nullable=False),
        sa.Column("annual_yield_kwh_per_kwp_source", sa.String(16), nullable=False),
        sa.Column("annual_yield_kwh_per_kwp_confidence", sa.Float, nullable=False),
        sa.Column("monthly_yield_json", sa.dialects.postgresql.JSONB),
        sa.Column("loss_assumptions_json", sa.dialects.postgresql.JSONB),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("building_id", "version", name="uq_analysis_version"),
        sa.CheckConstraint(
            "annual_yield_kwh_per_kwp_lo <= annual_yield_kwh_per_kwp "
            "AND annual_yield_kwh_per_kwp <= annual_yield_kwh_per_kwp_hi",
            name="ck_yield_band_ordered",
        ),
    )

    for table in ("tariff_schedules", "subsidy_schedules"):
        op.create_table(
            table,
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("category", sa.String(32), nullable=False),
            sa.Column("version", sa.String(64), nullable=False),
            sa.Column("effective_from", sa.Date, nullable=False),
            sa.Column("effective_to", sa.Date),
            sa.Column("rules_json", sa.dialects.postgresql.JSONB, nullable=False),
            sa.Column("verification_status", sa.String(48), nullable=False),
            sa.UniqueConstraint("category", "version", name=f"uq_{table.split('_')[0]}_version"),
        )

    # No consumer number, name, address or bill-image column exists here, and
    # none may be added. ARCHITECTURE.md 8.
    op.create_table(
        "sizing_runs",
        sa.Column("id", sa.String(43), primary_key=True),  # token_urlsafe(32)
        sa.Column("building_id", sa.String(64), sa.ForeignKey("buildings.id"), nullable=False),
        sa.Column("tariff_version", sa.String(64), nullable=False),
        sa.Column("subsidy_version", sa.String(64), nullable=False),
        sa.Column("assumptions_version", sa.String(64), nullable=False),
        sa.Column("input_profile_json", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("roof_max_kwp", sa.Numeric(6, 2), nullable=False),
        sa.Column("sanctioned_load_max_kwp", sa.Numeric(6, 2), nullable=False),
        sa.Column("recommended_kwp", sa.Numeric(6, 2)),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("self_consumed_kwh_range_json", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("exported_kwh_range_json", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("savings_range_json", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("payback_range_years_json", sa.dialects.postgresql.JSONB),
        sa.Column("curve_json", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "recommended_kwp IS NULL OR recommended_kwp <= sanctioned_load_max_kwp",
            name="ck_recommendation_within_sanctioned_load",
        ),
        sa.CheckConstraint(
            "recommended_kwp IS NULL OR recommended_kwp <= roof_max_kwp",
            name="ck_recommendation_within_roof",
        ),
    )
    op.create_index("ix_sizing_runs_expires_at", "sizing_runs", ["expires_at"])


def downgrade() -> None:
    op.drop_table("sizing_runs")
    op.drop_table("subsidy_schedules")
    op.drop_table("tariff_schedules")
    op.drop_table("roof_analyses")
    op.drop_table("buildings")
    op.drop_table("addresses")
    # Extensions are left in place: other databases on the cluster may use them.
