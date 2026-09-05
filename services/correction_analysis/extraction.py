from typing import *

from .client import CorrectionAnalysisError, get_client
from .models import ExtractionResult
from .prompts import EXTRACTION_PROMPT

EXTRACTION_MODEL = "gpt-5-mini"

# The slips are large, clean text rather than hard OCR, but `2+` -> Over 1.5 and the
# bet-type vocabulary mapping are reasoning-shaped enough to warrant mini over nano.

_MAGIC_PREFIXES = {
    "iVBORw0KGgo": "image/png",
    "/9j/": "image/jpeg",
    "R0lGOD": "image/gif",
    "UklGR": "image/webp",
}


def _data_url(image: str) -> str:
    payload = image.strip()
    if payload.startswith("data:"):
        return payload
    for prefix, mime in _MAGIC_PREFIXES.items():
        if payload.startswith(prefix):
            return f"data:{mime};base64,{payload}"
    return f"data:image/jpeg;base64,{payload}"


async def extract_legs(images: list[str]) -> ExtractionResult:
    """Read every bet leg out of one or more screenshots of the same parlay slip.

    All images go into a single call so the model can reconcile overlap between
    scrolled screenshots itself rather than us deduping blind.
    """
    response = await get_client().responses.parse(
        model=EXTRACTION_MODEL,
        reasoning={"effort": "low"},
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": EXTRACTION_PROMPT},
                    *[
                        {
                            "type": "input_image",
                            "image_url": _data_url(image),
                            "detail": "high",
                        }
                        for image in images
                    ],
                ],
            }
        ],
        text_format=ExtractionResult,
    )

    if response.output_parsed is None:
        raise CorrectionAnalysisError("Could not read any bet lines from those screenshots.")

    return response.output_parsed
