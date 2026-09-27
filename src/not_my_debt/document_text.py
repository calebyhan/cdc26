"""Turn uploaded bills into line-oriented text, entirely on this machine.

PyMuPDF rebuilds each visual line from word positions, so a table row such as
"Balance due        $150.00" stays on one line even when the label and amount
are separate text objects. Pages without a text layer (scans) and photos of
bills are read with RapidOCR, a free local OCR model; nothing leaves the server.
pypdf remains a fallback for PDFs PyMuPDF cannot open.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 12
MIN_PAGE_CHARS = 20
OCR_DPI = 200
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
_ocr_engine = None


@dataclass
class DocumentText:
    text: str
    notes: list[str] = field(default_factory=list)


def _ocr():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ValueError("Scanned documents need OCR. Run uv sync, or paste the text.") from exc
        _ocr_engine = RapidOCR()
    return _ocr_engine


def lines_from_boxes(boxes: list[tuple[float, float, float, float, str]]) -> str:
    """Group positioned text chunks into visual lines; wide gaps become two spaces.

    ``boxes`` are (x0, y0, x1, y1, text). Chunks whose vertical centers are within
    half a line height join the same line, ordered left to right.
    """
    items = sorted(
        ((x0, y0, x1, y1, t.strip()) for x0, y0, x1, y1, t in boxes if t and t.strip()),
        key=lambda b: ((b[1] + b[3]) / 2, b[0]),
    )
    lines: list[list[tuple]] = []
    for item in items:
        center, height = (item[1] + item[3]) / 2, max(item[3] - item[1], 1)
        if lines:
            last = lines[-1]
            last_center = sum((b[1] + b[3]) / 2 for b in last) / len(last)
            if abs(center - last_center) <= height * 0.5:
                last.append(item)
                continue
        lines.append([item])
    out = []
    for line in lines:
        line.sort(key=lambda b: b[0])
        text = line[0][4]
        for prev, cur in zip(line, line[1:]):
            char_width = (prev[2] - prev[0]) / max(len(prev[4]), 1)
            gap = cur[0] - prev[2]
            text += ("  " if gap > max(3 * char_width, 8) else " ") + cur[4]
        out.append(text)
    return "\n".join(out)


def _ocr_image(png_bytes: bytes) -> str:
    result, _ = _ocr()(png_bytes, return_word_box=True)
    boxes = []
    for points, text, *_ in result or []:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        boxes.append((min(xs), min(ys), max(xs), max(ys), text))
    return lines_from_boxes(boxes)


def _read_pdf(content: bytes) -> DocumentText:
    import pymupdf

    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ValueError("This PDF could not be read. Paste its text instead.") from exc
    with doc:
        if doc.needs_pass:
            raise ValueError("Please provide an unlocked PDF.")
        if doc.page_count > MAX_PAGES:
            raise ValueError(f"Please upload at most {MAX_PAGES} pages for one document.")
        pages, ocr_pages = [], []
        for number, page in enumerate(doc, 1):
            words = page.get_text("words")
            text = lines_from_boxes([(w[0], w[1], w[2], w[3], w[4]) for w in words])
            if len(text.strip()) < MIN_PAGE_CHARS:
                pixmap = page.get_pixmap(dpi=OCR_DPI)
                text = _ocr_image(pixmap.tobytes("png"))
                ocr_pages.append(number)
            pages.append(text)
    notes = []
    if ocr_pages:
        notes.append(
            f"Read page {', '.join(map(str, ocr_pages))} with OCR. "
            "Check every value against the original document."
        )
    return DocumentText("\f".join(pages), notes)


def _read_pdf_fallback(content: bytes) -> DocumentText:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        raise ValueError("Please provide an unlocked PDF.")
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f"Please upload at most {MAX_PAGES} pages for one document.")
    return DocumentText("\f".join(page.extract_text() or "" for page in reader.pages))


def read_document(content: bytes, filename: str) -> DocumentText:
    """Extract text from a PDF, photo, or text file held in memory."""
    if len(content) > MAX_BYTES:
        raise ValueError("Please use a document smaller than 10 MB.")
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            result = _read_pdf(content)
        except ValueError:
            raise
        except Exception:
            try:
                result = _read_pdf_fallback(content)
            except ValueError:
                raise
            except Exception as exc:
                raise ValueError("This PDF could not be read. Paste its text instead.") from exc
    elif name.endswith(IMAGE_TYPES):
        try:
            text = _ocr_image(content)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("This image could not be read. Try a clearer photo or a PDF.") from exc
        result = DocumentText(text, ["Read this photo with OCR. Check every value against it."])
    elif name.endswith((".txt", ".md")):
        try:
            result = DocumentText(content.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise ValueError("Please use UTF-8 text or a text PDF.") from exc
    else:
        raise ValueError("Use a PDF, a photo (PNG or JPG), or a .txt document.")
    if not result.text.strip():
        raise ValueError("No readable text was found. Try a clearer scan or paste the text.")
    if len(result.text) > 60_000:
        raise ValueError("Document text exceeds 60,000 characters. Split it into smaller documents.")
    return result
