"""Turning an uploaded policy into text, without the policy ever reaching a disk.

Every byte handled here lives in memory for the duration of one request. There
is no upload directory, no cache, no temp file on persistent storage, and no
code path that writes the original document anywhere.

The one unavoidable exception is Tesseract, which is a subprocess that reads a
file. It is pointed at a RAM-backed directory (``/dev/shm``) and the file is
unlinked immediately, so the page image never touches the filesystem that
survives a reboot. If ``/dev/shm`` is not available the OCR path refuses to run
rather than quietly falling back to ``/tmp``.

Scanned carátulas are the norm rather than the exception in Mexico, so OCR is a
first-class path here, not a fallback bolted on. It runs locally: sending the
page image to a cloud OCR would leak exactly what the redactor exists to remove.
"""

import hashlib
import io
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import (
    Iterator,
    Optional,
)

import pypdfium2
import pytesseract
from PIL import (
    Image,
    UnidentifiedImageError,
)

from app.core.config import settings
from app.core.logging import logger

# A page yielding fewer than this many characters from its text layer is treated
# as an image of a page rather than a page of text. Real carátulas are dense;
# a scan usually yields a handful of stray ligatures or nothing at all.
TEXT_LAYER_MIN_CHARS = 120

# Rendering DPI for OCR. 300 is the accepted floor for reliable small-print
# recognition; below it, deducible amounts start losing digits.
OCR_RENDER_DPI = 300

# Where Tesseract is allowed to stage a page image.
RAM_TMPDIR = "/dev/shm"


class DocumentKind(str, Enum):
    """How the text was obtained, which the UI surfaces to set expectations."""

    PDF_TEXT = "pdf_text"
    PDF_OCR = "pdf_ocr"
    PDF_MIXED = "pdf_mixed"
    IMAGE_OCR = "image_ocr"
    PLAIN_TEXT = "plain_text"


class DocumentError(ValueError):
    """Raised when an upload cannot be accepted or parsed."""


@dataclass
class ExtractedDocument:
    """The result of parsing one upload.

    Attributes:
        text: Full extracted text.
        kind: How it was obtained.
        page_count: Pages parsed.
        ocr_page_count: How many of those needed OCR.
        sha256: Digest of the original bytes, for re-upload detection.
        extension_hint: The file extension, lowercased, without a dot. The
            filename itself is deliberately discarded — filenames routinely
            carry the patient's name.
        truncated: Whether the text was cut at the configured character ceiling.
    """

    text: str
    kind: DocumentKind
    page_count: int
    ocr_page_count: int
    sha256: str
    extension_hint: str
    truncated: bool = False


