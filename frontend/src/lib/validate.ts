// Frontend validation mirroring backend rules. The backend validates again; never trust the browser alone.
import type { ClientInput, FieldError, ProductInput } from "./types";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const PHONE = /^[0-9+()\-\s]{6,40}$/;

export const isEmail = (v: string) => EMAIL.test(v.trim());

export function normaliseUrl(v?: string | null): string | null {
  if (!v || !v.trim()) return null;
  const s = v.trim();
  return /^https?:\/\//i.test(s) ? s : `https://${s}`;
}

export function validUrl(v: string): boolean {
  try { const u = new URL(v); return !!u.hostname.includes("."); } catch { return false; }
}

export function validatePassword(p: string): string | null {
  if (p.length < 8) return "Use at least 8 characters";
  if (!/[0-9]/.test(p) || !/[a-z]/i.test(p)) return "Use letters and numbers";
  return null;
}

export function validateRegister(v: { agency_name: string; full_name: string; email: string; password: string }): FieldError[] {
  const e: FieldError[] = [];
  if (v.agency_name.trim().length < 2) e.push({ field: "agency_name", message: "Enter your agency name" });
  if (v.full_name.trim().length < 2) e.push({ field: "full_name", message: "Enter your full name" });
  if (!isEmail(v.email)) e.push({ field: "email", message: "Enter a valid email address" });
  const pw = validatePassword(v.password); if (pw) e.push({ field: "password", message: pw });
  return e;
}

export function validateClient(v: ClientInput): FieldError[] {
  const e: FieldError[] = [];
  if ((v.company_name || "").trim().length < 2) e.push({ field: "company_name", message: "Company name is required" });
  const url = normaliseUrl(v.website);
  if (url && !validUrl(url)) e.push({ field: "website", message: "Enter a valid website, e.g. example.com" });
  if (v.contact_email && !isEmail(v.contact_email)) e.push({ field: "contact_email", message: "Enter a valid email" });
  if (v.contact_phone && !PHONE.test(v.contact_phone)) e.push({ field: "contact_phone", message: "Use digits, spaces, + ( ) or -" });
  if (v.marketing_budget != null && (isNaN(v.marketing_budget) || v.marketing_budget < 0)) e.push({ field: "marketing_budget", message: "Budget must be zero or more" });
  if (!/^[A-Z]{3}$/.test(v.budget_currency)) e.push({ field: "budget_currency", message: "Use a 3-letter currency code" });
  return e;
}

export function validateProduct(v: ProductInput): FieldError[] {
  const e: FieldError[] = [];
  if (!v.client_id) e.push({ field: "client_id", message: "Choose a client" });
  if ((v.name || "").trim().length < 2) e.push({ field: "name", message: "Name is required" });
  return e;
}

export const ALLOWED_EXT = ["pdf", "docx", "jpg", "jpeg", "png"] as const;
export const MAX_UPLOAD_MB = 20;
export function validateFile(f: { name: string; size: number }): string | null {
  const ext = f.name.split(".").pop()?.toLowerCase() || "";
  if (!(ALLOWED_EXT as readonly string[]).includes(ext)) return "Only PDF, DOCX, JPG and PNG files are allowed";
  if (f.size === 0) return "File is empty";
  if (f.size > MAX_UPLOAD_MB * 1024 * 1024) return `File is larger than ${MAX_UPLOAD_MB} MB`;
  return null;
}
