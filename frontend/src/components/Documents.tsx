"use client";
import { Download, FileImage, FileText, Trash2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import type { DocumentMeta, Product } from "@/lib/types";
import { MAX_UPLOAD_MB, validateFile } from "@/lib/validate";
import { Badge, Empty, Select, Table, cx } from "./ui";

interface Item { name: string; pct: number; error?: string; done?: boolean }

export function Uploader({ clientId, products, onUploaded }: { clientId: string | null; products?: Product[]; onUploaded: (d: DocumentMeta) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false); const [productId, setProductId] = useState(""); const [items, setItems] = useState<Item[]>([]);
  const upd = (i: number, p: Partial<Item>) => setItems((s) => s.map((x, j) => (j === i ? { ...x, ...p } : x)));

  const handle = async (files: FileList | null) => {
    if (!files || !clientId) return;
    const list = Array.from(files); const start = items.length;
    setItems((s) => [...s, ...list.map((f) => ({ name: f.name, pct: 0 }))]);
    await Promise.all(list.map(async (f, k) => {
      const i = start + k; const err = validateFile(f);
      if (err) return upd(i, { error: err });
      try { const d = await api.uploadDocument(f, clientId, productId || null, (pct) => upd(i, { pct })); upd(i, { pct: 100, done: true }); onUploaded(d); }
      catch (e) { upd(i, { error: e instanceof Error ? e.message : "Upload failed" }); }
    }));
  };

  return (
    <div className="space-y-3 p-5">
      {products && products.length > 0 && (
        <div className="flex items-center gap-2 text-sm"><span className="text-navy-500">Link to</span>
          <Select className="h-9 max-w-xs" value={productId} onChange={(e) => setProductId(e.target.value)}><option value="">Client (no specific product)</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></div>
      )}
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); handle(e.dataTransfer.files); }}
        onClick={() => clientId && input.current?.click()}
        className={cx("flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition", drag ? "border-brand-500 bg-brand-50" : "border-line hover:border-brand-200 hover:bg-canvas", !clientId && "pointer-events-none opacity-50")}>
        <UploadCloud className="h-6 w-6 text-brand-600" />
        <div className="mt-2 text-sm font-medium text-navy-950">{clientId ? "Drop files or click to upload" : "Choose a client first"}</div>
        <div className="text-xs text-navy-500">PDF, DOCX, JPG or PNG · up to {MAX_UPLOAD_MB} MB each</div>
        <input ref={input} type="file" multiple accept=".pdf,.docx,.jpg,.jpeg,.png" className="hidden" onChange={(e) => { handle(e.target.files); e.target.value = ""; }} />
      </div>
      {items.map((it, i) => (
        <div key={i} className="rounded-lg border border-line px-3 py-2 text-sm">
          <div className="flex justify-between"><span className="truncate text-navy-900">{it.name}</span>
            <span className={cx("text-xs", it.error ? "text-red-600" : it.done ? "text-emerald-600" : "text-navy-500")}>{it.error || (it.done ? "Uploaded" : `${it.pct}%`)}</span></div>
          {!it.error && !it.done && <div className="mt-1.5 h-1 overflow-hidden rounded bg-canvas"><div className="h-full bg-brand-500 transition-all" style={{ width: `${it.pct}%` }} /></div>}
        </div>
      ))}
    </div>
  );
}

export function DocumentTable({ items, names, onDeleted }: { items: DocumentMeta[]; names?: Record<string, string>; onDeleted: (id: string) => void }) {
  const { session } = useAuth();
  const canDelete = session && ["owner", "admin", "manager"].includes(session.user.role);
  const download = async (d: DocumentMeta) => {
    try { const b = await api.downloadDocument(d.id); const url = URL.createObjectURL(b); const a = document.createElement("a"); a.href = url; a.download = d.original_name; a.click(); URL.revokeObjectURL(url); }
    catch (e) { alert(e instanceof Error ? e.message : "Download failed"); }
  };
  const del = async (d: DocumentMeta) => { if (!confirm(`Delete ${d.original_name}?`)) return; try { await api.deleteDocument(d.id); onDeleted(d.id); } catch (e) { alert(e instanceof Error ? e.message : "Delete failed"); } };
  if (!items.length) return <Empty title="No documents yet" body="Upload catalogues, spec sheets, certificates and product photos." icon={<FileText className="h-5 w-5" />} />;
  return (
    <Table head={["Document", "Type", "Linked to", "Size", "Uploaded", "Extraction", ""]}>
      {items.map((d) => (
        <tr key={d.id} className="hover:bg-canvas">
          <td className="px-5 py-3"><div className="flex items-center gap-2">{["jpg", "jpeg", "png"].includes(d.file_ext) ? <FileImage className="h-4 w-4 text-violet-500" /> : <FileText className="h-4 w-4 text-brand-600" />}
            <span className="max-w-[240px] truncate font-medium text-navy-950">{d.original_name}</span></div></td>
          <td className="px-5 py-3 uppercase text-navy-700">{d.file_ext}</td>
          <td className="px-5 py-3 text-navy-700">{names?.[d.product_id || ""] || names?.[d.client_id] || "Client"}</td>
          <td className="px-5 py-3 text-navy-700">{fmtBytes(d.size_bytes)}</td>
          <td className="whitespace-nowrap px-5 py-3 text-navy-500">{fmtDateTime(d.created_at)}</td>
          <td className="px-5 py-3"><Badge>Phase 2</Badge></td>
          <td className="px-5 py-3"><div className="flex justify-end gap-1">
            <button onClick={() => download(d)} className="rounded p-1.5 text-navy-500 hover:bg-canvas" aria-label="Download"><Download className="h-4 w-4" /></button>
            {canDelete && <button onClick={() => del(d)} className="rounded p-1.5 text-navy-500 hover:bg-red-50 hover:text-red-600" aria-label="Delete"><Trash2 className="h-4 w-4" /></button>}
          </div></td>
        </tr>))}
    </Table>
  );
}
