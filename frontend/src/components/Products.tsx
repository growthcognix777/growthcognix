"use client";
import { Package, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ApiError, type Client, type FieldError, type Product, type ProductInput } from "@/lib/types";
import { validateProduct } from "@/lib/validate";
import { Badge, Button, Empty, ErrorBox, Field, Input, Modal, Select, TagInput, Textarea } from "./ui";

const blank = (client_id = ""): ProductInput => ({ client_id, kind: "product", name: "", category: "", description: "", specifications: "", applications: "",
  pricing: "", min_order_quantity: "", production_capacity: "", target_industries: [] });

export function ProductModal({ open, onClose, onSaved, clients, initial, clientId }: {
  open: boolean; onClose: () => void; onSaved: (p: Product) => void; clients?: Client[]; initial?: Product | null; clientId?: string;
}) {
  const [v, setV] = useState<ProductInput>(initial ? { ...initial } : blank(clientId));
  const [errs, setErrs] = useState<FieldError[]>([]); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const fe = (f: string) => errs.find((e) => e.field === f)?.message;
  const set = (k: keyof ProductInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setV({ ...v, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null);
    const body = { ...v }; (Object.keys(body) as (keyof ProductInput)[]).forEach((k) => { if (body[k] === "") (body as unknown as Record<string, unknown>)[k] = null; });
    const ve = validateProduct(body); setErrs(ve); if (ve.length) return;
    setBusy(true);
    try {
      const { client_id, ...rest } = body;
      onSaved(initial ? await api.updateProduct(initial.id, rest) : await api.createProduct({ ...rest, client_id }));
      onClose();
    } catch (e) { if (e instanceof ApiError) { setErr(e.message); setErrs(e.errors); } else setErr("Could not save"); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title={initial ? `Edit ${initial.name}` : "Add product or service"}>
      <form onSubmit={submit} noValidate className="space-y-4">
        {err && <div className="-m-5 mb-0"><ErrorBox message={err} /></div>}
        <div className="grid gap-4 md:grid-cols-2">
          {clients && !initial && <div className="md:col-span-2"><Field label="Client" required error={fe("client_id")}>
            <Select value={v.client_id} onChange={set("client_id")} invalid={!!fe("client_id")}><option value="">Select a client…</option>{clients.map((c) => <option key={c.id} value={c.id}>{c.company_name}</option>)}</Select></Field></div>}
          <Field label="Name" required error={fe("name")}><Input value={v.name} onChange={set("name")} invalid={!!fe("name")} /></Field>
          <Field label="Type"><Select value={v.kind} onChange={set("kind")}><option value="product">Product</option><option value="service">Service</option></Select></Field>
          <Field label="Category"><Input value={v.category || ""} onChange={set("category")} /></Field>
          <Field label="Pricing" hint="Only what the client has supplied"><Input value={v.pricing || ""} onChange={set("pricing")} placeholder="e.g. ₹2.4L per unit" /></Field>
          <Field label="Minimum order quantity"><Input value={v.min_order_quantity || ""} onChange={set("min_order_quantity")} /></Field>
          <Field label="Production capacity"><Input value={v.production_capacity || ""} onChange={set("production_capacity")} placeholder="e.g. 40 units / month" /></Field>
          <div className="md:col-span-2"><Field label="Description"><Textarea value={v.description || ""} onChange={set("description")} /></Field></div>
          <div className="md:col-span-2"><Field label="Specifications"><Textarea value={v.specifications || ""} onChange={set("specifications")} placeholder="Technical specs, materials, certifications supplied by the client." /></Field></div>
          <div className="md:col-span-2"><Field label="Applications"><Textarea className="min-h-[64px]" value={v.applications || ""} onChange={set("applications")} /></Field></div>
          <div className="md:col-span-2"><Field label="Target industries" hint="Press Enter after each"><TagInput value={v.target_industries} onChange={(t) => setV({ ...v, target_industries: t })} /></Field></div>
        </div>
        <p className="text-xs text-navy-500">Product images and spec sheets are uploaded under Documents and linked to this item.</p>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy}>{initial ? "Save" : "Add"}</Button></div>
      </form>
    </Modal>
  );
}

export function ProductCards({ items, clientsById, onEdit, onDeleted }: {
  items: Product[]; clientsById?: Record<string, string>; onEdit: (p: Product) => void; onDeleted: (id: string) => void;
}) {
  const { session } = useAuth();
  const canDelete = session && ["owner", "admin", "manager"].includes(session.user.role);
  const del = async (p: Product) => { if (!confirm(`Delete ${p.name}?`)) return; try { await api.deleteProduct(p.id); onDeleted(p.id); } catch (e) { alert(e instanceof Error ? e.message : "Delete failed"); } };
  if (!items.length) return <Empty title="No products or services yet" body="Add what the client sells — this is the input for buyer discovery later." icon={<Package className="h-5 w-5" />} />;
  return (
    <div className="grid gap-4 p-5 md:grid-cols-2">
      {items.map((p) => (
        <div key={p.id} className="rounded-xl border border-line p-4 transition hover:border-brand-200">
          <div className="flex items-start justify-between gap-3">
            <div><div className="flex items-center gap-2"><h4 className="font-medium text-navy-950">{p.name}</h4><Badge tone={p.kind === "service" ? "violet" : "blue"}>{p.kind}</Badge></div>
              <div className="text-xs text-navy-500">{[p.category, clientsById?.[p.client_id]].filter(Boolean).join(" · ") || "Uncategorised"}</div></div>
            <div className="flex gap-1">
              <button onClick={() => onEdit(p)} className="rounded p-1.5 text-navy-500 hover:bg-canvas" aria-label="Edit"><Pencil className="h-4 w-4" /></button>
              {canDelete && <button onClick={() => del(p)} className="rounded p-1.5 text-navy-500 hover:bg-red-50 hover:text-red-600" aria-label="Delete"><Trash2 className="h-4 w-4" /></button>}
            </div>
          </div>
          {p.description && <p className="mt-2 line-clamp-2 text-sm text-navy-700">{p.description}</p>}
          <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
            {[["Pricing", p.pricing], ["MOQ", p.min_order_quantity], ["Capacity", p.production_capacity]].map(([k, val]) => (
              <div key={k}><dt className="text-navy-400">{k}</dt><dd className="font-medium text-navy-800">{val || "Not supplied"}</dd></div>))}
          </dl>
          {!!p.target_industries.length && <div className="mt-3 flex flex-wrap gap-1">{p.target_industries.map((t) => <Badge key={t}>{t}</Badge>)}</div>}
        </div>
      ))}
    </div>
  );
}

export function AddProductButton({ onClick }: { onClick: () => void }) { return <Button size="sm" onClick={onClick}><Plus className="h-4 w-4" />Add item</Button>; }
