"""Live GPU roof segmentation, served over HTTP.

Deliberately not imported by `pvmaps.api`: the API talks to this over the
network so that torch and SAM2 stay out of the 303 MB request-path image
(ARCHITECTURE.md 1). `tests/test_architecture.py` enforces that boundary.
"""
