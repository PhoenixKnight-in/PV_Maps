"""Address normalisation — one function, shared by the seeder and the search route.

ARCHITECTURE.md 9.3: search resolves against our own `addresses` table rather
than a live geocoder, so there is no geocoder to fail on stage. That only works
if the string the pipeline wrote and the string the browser is matched against
were normalised the same way. Two copies of "lowercase and strip punctuation"
drift, and the symptom is a pilot address that cannot be found during a demo.

Pure. No dependencies beyond the standard library -- the pipeline image and the
API image both import it.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normalize_address"]

_PUNCT = re.compile(r"[^\w\s]+", flags=re.UNICODE)
_SPACE = re.compile(r"\s+")

_ABBREVIATIONS = {
    "rd": "road",
    "st": "street",
    "nr": "near",
    "opp": "opposite",
    "clg": "college",
    "apts": "apartments",
    "blk": "block",
    "nagar": "nagar",
}


def normalize_address(raw: str) -> str:
    """Fold an address to its search key.

    Casefolded, NFKC-normalised, punctuation-free, single-spaced, with a short
    list of Indian address abbreviations expanded so that "12 Katpadi Rd" and
    "12 Katpadi Road" land on the same key.

    Deliberately not a geocoder and deliberately not clever: it never drops a
    token, because dropping one silently merges two distinct pilot addresses.
    """
    folded = unicodedata.normalize("NFKC", raw).casefold()
    folded = _PUNCT.sub(" ", folded)
    tokens = [_ABBREVIATIONS.get(t, t) for t in _SPACE.split(folded) if t]
    return " ".join(tokens)
