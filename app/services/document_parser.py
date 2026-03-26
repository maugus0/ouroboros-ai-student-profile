"""Document text extraction from PDF, DOCX, and image files."""

import base64
import binascii
import hashlib
import os
import tempfile
import time
from typing import Optional

from app.config import settings
from app.core.logging import get_logger
from app.utils.exceptions import DocumentParsingError
from app.utils.file_utils import get_file_extension

logger = get_logger(__name__)


class DocumentParser:
    """Extracts raw text from uploaded documents."""

    async def extract_text(self, file_content_base64: str, file_name: str) -> dict:
        """Decode base64 content, detect file type, and extract text.

        Returns a dict with keys: text, extraction_method, ocr_used,
        extracted_text_length, extraction_time_ms, file_hash.
        """
        start = time.perf_counter()

        try:
            raw_bytes = base64.b64decode(file_content_base64)
        except (binascii.Error, ValueError) as exc:
            raise DocumentParsingError(f"Invalid base64 content: {exc}") from exc

        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        ext = get_file_extension(file_name)

        tmp_path: Optional[str] = None
        try:
            tmp_path = self._write_temp(raw_bytes, ext)

            if ext == ".pdf":
                text, method, ocr_used = self._extract_pdf(tmp_path)
            elif ext in (".docx", ".doc"):
                text, method, ocr_used = self._extract_docx(tmp_path)
            elif ext in (".jpg", ".jpeg", ".png"):
                text, method, ocr_used = self._extract_image(tmp_path)
            else:
                raise DocumentParsingError(f"Unsupported file extension: {ext}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return {
            "text": text,
            "extraction_method": method,
            "ocr_used": ocr_used,
            "extracted_text_length": len(text),
            "extraction_time_ms": elapsed_ms,
            "file_hash": file_hash,
            "file_size_bytes": len(raw_bytes),
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _write_temp(raw_bytes: bytes, ext: str) -> str:
        os.makedirs(settings.TEMP_UPLOAD_DIR, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=ext, dir=settings.TEMP_UPLOAD_DIR)
        os.write(fd, raw_bytes)
        os.close(fd)
        return path

    @staticmethod
    def _extract_pdf(path: str) -> tuple[str, str, bool]:
        import pdfplumber  # pylint: disable=import-outside-toplevel

        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)

        text = "\n".join(pages)

        if not text.strip():
            text, ocr_used = DocumentParser._ocr_fallback(path)
            return text, "ocr", ocr_used

        return text, "digital_pdf", False

    @staticmethod
    def _extract_docx(path: str) -> tuple[str, str, bool]:
        from docx import Document  # pylint: disable=import-outside-toplevel

        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs), "docx", False

    @staticmethod
    def _extract_image(path: str) -> tuple[str, str, bool]:
        text, ocr_used = DocumentParser._ocr_fallback(path)
        return text, "ocr", ocr_used

    @staticmethod
    def _ocr_fallback(path: str) -> tuple[str, bool]:
        try:
            import pytesseract  # pylint: disable=import-outside-toplevel
            from PIL import Image  # pylint: disable=import-outside-toplevel

            if settings.TESSERACT_PATH:
                pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_PATH

            img = Image.open(path)
            text = pytesseract.image_to_string(img, lang=settings.OCR_LANGUAGE)
            return text.strip(), True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("ocr_fallback_failed", error=str(exc))
            return "", False
