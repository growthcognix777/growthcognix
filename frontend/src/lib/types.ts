// Typed interfaces mirroring backend/app/schemas.py
export type Role = "owner" | "admin" | "manager" | "staff";

export interface User { id: string; email: string; full_name: string; role: Role; is_active: boolean; created_at: string; }
export interface Tenant { id: string; name: string; slug: string; website?: string | null; phone?: string | null; address?: string | null; }
export interface Session { access_token: string; token_type: string; user: User; tenant: Tenant; }

export interface Page<T> { items: T[]; total: number; }

export interface ClientInput {
  company_name: string;
  website?: string | null;
  industry?: string | null;
  business_type?: string | null;
  description?: string | null;
  address?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  target_markets: string[];
  marketing_budget?: number | null;
  budget_currency: string;
  business_objectives?: string | null;
  assigned_user_id?: string | null;
}
export interface Client extends ClientInput {
  id: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  product_count: number;
  document_count: number;
}

export type ProductKind = "product" | "service";
export interface ProductInput {
  client_id: string;
  kind: ProductKind;
  name: string;
  category?: string | null;
  description?: string | null;
  specifications?: string | null;
  applications?: string | null;
  pricing?: string | null;
  min_order_quantity?: string | null;
  production_capacity?: string | null;
  target_industries: string[];
}
export interface Product extends ProductInput { id: string; created_at: string; updated_at: string; }

export interface DocumentMeta {
  id: string; client_id: string; product_id: string | null; original_name: string;
  content_type: string; file_ext: string; size_bytes: number; extraction_status: string; created_at: string;
}

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export interface ResearchJob {
  id: string; client_id: string | null; job_type: string; agent_key: string | null; status: JobStatus;
  progress: number; started_at: string | null; completed_at: string | null; error: string | null;
  result: Record<string, unknown> | null; params: Record<string, unknown>; created_at: string;
}

export interface Agent { key: string; name: string; phase: number; description: string; status: "planned" | "active"; total_jobs: number; last_job_at: string | null; }

export interface Activity { id: string; user_id: string | null; action: string; entity_type: string; entity_id: string | null; summary: string; meta: Record<string, unknown>; created_at: string; }

export interface DashboardSummary { active_clients: number; archived_clients: number; products: number; documents: number; team_members: number; jobs_running: number; }

export interface FieldError { field: string; message: string; }
export class ApiError extends Error {
  status: number; errors: FieldError[];
  constructor(status: number, message: string, errors: FieldError[] = []) { super(message); this.status = status; this.errors = errors; }
}

// ---------------------------------------------------------------- Phase 2: Client Intelligence
export type FindingType = "profile" | "application" | "market" | "persona" | "insight";
export type VerificationStatus = "verified" | "ai_hypothesis" | "needs_review" | "rejected";
export interface Evidence {
  id: string; source_type: string; source_url: string | null; document_id: string | null;
  excerpt: string | null; quote_matched: boolean | null; created_at: string;
}
export interface Finding {
  id: string; type: FindingType; client_id: string; verification_status: VerificationStatus;
  confidence: number | null; is_inferred: boolean; approved: boolean; origin: string; edited: boolean;
  analysis_job_id: string | null; reviewed_by: string | null; reviewed_at: string | null; review_note: string | null;
  created_at: string; updated_at: string; data: Record<string, unknown>; evidence: Evidence[];
}
export interface AnalysisStage { key: string; label: string; status: string; error: string | null; result: Record<string, unknown> | null; }
export interface Analysis {
  id: string; client_id: string; status: JobStatus; progress: number; stages: AnalysisStage[]; attempts: number;
  provider: string | null; model: string | null; params: Record<string, unknown>; error: string | null;
  summary: Record<string, unknown> | null; started_at: string | null; completed_at: string | null; created_at: string;
}
export interface ProviderInfo { name: string; model: string; configured: boolean; used_for: string; }
export interface IntelligenceProviders { providers: ProviderInfo[]; stages: string[]; }
export interface IntelligenceSummary {
  status_counts: Record<VerificationStatus, number>;
  sources: { documents: number; documents_extracted: number; evidence_items: number };
  last_analysis: Analysis | null;
}
