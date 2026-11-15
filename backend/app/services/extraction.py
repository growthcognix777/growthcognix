"""Document extraction interface — implemented in Phase 2 (Client Intelligence Engine).

Phase 1 only defines the contract so later providers (pdfplumber, python-docx, OCR, Gemini vision)
plug in without changing callers. Nothing here fabricates content.
"""
from typing import Protocol

from pydantic import BaseModel


class ExtractedDocument(BaseModel):
    document_id: str
    text: str | None = None
    pages: int | None = None
    fields: dict = {}
    provider: str


class DocumentExtractor(Protocol):
    name: str

    def supports(self, file_ext: str) -> bool: ...

    def extract(self, document_id: str, path: str) -> ExtractedDocument: ...


REGISTRY: list[DocumentExtractor] = []  # populated in Phase 2
