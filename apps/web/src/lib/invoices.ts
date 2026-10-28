// Invoice shapes from the API (docs/11-api-spec.md) and display helpers.

export type InvoiceStatus =
  | "received"
  | "extracting"
  | "extraction_failed"
  | "needs_review"
  | "awaiting_approval"
  | "approved"
  | "posting"
  | "posted"
  | "posting_failed"
  | "rejected"
  | "not_invoice";

export interface InvoiceSummary {
  id: string;
  status: InvoiceStatus;
  status_reason: string;
  filename: string;
  vendor_name: string;
  invoice_number: string;
  invoice_date: string | null;
  currency: string;
  total: string | null;
  route: string;
  created_at: string;
}

export interface Evidence {
  value: string | null;
  printed?: string | null;
  page?: number;
  box?: [number, number, number, number];
  grounding: string;
  trust?: string;
  rejected?: string;
}

export interface CheckResult {
  code: string;
  severity: "info" | "warning" | "blocking";
  message: string;
  fields: string[];
}

export interface InvoiceDetail extends InvoiceSummary {
  fields: Record<string, Evidence>;
  lines: Record<string, Evidence>[];
  checks: CheckResult[];
  decision: { route?: string; reasons?: string[]; vendor_matched_by?: string; rules_version?: string };
  extraction: { provider?: string; model?: string; input_tokens?: number; output_tokens?: number; ms?: number; notes?: string };
  pages: { number: number; width: number; height: number }[];
  po_number: string | null;
  has_text_layer: boolean;
  uploaded_by: string | null;
  decided_by: string | null;
  decided_at: string | null;
  erp_bill_id: string;
  erp_url: string;
}

export const BUSY: InvoiceStatus[] = ["received", "extracting", "approved", "posting"];

export const STATUS: Record<InvoiceStatus, { label: string; tone: string }> = {
  received: { label: "Received", tone: "bg-canvas text-muted" },
  extracting: { label: "Reading…", tone: "bg-canvas text-muted" },
  extraction_failed: { label: "Couldn't read", tone: "bg-danger/10 text-danger" },
  needs_review: { label: "Needs review", tone: "bg-warn-soft text-warn" },
  awaiting_approval: { label: "Awaiting approval", tone: "bg-accent/10 text-accent" },
  approved: { label: "Approved", tone: "bg-ok/10 text-ok" },
  posting: { label: "Posting…", tone: "bg-ok/10 text-ok" },
  posted: { label: "Posted to ERP", tone: "bg-ok/15 text-ok" },
  posting_failed: { label: "Posting failed", tone: "bg-danger/10 text-danger" },
  rejected: { label: "Rejected", tone: "bg-canvas text-muted line-through" },
  not_invoice: { label: "Not an invoice", tone: "bg-canvas text-muted" },
};

export const FIELD_LABELS: Record<string, string> = {
  vendor_name: "Vendor",
  vendor_tax_id: "Tax ID (NTN)",
  vendor_email: "Vendor email",
  bank_account: "Bank account",
  invoice_number: "Invoice number",
  invoice_date: "Invoice date",
  due_date: "Due date",
  po_number: "PO number",
  currency: "Currency",
  subtotal: "Subtotal",
  tax_total: "Tax",
  shipping: "Shipping",
  total: "Total",
};

export function money(value: string | null, currency = ""): string {
  if (value === null || value === "") return "—";
  const n = Number(value);
  return `${currency ? `${currency} ` : ""}${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
