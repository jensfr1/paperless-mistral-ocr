"""Mistral OCR parser plugin for Paperless-ngx.

Registers through the ``paperless_ngx.parsers`` entrypoint group and
subclasses the built-in RemoteDocumentParser to inherit its lifecycle,
thumbnail generation and metadata extraction. Only the identity,
``score()`` and ``parse()`` are overridden.

The Mistral logic originates from PR paperless-ngx#13085.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from paperless.parsers.remote import _SUPPORTED_MIME_TYPES
from paperless.parsers.remote import RemoteDocumentParser
from paperless.parsers.utils import extract_pdf_text
from paperless.parsers.utils import post_process_text

from paperless_mistral_ocr.config import MistralConfig
from paperless_mistral_ocr.helpers import MISTRAL_OCR_TIMEOUT
from paperless_mistral_ocr.helpers import RENDER_DPI
from paperless_mistral_ocr.helpers import _build_ocr_page
from paperless_mistral_ocr.helpers import _data_uri
from paperless_mistral_ocr.helpers import _load_page_images
from paperless_mistral_ocr.helpers import _mistral_pages_to_text
from paperless_mistral_ocr.helpers import strip_image_placeholders

if TYPE_CHECKING:
    from paperless.parsers import ParserContext  # noqa: F401

logger = logging.getLogger("paperless.parsing.mistral")

__version__ = "0.3.0"

#: Confidence threshold for ocrmypdf's page rotation during preprocessing.
#: The ocrmypdf default of 12 is conservative and leaves many sideways
#: scans untouched; 6 catches noticeably more without flipping upright
#: pages in practice.
ROTATE_THRESHOLD: float = 6.0


class MistralOcrParser(RemoteDocumentParser):
    """Sends documents to the Mistral OCR API.

    Mistral returns markdown plus bounding boxes, but no PDF. The
    searchable archive is therefore assembled locally: each page is
    rasterised and overlaid with an invisible text layer positioned from
    the bounding boxes.
    """

    name: str = "Mistral OCR Parser"
    version: str = __version__
    author: str = "Jens Franke"
    url: str = "https://github.com/jensfr1/paperless-mistral-ocr"

    uses_remote_service: bool = True

    # ------------------------------------------------------------------
    # Registry interface
    # ------------------------------------------------------------------

    @classmethod
    def supported_mime_types(cls) -> dict[str, str]:
        """PDF and the usual image formats, same as the core remote parser."""
        return _SUPPORTED_MIME_TYPES

    @classmethod
    def score(
        cls,
        mime_type: str,
        filename: str,
        path: Path | None = None,
    ) -> int | None:
        """Priority for this file, or None when the plugin is not ready.

        Without an API key the parser declines and Paperless keeps using
        Tesseract. The default of 30 sits above the built-in remote parser
        (20) and Tesseract (10).
        """
        config = MistralConfig.from_env()
        if not config.is_valid():
            return None
        if mime_type not in _SUPPORTED_MIME_TYPES:
            return None
        return config.score

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def parse(
        self,
        document_path: Path,
        mime_type: str,
        *,
        produce_archive: bool = True,
    ) -> None:
        """Send the document to Mistral and store the results."""
        config = MistralConfig.from_env()

        if not config.is_valid():
            logger.warning(
                "Mistral OCR is not configured (PAPERLESS_MISTRAL_OCR_API_KEY "
                "missing), content will be empty.",
            )
            self._text = ""
            return

        # Born-digital PDFs that need no archive are not uploaded at all:
        # saves money and avoids a second text layer.
        if not produce_archive and mime_type == "application/pdf":
            logger.debug(
                "Mistral OCR skipped - no archive requested, "
                "using locally extracted text.",
            )
            self._text = (
                post_process_text(extract_pdf_text(document_path, log=logger)) or ""
            )
            return

        source = document_path
        if config.preprocess:
            source = self._preprocess(document_path, mime_type) or document_path

        text = self._mistral_ocr_parse(source, mime_type, config)

        if text is None and config.fallback:
            logger.warning("Falling back to Tesseract after Mistral failure.")
            text = self._tesseract_fallback(document_path, mime_type, produce_archive)

        self._text = text or ""

    def _preprocess(self, source: Path, mime_type: str) -> Path | None:
        """Deskew and rotate the pages before sending them to Mistral.

        Mistral reads rotated pages correctly either way, but the archive
        PDF would keep the original skew - pages then look sideways when
        browsing them in Paperless. Running ocrmypdf first fixes the
        geometry. ``tesseract_timeout=0`` keeps it from adding its own OCR
        text layer: only the page images are corrected, the text comes
        from Mistral.

        Returns the preprocessed file, or None to continue with the
        original when preprocessing is not applicable or fails.
        """
        if mime_type != "application/pdf":
            return None

        import ocrmypdf

        target = self._tempdir / "preprocessed.pdf"
        try:
            ocrmypdf.ocr(
                source,
                target,
                deskew=True,
                rotate_pages=True,
                rotate_pages_threshold=ROTATE_THRESHOLD,
                tesseract_timeout=0,
                progress_bar=False,
                output_type="pdf",
            )
        except Exception as e:
            logger.warning(
                "Preprocessing failed (%s), continuing with the original file.",
                type(e).__name__,
            )
            return None
        return target

    def _tesseract_fallback(
        self,
        document_path: Path,
        mime_type: str,
        produce_archive: bool,
    ) -> str:
        """Run the built-in Tesseract parser after a Mistral failure.

        Without this the document would be stored with empty content: the
        registry picks a parser before processing and does not retry with
        a different engine. The archive is copied into our own temporary
        directory because the Tesseract parser cleans up its own on exit.
        """
        import shutil

        from paperless.parsers.tesseract import RasterisedDocumentParser

        try:
            with RasterisedDocumentParser(self._logging_group) as parser:
                parser.parse(document_path, mime_type, produce_archive=produce_archive)
                archive = parser.get_archive_path()
                if archive and archive.exists():
                    target = self._tempdir / "archive_fallback.pdf"
                    shutil.copy2(archive, target)
                    self._archive_path = target
                return parser.get_text() or ""
        except Exception as e:
            logger.exception("Tesseract fallback failed as well: %s", e)
            return ""

    def _mistral_ocr_parse(
        self,
        file: Path,
        mime_type: str,
        config: MistralConfig,
    ) -> str | None:
        """Send the file to the Mistral OCR API and return the text.

        Also builds the searchable archive at ``self._archive_path``.
        Returns None when the call fails; the error is logged and the
        archive path is cleared.
        """
        import httpx

        endpoint = config.endpoint.rstrip("/")
        url = f"{endpoint}/v1/ocr"

        document_uri = _data_uri(mime_type, file.read_bytes())
        if mime_type == "application/pdf":
            document = {"type": "document_url", "document_url": document_uri}
        else:
            document = {"type": "image_url", "image_url": document_uri}

        payload = {
            "model": config.model,
            "document": document,
            "include_blocks": True,
        }
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=MISTRAL_OCR_TIMEOUT,
            )
            response.raise_for_status()
            pages = response.json().get("pages", [])

            self._archive_path = self._tempdir / "archive.pdf"
            self._build_searchable_pdf(file, mime_type, pages, self._archive_path)

            return strip_image_placeholders(_mistral_pages_to_text(pages))

        except Exception as e:
            logger.exception("Mistral OCR failed: %s", e)
            self._archive_path = None

        return None

    def _build_searchable_pdf(
        self,
        source: Path,
        mime_type: str,
        pages: list[dict],
        out_path: Path,
    ) -> None:
        """Assemble a searchable PDF from the original and the OCR result.

        Each page is rasterised and overlaid with an invisible text layer
        positioned from Mistral's bounding boxes, rendered with ocrmypdf's
        fpdf2 renderer and its bundled Unicode font. Note that ocrmypdf is
        used purely as a renderer here, no OCR engine is involved.
        """
        import ocrmypdf
        import pikepdf
        from ocrmypdf.font import MultiFontManager
        from ocrmypdf.fpdf_renderer import Fpdf2PdfRenderer

        images = _load_page_images(source, mime_type, RENDER_DPI)
        font_dir = Path(ocrmypdf.__file__).parent / "data"
        font_manager = MultiFontManager(font_dir)

        merged = pikepdf.Pdf.new()
        opened: list = []
        try:
            for index, image in enumerate(images):
                page_data = pages[index] if index < len(pages) else {}

                image_path = self._tempdir / f"page-{index}.png"
                image.save(image_path)

                ocr_page = _build_ocr_page(
                    page_data,
                    image.width,
                    image.height,
                    RENDER_DPI,
                )

                page_pdf_path = self._tempdir / f"page-{index}.pdf"
                Fpdf2PdfRenderer(
                    page=ocr_page,
                    dpi=RENDER_DPI,
                    multi_font_manager=font_manager,
                    invisible_text=True,
                    image=image_path,
                ).render(page_pdf_path)

                page_pdf = pikepdf.open(page_pdf_path)
                opened.append(page_pdf)
                merged.pages.extend(page_pdf.pages)

            merged.save(out_path)
        finally:
            for page_pdf in opened:
                page_pdf.close()
            merged.close()
