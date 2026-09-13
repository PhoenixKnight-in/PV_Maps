"""Segmentation IoU — PRD 10's roof-segmentation acceptance criterion.

    "Roof segmentation | IoU of at least 0.75 on 50 held-out roofs;
     report the actual number"

Two clauses, and the second is the one with teeth. This module computes the
number and reports it whatever it says. There is no threshold argument that
quietly turns a failure into a pass, and `IoUReport.verdict` names the shortfall
rather than rounding it away.

PRD 12 lists flat-roof segmentation error as a known risk whose mitigation is to
"hand-correct demo roofs and report IoU honestly". Honestly means: measured on
roofs the model did not see, reported with n, and reported even when it is bad.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from shapely.geometry.base import BaseGeometry

__all__ = ["IoUReport", "evaluate", "iou"]

TARGET_IOU = 0.75
REQUIRED_ROOFS = 50


def iou(predicted: BaseGeometry, truth: BaseGeometry) -> float:
    """Intersection over union of two polygons, computed in UTM 44N.

    In metres, not degrees. IoU is a ratio so the units cancel and a degrees-based
    figure looks plausible — but the longitude/latitude scale difference at 12.9 N
    distorts the shapes themselves before the ratio is taken, which biases the
    result in a direction that depends on roof orientation.
    """
    from pvmaps.pipeline.roofs import to_utm

    a, b = to_utm(predicted), to_utm(truth)
    if not a.is_valid:
        a = a.buffer(0)
    if not b.is_valid:
        b = b.buffer(0)

    union = a.union(b).area
    if union <= 0:
        return 0.0
    return float(a.intersection(b).area / union)


@dataclass(frozen=True, slots=True)
class IoUReport:
    scores: tuple[float, ...]
    target: float = TARGET_IOU
    required_n: int = REQUIRED_ROOFS

    @property
    def n(self) -> int:
        return len(self.scores)

    @property
    def mean(self) -> float:
        return mean(self.scores) if self.scores else 0.0

    @property
    def median(self) -> float:
        return median(self.scores) if self.scores else 0.0

    @property
    def worst(self) -> float:
        return min(self.scores) if self.scores else 0.0

    @property
    def fraction_above_target(self) -> float:
        if not self.scores:
            return 0.0
        return sum(1 for s in self.scores if s >= self.target) / self.n

    @property
    def meets_criterion(self) -> bool:
        """Both clauses: enough roofs, and a mean at or above target."""
        return self.n >= self.required_n and self.mean >= self.target

    @property
    def verdict(self) -> str:
        if self.n < self.required_n:
            return (
                f"INSUFFICIENT EVIDENCE: {self.n} roofs measured, PRD 10 requires "
                f"{self.required_n}. Mean IoU so far is {self.mean:.3f}, which is "
                f"not yet a result."
            )
        if self.mean < self.target:
            return (
                f"BELOW TARGET: mean IoU {self.mean:.3f} over {self.n} roofs, "
                f"target {self.target:.2f}. Report this number. Do not lower the "
                f"target, and do not quietly drop the roofs that scored worst."
            )
        return (
            f"MEETS CRITERION: mean IoU {self.mean:.3f} over {self.n} roofs "
            f"(median {self.median:.3f}, worst {self.worst:.3f}, "
            f"{self.fraction_above_target:.0%} at or above {self.target:.2f})."
        )

    def to_json(self) -> dict[str, float | int | bool | str]:
        return {
            "n": self.n,
            "mean_iou": round(self.mean, 4),
            "median_iou": round(self.median, 4),
            "worst_iou": round(self.worst, 4),
            "fraction_above_target": round(self.fraction_above_target, 4),
            "target": self.target,
            "required_n": self.required_n,
            "meets_criterion": self.meets_criterion,
            "verdict": self.verdict,
        }


def evaluate(pairs: list[tuple[BaseGeometry, BaseGeometry]]) -> IoUReport:
    """Score (predicted, ground-truth) pairs.

    Every pair is scored, including the ones that score zero because the model
    found nothing. Dropping a miss from the denominator is the most common way an
    IoU number gets flattering, and it is why this takes pairs rather than
    matched detections.
    """
    return IoUReport(scores=tuple(iou(p, t) for p, t in pairs))
