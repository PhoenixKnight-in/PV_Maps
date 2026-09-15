"""Non-reversible identifiers for EB service and meter numbers.

A household's connection number is the natural key for "show me my roof again",
and it is also the thing ARCHITECTURE.md 8 says not to retain. Both can be true
at once: what the database needs is something that MATCHES a number, not
something that IS one.

So the stored key is `HMAC-SHA256(key, normalised number)`. Given the number you
can find the row; given the table you cannot find the numbers.

WHY HMAC AND NOT A PLAIN DIGEST. A TNEB service number is short and heavily
structured -- region, section and distribution codes each come from small sets
-- so the space of real numbers is small enough to enumerate and precompute.
An unsalted SHA-256 column would be reversible in practice by anyone who
obtained it. The key is what makes the digest worthless on its own.

WHY THE KEY MUST BE CONFIGURED. A key generated at startup would change on every
restart, every stored row would stop matching, and the feature would silently
do nothing -- which is worse than not having it, because it looks like it works
until someone comes back the next day. With no key configured, persistence is
refused outright and the caller falls back to the in-memory store.
"""

from __future__ import annotations

import hmac
import os
import re
from hashlib import sha256

CONNECTION_HASH_KEY = os.environ.get("CONNECTION_HASH_KEY", "").strip()
"""Server-side HMAC key. Set it to a long random string, keep it out of git,
and understand that CHANGING IT ORPHANS EVERY STORED ROW -- the digests will no
longer match, and no household will be found by their number again."""


def persistence_enabled() -> bool:
    """False when no key is configured, which disables storage entirely."""
    return bool(CONNECTION_HASH_KEY)


def normalise(number: str | None) -> str | None:
    """Strip the punctuation people and bills disagree about.

    `08-211-019-1233`, `08 211 019 1233` and `082110191233` are one connection.
    """
    if not number:
        return None
    cleaned = re.sub(r"[^0-9a-zA-Z]", "", number).upper()
    return cleaned or None


def digest(number: str | None) -> str | None:
    """HMAC of a connection number, or None if there is nothing to hash."""
    cleaned = normalise(number)
    if cleaned is None or not CONNECTION_HASH_KEY:
        return None
    return hmac.new(
        CONNECTION_HASH_KEY.encode("utf-8"), cleaned.encode("utf-8"), sha256
    ).hexdigest()
