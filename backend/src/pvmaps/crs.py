"""The two coordinate reference systems this system uses, and the rule between them.

Here rather than in `db.models` because both planes need them and they are a
domain fact, not a SQLAlchemy detail. `pipeline.roofs` importing them from the ORM
module would drag geoalchemy2 -- an `api` group dependency -- into the pipeline
image, which does not install it.
"""

from __future__ import annotations

__all__ = ["UTM_44N", "WGS84"]

WGS84 = 4326
"""Storage CRS. Lat/lon, no metric meaning: an area computed in this CRS comes
out in square degrees, which at Vellore's latitude is wrong by about ten orders
of magnitude while still being a positive float."""

UTM_44N = 32644
"""Computation CRS for the Vellore pilot (79.13 deg E falls in zone 44N).
ST_Transform into this before any ST_Area or ST_Distance, and use
`pipeline.roofs.area_m2` rather than `.area` anywhere in Python."""
