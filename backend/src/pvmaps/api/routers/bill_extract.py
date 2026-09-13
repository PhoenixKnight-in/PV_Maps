"""POST /v1/bill-extract — optional convenience, never product logic.

ARCHITECTURE.md 4.3:

    "This keeps OCR as convenience, not product logic."
    "The original upload is discarded after extraction unless retention is
     explicitly requested."

ARCHITECTURE.md 8:

    "Limit bill-extraction requests by IP and size."
    "Process uploaded bills in memory and discard them after extraction by
     default."
    "Do not log consumer numbers, names, addresses, bill images, or raw OCR
     output."

All three are implemented below, and the last one is why this module logs a byte
count and a list of field *names* but never a field value and never the text.

There is no retention path. ARCHITECTURE.md 4.3 allows one "unless retention is
explicitly requested", and Phase 1 has no requester, no consent flow and no
encrypted store to put a bill in — so the bytes are function-local, and the
function returns a dict of numbers. Nothing writes them anywhere.
"""

from __future__ import annotations

import io
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, UploadFile, status

from pvmaps.api.bill_parse import parse_bill_text
from pvmaps.api.ratelimit import SlidingWindowLimiter

router = APIRouter(tags=["bill"])
log = structlog.get_logger("pvmaps.bill")

_ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

_CHUNK = 64 * 1024


def _rate_limit(limiter: SlidingWindowLimiter, client: str) -> None:
    if not limiter.check(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many bill uploads. Wait a minute, or type the values in.",
            headers={"Retry-After": "60"},
        )


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read at most `max_bytes + 1`, then refuse if it overflowed.

    Reading in chunks rather than calling `.read()`: the Content-Length header is
    not trustworthy, and a 2 GB upload should be rejected after 8 MB of memory,
    not after 2 GB of it.
    """
    buf = bytearray()
    while chunk := await upload.read(_CHUNK):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"That file is larger than {max_bytes // (1024 * 1024)} MB. "
                    "A photo of the bill taken at a lower resolution will do."
                ),
            )
    return bytes(buf)


def _extract_text(payload: bytes, content_type: str) -> str:
    """Text out of a PDF or an image, using whatever backend is installed.

    The `extract` dependency group is optional (pyproject.toml) and deliberately
    absent from `docker/api.Dockerfile`: manual bill entry always works, so
    shipping an OCR engine into the request-path image buys nothing the product
    depends on. When the backend is missing this raises 503, and the browser
    already handles that by telling the user to type the values in.
    """
    if content_type == "application/pdf":
        try:
            from pypdf import PdfReader  # optional: the `extract` group
        except ImportError:
            raise _unavailable("PDF") from None

        reader = PdfReader(io.BytesIO(payload))
        # Text layer only. A scanned PDF yields nothing here, which is correct:
        # it falls through to an empty parse and a "please type it in" warning.
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    try:
        from rapidocr_onnxruntime import RapidOCR  # optional: the `extract` group
    except ImportError:
        raise _unavailable("image") from None

    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(payload)) as img:
        frame = np.asarray(img.convert("RGB"))

    result, _elapsed = RapidOCR()(frame)
    return "\n".join(line[1] for line in (result or []))


def _unavailable(kind: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            f"{kind} reading is not enabled on this server. Type the values from "
            "your bill instead — manual entry gives exactly the same result."
        ),
    )


@router.post(
    "/bill-extract",
    summary="Copy visible fields off a bill, for the user to confirm",
    responses={
        413: {"description": "Upload larger than the configured limit"},
        415: {"description": "Unsupported file type"},
        429: {"description": "Rate limit exceeded for this client"},
        503: {"description": "No extraction backend installed on this server"},
    },
)
async def extract_bill(
    request: Request,
    file: UploadFile,
) -> dict[str, Any]:
    settings = request.app.state.settings
    _rate_limit(
        request.app.state.bill_limiter,
        request.client.host if request.client else "unknown",
    )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Upload a PDF or a photo of the bill. "
                f"Accepted types: {', '.join(sorted(_ALLOWED_TYPES))}."
            ),
        )

    payload = await _read_capped(file, settings.bill_upload_max_bytes)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That file was empty."
        )

    try:
        text = _extract_text(payload, content_type)
    finally:
        # ARCHITECTURE.md 8 and NFR-1. `payload` is function-local and nothing
        # has written it anywhere, but dropping the reference here makes the
        # lifetime of a household's bill a visible, single line of code rather
        # than an inference about scope.
        del payload
        await file.close()

    fields = parse_bill_text(text)
    patch = fields.to_form_patch()
    del text

    log.info(
        "bill_extracted",
        content_type=content_type,
        # Field NAMES, never values. "we found a sanctioned load" is operable;
        # "the sanctioned load is 3 kW" is the household's data.
        found=patch["extracted_fields"],
        warning_count=len(patch["warnings"]),
    )
    return patch
