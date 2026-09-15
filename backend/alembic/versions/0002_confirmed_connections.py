"""Confirmed service connections, keyed by a non-reversible digest.

ARCHITECTURE.md 8 forbids retaining consumer numbers. This table keeps the
rooftop a household confirmed WITHOUT keeping the number that identifies them:
the primary key is an HMAC of the service number under a server-side key, so
the row is reachable by someone who already knows the number and useless to
anyone reading the table.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "confirmed_connections",
        sa.Column("service_hash", sa.String(length=64), nullable=False),
        sa.Column("meter_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("accuracy_meters", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("geocode_level", sa.String(length=16), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_conn_confidence_unit"),
        sa.CheckConstraint("accuracy_meters > 0", name="ck_conn_accuracy_positive"),
        sa.PrimaryKeyConstraint("service_hash"),
    )
    op.create_index(
        "ix_confirmed_connections_meter_hash", "confirmed_connections", ["meter_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_confirmed_connections_meter_hash", table_name="confirmed_connections")
    op.drop_table("confirmed_connections")
