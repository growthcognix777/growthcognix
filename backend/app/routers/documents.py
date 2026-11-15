import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.deps import Ctx, get_ctx, require_role
from app.models import Client, Document, Product
from app.schemas import DocumentOut, Page
from app.services.activity import log
from app.services.tenancy import get_owned, scoped

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

ALLOWED = {
    "pdf": ("application/pdf", b"%PDF"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04"),
    "jpg": ("image/jpeg", b"\xff\xd8\xff"),
    "jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    "png": ("image/png", b"\x89PNG"),
}


def _root() -> Path:
    p = Path(get_settings().upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.get("", response_model=Page[DocumentOut])
def list_documents(ctx: Ctx = Depends(get_ctx), client_id: str | None = None, product_id: str | None = None):
    stmt = scoped(ctx, Document)
    if client_id:
        stmt = stmt.where(Document.client_id == client_id)
    if product_id:
        stmt = stmt.where(Document.product_id == product_id)
    rows = ctx.db.scalars(stmt.order_by(Document.created_at.desc())).all()
    return Page[DocumentOut](items=rows, total=len(rows))


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    product_id: str | None = Form(default=None),
    ctx: Ctx = Depends(get_ctx),
):
    client = get_owned(ctx, Client, client_id, "Client")
    if product_id:
        product = get_owned(ctx, Product, product_id, "Product")
        if product.client_id != client.id:
            raise HTTPException(400, "Product does not belong to this client")
    name = os.path.basename(file.filename or "upload")[:255]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED:
        raise HTTPException(415, "Only PDF, DOCX, JPG and PNG files are allowed")
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"File is larger than {get_settings().max_upload_mb} MB")
    if not data:
        raise HTTPException(400, "File is empty")
    mime, magic = ALLOWED[ext]
    if not data.startswith(magic):
        raise HTTPException(415, "File content does not match its extension")
    key = f"{ctx.tenant_id}/{client.id}/{uuid.uuid4().hex}.{ext}"
    dest = _root() / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    doc = Document(tenant_id=ctx.tenant_id, client_id=client.id, product_id=product_id, original_name=name,
                   content_type=mime, file_ext=ext, size_bytes=len(data), storage_key=key, uploaded_by=ctx.user.id)
    ctx.db.add(doc)
    ctx.db.flush()
    log(ctx, "document.uploaded", "document", doc.id, f"{name} uploaded to {client.company_name}", client_id=client.id)
    ctx.db.commit()
    return doc


@router.get("/{document_id}/download")
def download_document(document_id: str, ctx: Ctx = Depends(get_ctx)):
    """Streams the file after a tenant check. The storage path is never sent to the browser."""
    doc = get_owned(ctx, Document, document_id, "Document")
    path = _root() / doc.storage_key
    if not path.is_file():
        raise HTTPException(410, "The stored file is missing")
    return FileResponse(path, media_type=doc.content_type, filename=doc.original_name)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str, ctx: Ctx = Depends(require_role("manager"))):
    doc = get_owned(ctx, Document, document_id, "Document")
    path = _root() / doc.storage_key
    if path.is_file():
        path.unlink()
    log(ctx, "document.deleted", "document", doc.id, f"{doc.original_name} deleted", client_id=doc.client_id)
    ctx.db.delete(doc)
    ctx.db.commit()