# Magic bytes, checked instead of the client-supplied Content-Type. A browser
# will say whatever it is told to say; the first eight bytes of the file will
# not.
_MAGIC = (
    (b"%PDF-", "application/pdf", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
)


def _sniff(content: bytes) -> tuple[str, str]:
    """Identify a file from its leading bytes.

    Args:
        content: The uploaded bytes.

    Returns:
        tuple: ``(mime_type, extension)``.

    Raises:
        DocumentError: If the type is not recognised or not allowed.
    """
    for signature, mime, extension in _MAGIC:
        if content.startswith(signature):
            return mime, extension

    # WEBP is RIFF-framed, so its marker is not at offset 0.
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", "webp"

    # Fall back to plain text only when the bytes actually decode as UTF-8 and
    # contain no NULs — otherwise an arbitrary binary would be "text".
    try:
        sample = content[:4096].decode("utf-8")
        if "\x00" not in sample:
            return "text/plain", "txt"
    except UnicodeDecodeError:
        pass

    raise DocumentError(
        "Tipo de archivo no reconocido. Se aceptan PDF, PNG, JPG, WEBP o texto plano."
    )


def _configure_ram_tempdir() -> bool:
    """Point the whole process's temp directory at tmpfs, once, at import.

    This used to be done per request, swapping ``tempfile.tempdir`` in and out
    around each OCR call. That was a real bug rather than a style problem:
    ``tempfile.tempdir`` is process-global, extraction runs in a thread pool,
    and two concurrent uploads would interleave their set/restore. The loser of
    that race restored a path the winner had already deleted — and Python's
    ``tempfile`` silently falls back to ``/tmp`` when its configured directory
    is gone, so page images from a scanned policy would have been written to
    real disk with nothing in the logs to say so.

    Setting it once, globally, at import removes the race entirely. It is also
    the more honest configuration: *nothing* in this service should ever write
    a temporary file to persistent storage, not just the OCR path.

    Returns:
        bool: True when a RAM-backed directory is in use.
    """
    if not os.path.isdir(RAM_TMPDIR):
        logger.warning("ram_tempdir_unavailable", path=RAM_TMPDIR)
        return False

    tempfile.tempdir = RAM_TMPDIR
    logger.info("ram_tempdir_configured", path=RAM_TMPDIR)
    return True


RAM_TMPDIR_AVAILABLE = _configure_ram_tempdir()


@contextmanager
def _ocr_scratch_dir() -> Iterator[str]:
    """Provide a private scratch directory on tmpfs for one OCR call.

    No global state is touched. The directory is created under the RAM-backed
    root and removed on exit, so concurrent extractions never share a path.

    Yields:
        str: Path to a per-call directory on tmpfs.

    Raises:
        DocumentError: If no RAM-backed filesystem is available, rather than
            silently degrading to disk.
    """
    if not RAM_TMPDIR_AVAILABLE:
        raise DocumentError(
            "OCR no disponible: se requiere un directorio temporal en memoria (/dev/shm). "
            "El documento no se escribirá en disco."
        )

    directory = tempfile.mkdtemp(prefix="cc_ocr_", dir=RAM_TMPDIR)
    try:
        yield directory
    finally:
        try:
            for entry in os.scandir(directory):
                try:
                    os.unlink(entry.path)
                except OSError:
                    logger.warning("ocr_tempfile_unlink_failed")
            os.rmdir(directory)
        except OSError:
            logger.warning("ocr_tempdir_cleanup_failed")


class DocumentExtractor:
    """Parses uploads into text, in memory, with local OCR for scans."""

    def extract(self, content: bytes, declared_type: Optional[str] = None) -> ExtractedDocument:
        """Extract text from an uploaded document.

        Args:
            content: The raw uploaded bytes.
            declared_type: The client's Content-Type. Logged when it disagrees
                with the sniffed type, never trusted.

        Returns:
            ExtractedDocument: The parsed text and its provenance.

        Raises:
            DocumentError: If the upload is empty, too large, of a disallowed
                type, or yields no readable text.
        """
        if not content:
            raise DocumentError("El archivo está vacío.")

        if len(content) > settings.MAX_UPLOAD_BYTES:
            limit_mb = settings.MAX_UPLOAD_BYTES / (1024 * 1024)
            raise DocumentError(f"El archivo excede el límite de {limit_mb:.0f} MB.")

        mime, extension = _sniff(content)
        if mime not in settings.ALLOWED_UPLOAD_TYPES:
            raise DocumentError(f"Tipo de archivo no permitido: {mime}")

        if declared_type and declared_type.split(";")[0].strip() != mime:
            logger.warning("upload_type_mismatch", declared=declared_type, detected=mime)

        digest = hashlib.sha256(content).hexdigest()

        if mime == "application/pdf":
            text, kind, pages, ocr_pages = self._extract_pdf(content)
        elif mime == "text/plain":
            text = content.decode("utf-8", errors="replace")
            kind, pages, ocr_pages = DocumentKind.PLAIN_TEXT, 1, 0
        else:
            text = self._ocr_image(content)
            kind, pages, ocr_pages = DocumentKind.IMAGE_OCR, 1, 1

        text = self._normalise_whitespace(text)

        if not text.strip():
            raise DocumentError(
                "No se pudo extraer texto del documento. "
                "Si es un escaneo, verifique que la imagen sea legible."
            )

        truncated = len(text) > settings.MAX_EXTRACTED_CHARS
        if truncated:
            text = text[: settings.MAX_EXTRACTED_CHARS]
            logger.warning("extracted_text_truncated", limit=settings.MAX_EXTRACTED_CHARS)

        logger.info(
            "document_extracted",
            kind=kind.value,
            pages=pages,
            ocr_pages=ocr_pages,
            chars=len(text),
            truncated=truncated,
        )

        return ExtractedDocument(
            text=text,
            kind=kind,
            page_count=pages,
            ocr_page_count=ocr_pages,
            sha256=digest,
            extension_hint=extension,
            truncated=truncated,
        )

    # ------------------------------------------------------------------
    # PDF
    # ------------------------------------------------------------------

    def _extract_pdf(self, content: bytes) -> tuple[str, DocumentKind, int, int]:
        """Extract a PDF's text, OCRing any page that has no text layer.

        Args:
            content: The PDF bytes.

        Returns:
            tuple: ``(text, kind, page_count, ocr_page_count)``.

        Raises:
            DocumentError: If the PDF is encrypted, malformed, or over the page
                limit.
        """
        try:
            document = pypdfium2.PdfDocument(io.BytesIO(content))
        except Exception as exc:
            # A password-protected or corrupt file lands here. The message stays
            # generic: parser internals are not useful to the operator and are
            # useful to an attacker probing the parser.
            logger.warning("pdf_open_failed", reason=type(exc).__name__)
            raise DocumentError(
                "No se pudo abrir el PDF. Puede estar dañado o protegido con contraseña."
            ) from exc

        try:
            page_count = len(document)
            if page_count > settings.MAX_PDF_PAGES:
                raise DocumentError(
                    f"El PDF tiene {page_count} páginas; el límite es {settings.MAX_PDF_PAGES}."
                )

            pages: list[str] = []
            ocr_pages = 0
            needs_ocr: list[int] = []

            # First pass: the text layer, which is free.
            for index in range(page_count):
                page = document[index]
                try:
                    text_page = page.get_textpage()
                    page_text = text_page.get_text_bounded()
                    text_page.close()
                except Exception:
                    logger.warning("pdf_textlayer_failed", page=index)
                    page_text = ""
                finally:
                    page.close()

                pages.append(page_text)
                if len(page_text.strip()) < TEXT_LAYER_MIN_CHARS:
                    needs_ocr.append(index)

            # Second pass: rasterise and OCR only the pages that came back empty.
            if needs_ocr:
                with _ocr_scratch_dir():
                    for index in needs_ocr:
                        recognised = self._ocr_pdf_page(document, index)
                        if len(recognised.strip()) > len(pages[index].strip()):
                            pages[index] = recognised
                            ocr_pages += 1

            if ocr_pages == 0:
                kind = DocumentKind.PDF_TEXT
            elif ocr_pages == page_count:
                kind = DocumentKind.PDF_OCR
            else:
                kind = DocumentKind.PDF_MIXED

            joined = "\n\n".join(
                f"--- Página {index + 1} ---\n{page_text}" for index, page_text in enumerate(pages)
            )
            return joined, kind, page_count, ocr_pages
        finally:
            document.close()

    def _ocr_pdf_page(self, document, index: int) -> str:
        """Render one PDF page and run OCR on it.

        Args:
            document: An open ``pypdfium2.PdfDocument``.
            index: Zero-based page index.

        Returns:
            str: Recognised text, or empty on failure — one unreadable page
            should not fail the whole upload.
        """
        try:
            page = document[index]
            try:
                # pypdfium2 renders at a scale factor relative to 72 dpi.
                bitmap = page.render(scale=OCR_RENDER_DPI / 72)
                image = bitmap.to_pil()
            finally:
                page.close()

            return self._run_tesseract(image)
        except Exception as exc:
            logger.warning("pdf_page_ocr_failed", page=index, reason=type(exc).__name__)
            return ""

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def _ocr_image(self, content: bytes) -> str:
        """OCR a standalone image upload.

        Args:
            content: The image bytes.

        Returns:
            str: Recognised text.

        Raises:
            DocumentError: If the image cannot be decoded.
        """
        try:
            image = Image.open(io.BytesIO(content))
            image.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise DocumentError("No se pudo leer la imagen.") from exc

        with _ocr_scratch_dir():
            return self._run_tesseract(image)

    @staticmethod
    def _run_tesseract(image) -> str:
        """Run Tesseract over a PIL image using the Spanish model.

        Args:
            image: A PIL ``Image``.

        Returns:
            str: Recognised text, empty on failure.
        """
        try:
            # `spa+eng`: Mexican policies are Spanish, but insurer names, plan
            # tiers and international-coverage clauses routinely appear in
            # English, and a Spanish-only model mangles them.
            # PSM 3 is full automatic page segmentation, right for a form-heavy
            # carátula with multiple columns.
            return pytesseract.image_to_string(image, lang="spa+eng", config="--oem 1 --psm 3")
        except Exception as exc:
            logger.warning("tesseract_failed", reason=type(exc).__name__)
            return ""

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_whitespace(text: str) -> str:
        """Tidy extracted text without destroying its layout.

        OCR output is full of runs of spaces that carried column structure and
        stray blank lines that carried nothing. Collapsing every run would merge
        adjacent table cells into one string; collapsing none leaves the prompt
        padded with thousands of useless space characters. This keeps line
        structure and caps run length.

        Args:
            text: Raw extracted text.

        Returns:
            str: Cleaned text.
        """
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\x00", "")
        # Soft hyphens and zero-width characters survive OCR and break the
        # redactor's regexes by splitting a CURP in half.
        text = re.sub(r"[­​‌‍﻿]", "", text)
        text = re.sub(r"[ \t]{3,}", "   ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


document_extractor = DocumentExtractor()
