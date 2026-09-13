"""Offline preparation — ARCHITECTURE.md 1's second plane.

Roof segmentation, obstruction correction and pvlib yield. Runs before a demo or
when pilot imagery changes; never on a request path, and never during judging
(ARCHITECTURE.md 9.1).

Nothing here is imported by `pvmaps.api`. tests/test_architecture.py enforces it.
"""
