"""The Estimate generic — the enforcement mechanism for PRD NFR-2.

    "Every inferred value renders with its confidence band.
     No inferred figure is ever displayed as precise fact."

That requirement fails if it is enforced by discipline, because discipline
decays under deadline. So it is enforced by the type system instead: nothing in
this system carries a bare number that could have been inferred. Values that
genuinely are known go through `Estimate.exact()`, which collapses the band --
so the UI has exactly one type to render, and "is this measured or guessed?" is
always answerable in-band.

See ARCHITECTURE.md 7.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

__all__ = ["Estimate", "Source"]

Source = Literal[
    "surveyed",       # someone physically stood there with a GPS (FR-3.1)
    "published",      # a regulator or DISCOM published it
    "user_supplied",  # read off an uploaded bill (FR-7.1)
    "inferred",       # this model produced it -- band is mandatory and real
]

class Estimate[T: (int, float)](BaseModel):
    """A number that knows how much it should be trusted.

    >>> Estimate.exact(3.0, source="user_supplied").is_certain
    True
    >>> Estimate(value=100.0, lo=30.0, hi=90.0, source="inferred", confidence=0.4)
    Traceback (most recent call last):
        ...
    pydantic_core._pydantic_core.ValidationError: ...
    """

    model_config = {"frozen": True}

    value: T
    lo: T
    hi: T
    source: Source
    confidence: float = Field(ge=0.0, le=1.0)
    as_of: date | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check_band(self) -> Self:
        if not (self.lo <= self.value <= self.hi):
            raise ValueError(
                f"band violated: lo={self.lo} <= value={self.value} <= hi={self.hi} is false"
            )
        if self.source != "inferred" and self.lo != self.hi:
            raise ValueError(
                f"source={self.source!r} claims the value is known, but the band is "
                f"[{self.lo}, {self.hi}]. Use source='inferred' or collapse the band."
            )
        return self

    @classmethod
    def exact(cls, value: T, *, source: Source = "published", **kw: object) -> Estimate[T]:
        """A value that is actually known. Band collapses, confidence is 1.0."""
        if source == "inferred":
            raise ValueError("inferred values are never exact -- use the normal constructor")
        return cls(value=value, lo=value, hi=value, source=source, confidence=1.0, **kw)  # type: ignore[arg-type]

    @property
    def is_certain(self) -> bool:
        return self.source != "inferred" and self.lo == self.hi

    @property
    def spread(self) -> float:
        """Width of the band, in the value's own units. 0.0 when certain."""
        return float(self.hi) - float(self.lo)

    def render(self, unit: str = "", places: int = 1) -> str:
        """The one place a number becomes user-facing text.

        Deliberately impossible to call in a way that hides the band.
        PRD 10: "Label estimates as estimates IN THE UI. Never fabricate a
        precise number."
        """
        suffix = f" {unit}" if unit else ""
        if self.is_certain:
            return f"{self.value:.{places}f}{suffix}"
        return f"{self.value:.{places}f}{suffix} (est. {self.lo:.{places}f}-{self.hi:.{places}f})"
