"""Pure Mistral OCR helpers.

Originally written for src/paperless/parsers/remote.py and submitted as
PR paperless-ngx#13085. These functions are framework independent and are
reused here unchanged.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ocrmypdf.models.ocr_element import BoundingBox
    from ocrmypdf.models.ocr_element import OcrElement

logger = logging.getLogger("paperless.parsing.mistral")

#: Base URL of the hosted Mistral OCR API.
MISTRAL_DEFAULT_ENDPOINT: str = "https://api.mistral.ai"

#: Model identifier.
MISTRAL_OCR_MODEL: str = "mistral-ocr-latest"

#: Timeout (seconds) for a single OCR call. Large documents take a while.
MISTRAL_OCR_TIMEOUT: float = 600.0

#: DPI used to rasterise pages before overlaying the invisible text layer.
RENDER_DPI: int = 200


# ----------------------------------------------------------------------
# Mistral OCR helpers (pure, framework-independent)
# ----------------------------------------------------------------------


def _data_uri(mime_type: str, data: bytes) -> str:
    """Encode ``data`` as a ``data:`` URI for the given MIME type."""
    import base64

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _mistral_pages_to_text(pages: list[dict]) -> str:
    """Concatenate the markdown content of every page, blank pages dropped."""
    parts = [str(page.get("markdown", "")).strip() for page in pages]
    return "\n\n".join(part for part in parts if part)


def _block_text(block: dict) -> str:
    """Best-effort extraction of a block's text content."""
    for key in ("markdown", "text", "content"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _block_bounding_box(block: dict) -> tuple[float, float, float, float] | None:
    """Best-effort extraction of a block bbox as ``(left, top, right, bottom)``.

    Supports the bounding-box shapes Mistral has used across API revisions:
    a ``bbox`` list ``[x0, y0, x1, y1]``, a ``bbox`` dict with
    ``left/top/right/bottom``, or the image-style
    ``top_left_x/top_left_y/bottom_right_x/bottom_right_y`` keys (either nested
    under ``bbox`` or directly on the block).  Returns ``None`` when no usable
    box is present.
    """
    corner_keys = ("top_left_x", "top_left_y", "bottom_right_x", "bottom_right_y")
    edge_keys = ("left", "top", "right", "bottom")

    candidates = [block.get("bbox"), block]
    for candidate in candidates:
        if isinstance(candidate, (list, tuple)) and len(candidate) == 4:
            try:
                return tuple(float(v) for v in candidate)  # type: ignore[return-value]
            except (TypeError, ValueError):
                continue
        if isinstance(candidate, dict):
            for keys in (edge_keys, corner_keys):
                if all(k in candidate for k in keys):
                    try:
                        return tuple(float(candidate[k]) for k in keys)  # type: ignore[return-value]
                    except (TypeError, ValueError):
                        continue
    return None


def _clamp_bbox(
    left: float,
    top: float,
    right: float,
    bottom: float,
    max_width: float,
    max_height: float,
) -> BoundingBox | None:
    """Clamp a bbox to the page and return a valid ``BoundingBox`` or ``None``.

    ``BoundingBox`` rejects degenerate boxes (``right <= left`` etc.), so this
    also filters out empty or inverted boxes.
    """
    from ocrmypdf.models.ocr_element import BoundingBox

    left = max(0.0, min(left, max_width))
    right = max(0.0, min(right, max_width))
    top = max(0.0, min(top, max_height))
    bottom = max(0.0, min(bottom, max_height))
    if right <= left or bottom <= top:
        return None
    return BoundingBox(left, top, right, bottom)


def _text_band_elements(
    text: str,
    left: float,
    top: float,
    right: float,
    bottom: float,
    max_width: float,
    max_height: float,
    dpi: float,
) -> list[OcrElement]:
    """Lay ``text`` into one thin invisible ``ocr_line`` band per text line.

    A single tall box makes the fpdf2 renderer scale text so aggressively that
    the glyphs become unrecoverable, so the box is divided into one horizontal
    band per line of text and each band's height is capped to roughly a single
    line.  Returns the resulting ``ocr_line`` elements (each wrapping one
    ``ocrx_word``); an empty list when there is no usable text.
    """
    from ocrmypdf.models.ocr_element import OcrElement

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    band_cap = dpi * 0.3
    slot = (bottom - top) / len(lines)
    elements: list[OcrElement] = []
    for index, line in enumerate(lines):
        band_top = top + index * slot
        band_bottom = band_top + min(slot, band_cap)
        bbox = _clamp_bbox(left, band_top, right, band_bottom, max_width, max_height)
        if bbox is None:
            continue
        word = OcrElement(ocr_class="ocrx_word", text=line, bbox=bbox)
        elements.append(OcrElement(ocr_class="ocr_line", bbox=bbox, children=[word]))
    return elements


def _build_ocr_page(
    page_data: dict,
    image_width: int,
    image_height: int,
    dpi: float,
) -> OcrElement:
    """Build an ``OcrElement`` page tree from a Mistral OCR page result.

    Each content block's text is laid into thin invisible bands positioned at
    the block's (scaled) bounding box.  When no usable blocks are present, the
    whole page markdown is laid across the full page instead, so the archive
    stays searchable either way.
    """
    from ocrmypdf.models.ocr_element import BoundingBox
    from ocrmypdf.models.ocr_element import OcrElement

    dimensions = page_data.get("dimensions") or {}
    source_width = dimensions.get("width") or image_width
    source_height = dimensions.get("height") or image_height
    scale_x = image_width / source_width if source_width else 1.0
    scale_y = image_height / source_height if source_height else 1.0

    children: list[OcrElement] = []
    for block in page_data.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        text = _block_text(block)
        box = _block_bounding_box(block)
        if not text or box is None:
            continue
        left, top, right, bottom = box
        children.extend(
            _text_band_elements(
                text,
                left * scale_x,
                top * scale_y,
                right * scale_x,
                bottom * scale_y,
                image_width,
                image_height,
                dpi,
            ),
        )

    if not children:
        # Fallback: no positioned blocks — keep the page searchable by laying
        # the full markdown text across the whole page as invisible text.
        children.extend(
            _text_band_elements(
                str(page_data.get("markdown", "")).strip(),
                0,
                0,
                image_width,
                image_height,
                image_width,
                image_height,
                dpi,
            ),
        )

    return OcrElement(
        ocr_class="ocr_page",
        bbox=BoundingBox(0, 0, image_width, image_height),
        dpi=dpi,
        page_number=page_data.get("index", 0),
        children=children,
    )


def _load_page_images(source: Path, mime_type: str, dpi: int) -> list:
    """Return one RGB ``PIL.Image`` per page of the source document.

    PDF input is rasterised with pdf2image; image input (including multi-frame
    TIFF) is loaded directly, one entry per frame.
    """
    from PIL import Image
    from PIL import ImageSequence

    if mime_type == "application/pdf":
        from pdf2image import convert_from_path

        return convert_from_path(source, dpi=dpi)

    with Image.open(source) as opened:
        return [frame.convert("RGB") for frame in ImageSequence.Iterator(opened)]


#: Mistral returns markdown and references page images as
#: ``![img-0.jpeg](img-0.jpeg)``. In the extracted text this is pure noise:
#: it pollutes full-text search and shows up as "jpeg" in every document.
_IMAGE_PLACEHOLDER = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def strip_image_placeholders(text: str) -> str:
    """Remove markdown image references and tidy up the whitespace."""
    cleaned = _IMAGE_PLACEHOLDER.sub("", text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()
