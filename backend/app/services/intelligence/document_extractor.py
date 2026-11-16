"""Stage: pull text out of a client's uploaded PDF, DOCX and image documents.

PDF → pypdf, DOCX → python-docx (paragraphs + tables), JPG/PNG → Gemini vision transcription when a
Gemini key is configured, otherwise the document is marked `unsupported` (never guessed).
Scanned PDFs with no text layer come back empty and are marked `no_text`.
"""
from __future__ import annotations

import io
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.models import Document, DocumentExtraction
from app.services.ai.providers import ProviderError, get_vision
from app.services.extraction import REGISTRY, ExtractedDocument
from app.services.intelligence.common import Context

MAX_CHARS = 200_000


class PdfExtractor:
    name = "pypdf"

    def supports(self, file_ext: str) -> bool:
        return file_ext == "pdf"

    def extract(self, document_id: str, path: str) -> ExtractedDocument:
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
        return ExtractedDocument(document_id=document_id, text=text.strip()[:MAX_CHARS], pages=len(reader.pages),
                                 provider=self.name)


class DocxExtractor:
    name = "python-docx"

    def supports(self, file_ext: str) -> bool:
        return file_ext == "docx"

    def extract(self, document_id: str, path: str) -> ExtractedDocument:
        import docx
        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs if p.text.strip()]
        for table in d.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        return ExtractedDocument(document_id=document_id, text="\n".join(parts)[:MAX_CHARS], provider=self.name)


class ImageExtractor:
    name = "gemini-vision"

    def supports(self, file_ext: str) -> bool:
        return file_ext in ("jpg", "jpeg", "png")

    def extract(self, document_id: str, path: str) -> ExtractedDocument:
        vision = get_vision()
        if vision is None:
            raise NotImplementedError("Image text extraction needs GEMINI_API_KEY")
        ext = path.rsplit(".", 1)[-1].lower()
        mime = "image/png" if ext == "png" else "image/jpeg"
        text = vision.image_text(Path(path).read_bytes(), mime)
        return ExtractedDocument(document_id=document_id, text=text[:MAX_CHARS], pages=1, provider=self.name)


REGISTRY.extend([PdfExtractor(), DocxExtractor(), ImageExtractor()])


def extract_document(db, doc: Document) -> DocumentExtraction:
    path = str(Path(get_settings().upload_dir) / doc.storage_key)
    ex = db.scalar(select(DocumentExtraction).where(DocumentExtraction.document_id == doc.id))
    if ex is None:
        ex = DocumentExtraction(tenant_id=doc.tenant_id, document_id=doc.id, extractor="none")
        db.add(ex)
    extractor = next((e for e in REGISTRY if e.supports(doc.file_ext)), None)
    ex.text, ex.pages, ex.error = None, None, None
    if extractor is None:
        ex.extractor, ex.error, doc.extraction_status = "none", f"No extractor for .{doc.file_ext}", "unsupported"
        return ex
    ex.extractor = extractor.name
    try:
        out = extractor.extract(doc.id, path)
        ex.text, ex.pages = (out.text or None), out.pages
        doc.extraction_status = "completed" if out.text else "no_text"
        if not out.text:
            ex.error = "No readable text found (a scanned PDF needs OCR)" if doc.file_ext == "pdf" else "No readable text found"
    except NotImplementedError as e:
        ex.error, doc.extraction_status = str(e), "unsupported"
    except (ProviderError, OSError, ValueError, KeyError) as e:
        ex.error, doc.extraction_status = f"{type(e).__name__}: {e}"[:500], "failed"
    except Exception as e:  # malformed files from third-party parsers
        ex.error, doc.extraction_status = f"Could not read file: {type(e).__name__}"[:500], "failed"
    return ex


def run(ctx: Context) -> dict:
    docs = ctx.db.scalars(select(Document).where(Document.tenant_id == ctx.tenant_id,
                                                 Document.client_id == ctx.client.id)).all()
    force = bool(ctx.job.params.get("re_extract"))
    counts = {"extracted": 0, "skipped": 0, "no_text": 0, "unsupported": 0, "failed": 0}
    for d in docs:
        if d.extraction_status == "completed" and not force:
            counts["skipped"] += 1
            continue
        extract_document(ctx.db, d)
        key = {"completed": "extracted"}.get(d.extraction_status, d.extraction_status)
        counts[key] = counts.get(key, 0) + 1
    ctx.db.flush()
    return counts
