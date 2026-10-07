// ─────────────────────────────────────────────────────────────────────────────
// NEXUS ERP — API Service (Module 2 complete)
// src/services/api.ts
// ─────────────────────────────────────────────────────────────────────────────

declare global {
  interface ImportMetaEnv {
    readonly VITE_API_URL?: string;
  }

  interface ImportMeta {
    readonly env: ImportMetaEnv;
  }
}

const API_BASE_URL =
  import.meta.env.VITE_API_URL ||
  "http://127.0.0.1:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("nexus_token") : null;
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ═══════════════════════════════════════════════════════════════════════════════
// HEALTH
// ═══════════════════════════════════════════════════════════════════════════════
export const checkHealth = () =>
  apiFetch<{ status: string; db_connected: boolean; version: string }>("/health");

// ═══════════════════════════════════════════════════════════════════════════════
// AUTH
// ═══════════════════════════════════════════════════════════════════════════════
export interface AuthUser {
  id: string;
  name: string;
  email: string;
  role: string;
}

export const loginUser = (email: string, password: string) =>
  apiFetch<{ user: AuthUser; token: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const signupUser = (name: string, email: string, password: string) =>
  apiFetch<{ message: string; user_id: string }>("/api/auth/signup", {
    method: "POST",
    body: JSON.stringify({ name, email, password }),
  });

// ═══════════════════════════════════════════════════════════════════════════════
// INVENTORY (Module 2 — DB backed)
// ═══════════════════════════════════════════════════════════════════════════════
export interface InventoryItem {
  item_id: string;
  name: string;
  unit: string;
  min_threshold: number;
  critical_threshold: number;
  current_stock: number;
  daily_consumption: number;
  reorder_quantity: number;
  unit_price?: number | null;
  vendor_id?: string | null;
  vendor_name: string;
  vendor_email: string;
  status: "OK" | "Low" | "Critical" | "Out of Stock";
  category: string;
  days_until_reorder: number;
  days_until_critical: number;
  predicted_demand: number;
  stock_pct: number;
  last_updated: string;
}

export interface InventoryOverview {
  summary: { 
    total_items: number; 
    ok: number; 
    low: number; 
    critical: number; 
    out_of_stock: number;
    predicted_demand?: number;
    by_category?: Record<string, { total: number; ok: number; low: number; critical: number; predicted_demand: number; }>;
  };
  items: InventoryItem[];
  timestamp: string;
}

export const getInventoryOverview = () =>
  apiFetch<InventoryOverview>("/api/inventory/overview");

export const getInventoryItem = (itemId: string) =>
  apiFetch<InventoryItem>(`/api/inventory/item/${itemId}`);

export const runInventoryCheck = () =>
  apiFetch<{ message: string; new_orders: ProcurementOrder[] }>(
    "/api/inventory/check",
    { method: "POST" }
  );

export const updateStock = (itemId: string, stock: number, notes?: string) =>
  apiFetch(`/api/inventory/item/${itemId}/stock`, {
    method: "PUT",
    body: JSON.stringify({ current_stock: stock, notes }),
  });

// ═══════════════════════════════════════════════════════════════════════════════
// DEMAND PREDICTION (by date)
// ═══════════════════════════════════════════════════════════════════════════════
export interface DemandPredictionItem {
  item_id: string;
  name: string;
  unit: string;
  category: string;
  current_stock: number;
  predicted_demand: number;
  status: "OK" | "Low" | "Critical" | "Out of Stock" | "Unknown";
  reorder_needed: boolean;
  reorder_quantity: number;
  trigger_type: string;
}

export interface DemandForecastResponse {
  date: string;
  season: string;
  model_loaded: boolean;
  total_predicted_demand: number;
  items: DemandPredictionItem[];
  generated_at: string;
}

export const getDemandForecast = (date: string) =>
  apiFetch<DemandForecastResponse>(`/api/inventory/demand-forecast?date=${date}`);

// ═══════════════════════════════════════════════════════════════════════════════
// PROCUREMENT ORDERS
// ═══════════════════════════════════════════════════════════════════════════════
export interface TrackingEvent {
  ts: string;
  status: string;
  location: string;
  notes: string;
}

export interface ContractAuditEntry {
  id: string;
  action: string;
  tx_hash: string;
  block_number: number;
  payload: Record<string, unknown>;
  performed_at: string;
}

export interface DeliveryCheckin {
  id: string;
  order_id: string;
  checkin_at: string;
  location: string;
  status: string;
  quantity_received: number;
  condition: "Good" | "Partial" | "Damaged";
  notes: string;
  is_final: boolean;
}

export interface ProcurementOrder {
  id: string;
  order_code: string;
  item_id: string;
  item_name: string;
  unit: string;
  vendor_name: string;
  vendor_email: string;
  quantity: number;
  unit_price: number | null;
  total_price: number | null;
  trigger_type: "VEMA-Triggered" | "Auto-Generated" | "Auto-Generated (Demand > Stock)" | "Manual";
  stage: string;
  vendor_email_sent: boolean;
  vendor_confirmed: boolean;
  contract_status: "Pending" | "Signed" | "Executed" | "Rejected";
  contract_hash: string | null;
  expected_delivery: string;
  actual_delivery: string | null;
  delivery_confirmed: boolean;
  delivery_condition: string | null;
  tracking_events: TrackingEvent[];
  smart_contract_data: Record<string, unknown> | null;
  below_20pct_trigger?: boolean;
  pm_approval_status?: "Not Required" | "Pending" | "Approved" | "Rejected";
  pm_approved_by?: string | null;
  pm_approved_at?: string | null;
  vendor_response_token?: string | null;
  vendor_decision?: "Accepted" | "Rejected" | null;
  vendor_responded_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrderListResponse {
  total: number;
  orders: ProcurementOrder[];
}

export interface OrderDetailResponse {
  order: ProcurementOrder;
  checkins: DeliveryCheckin[];
  audit: ContractAuditEntry[];
}

export const listOrders = (params?: {
  stage?: string;
  item_id?: string;
  limit?: number;
  offset?: number;
}) => {
  const q = new URLSearchParams();
  if (params?.stage) q.set("stage", params.stage);
  if (params?.item_id) q.set("item_id", params.item_id);
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.offset) q.set("offset", String(params.offset));
  return apiFetch<OrderListResponse>(`/api/procurement/orders?${q}`);
};

export const getOrder = (orderId: string) =>
  apiFetch<OrderDetailResponse>(`/api/procurement/orders/${orderId}`);

export const createOrder = (payload: {
  item_id: string;
  quantity: number;
  unit_price?: number;
  trigger_type?: string;
  expected_delivery?: string;
}) =>
  apiFetch<{ order_id: string; order_code: string; stage: string; email_sent: boolean }>(
    "/api/procurement/orders",
    { method: "POST", body: JSON.stringify(payload) }
  );

export const manualReorder = (item_id: string, quantity: number, unit_price?: number) =>
  apiFetch<{ order_id: string; order_code: string; stage: string; email_sent: boolean }>(
    "/api/procurement/manual-reorder",
    {
      method: "POST",
      body: JSON.stringify({ item_id, quantity, unit_price }),
    }
  );

export const signContract = (orderId: string, signatory: string) =>
  apiFetch(`/api/procurement/sign/${orderId}`, {
    method: "POST",
    body: JSON.stringify({ signatory, role: "operator" }),
  });

export const submitDeliveryCheckin = (
  orderId: string,
  payload: {
    location?: string;
    status: string;
    quantity_received: number;
    condition: "Good" | "Partial" | "Damaged";
    notes?: string;
    is_final: boolean;
    checked_by?: string;
  }
) =>
  apiFetch<{ checkin_id: string; contract_executed: boolean; execution_hash: string | null }>(
    `/api/procurement/checkin/${orderId}`,
    { method: "POST", body: JSON.stringify(payload) }
  );

export const getCheckins = (orderId: string) =>
  apiFetch<{ checkins: DeliveryCheckin[] }>(`/api/procurement/checkins/${orderId}`);

// ═══════════════════════════════════════════════════════════════════════════════
// PROCUREMENT MANAGER — REORDER APPROVAL WORKFLOW (Section 3)
// ═══════════════════════════════════════════════════════════════════════════════
export const listPendingApprovals = () =>
  apiFetch<{ orders: ProcurementOrder[] }>("/api/procurement/pending-approvals");

export const approveReorder = (orderId: string) =>
  apiFetch<{ message: string; vendor_email_status: string }>(
    `/api/procurement/approve/${orderId}`,
    { method: "POST" }
  );

export const rejectReorder = (orderId: string, reason?: string) =>
  apiFetch<{ message: string }>(`/api/procurement/reject/${orderId}`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export interface VendorCommLogEntry {
  id: string;
  order_id: string;
  channel: string;
  status: "Sent" | "Failed" | "Simulated";
  triggered_by: string | null;
  response_body: string | null;
  sent_at: string;
}

export const getVendorCommLog = (orderId: string) =>
  apiFetch<{ log: VendorCommLogEntry[] }>(`/api/procurement/vendor-comm-log/${orderId}`);

export const resendVendorEmail = (orderId: string) =>
  apiFetch<{ message: string; vendor_email_status: string }>(
    `/api/procurement/vendor-comm-log/${orderId}/resend`,
    { method: "POST" }
  );

// ═══════════════════════════════════════════════════════════════════════════════
// BILLING / INVOICES
// ═══════════════════════════════════════════════════════════════════════════════
export interface InvoiceLineItem {
  description: string;
  item_id: string;
  quantity: number;
  unit: string;
  unit_price: number | null;
  line_total: number | null;
}

export interface Invoice {
  invoice_number: string;
  order_code: string;
  issued_at: string;
  status: string;
  company: { name: string; tagline: string; address: string; email: string };
  vendor: { name: string; email: string };
  line_items: InvoiceLineItem[];
  subtotal: number | null;
  blockchain_fee_rate: number;
  blockchain_fee: number | null;
  tax_rate: number;
  tax: number | null;
  total: number | null;
  currency: string;
  contract_hash: string | null;
  contract_status: string | null;
  expected_delivery: string | null;
  trigger_type: string;
  pricing_pending: boolean;
}

export const getInvoice = (orderId: string) =>
  apiFetch<Invoice>(`/api/procurement/orders/${orderId}/invoice`);

/**
 * Downloads the PDF invoice for an order and triggers a browser save.
 * Uses a raw fetch (not apiFetch) since the response is a binary blob, not JSON.
 */
export const downloadInvoicePdf = async (orderId: string, filenameHint?: string) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("nexus_token") : null;
  const res = await fetch(`${API_BASE_URL}/api/procurement/orders/${orderId}/invoice/pdf`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new Error(`Failed to generate invoice PDF (${res.status})`);
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameHint ? `${filenameHint}.pdf` : `invoice-${orderId}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

// ═══════════════════════════════════════════════════════════════════════════════
// NOTIFICATIONS (DB backed)
// ═══════════════════════════════════════════════════════════════════════════════
export interface Notification {
  id: string;
  category: string;
  title: string;
  description: string;
  is_read: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  // Phase 3 fields — present on anything created via notification_engine.notify();
  // older rows (and every pre-Phase-3 caller) simply leave these null/default.
  type?: string | null;
  severity?: "info" | "success" | "warning" | "critical";
  entity_type?: string | null;
  entity_id?: string | null;
  action_url?: string | null;
  action_label?: string | null;
  requires_action?: boolean;
  read_at?: string | null;
  resolved_at?: string | null;
  archived_at?: string | null;
}

export const getNotifications = (params?: {
  unread?: boolean;
  category?: string;
  severity?: string;
  requires_action?: boolean;
  archived?: boolean;
  limit?: number;
  offset?: number;
  /** @deprecated the backend now derives the user from the auth token — kept
   * only so no existing call site breaks; it's ignored server-side. */
  user_id?: string;
}) => {
  const q = new URLSearchParams();
  if (params?.unread) q.set("unread", "true");
  if (params?.category) q.set("category", params.category);
  if (params?.severity) q.set("severity", params.severity);
  if (params?.requires_action !== undefined) q.set("requires_action", String(params.requires_action));
  if (params?.archived) q.set("archived", "true");
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.offset) q.set("offset", String(params.offset));
  return apiFetch<{ unread_count: number; notifications: Notification[] }>(
    `/api/notifications?${q}`
  );
};

export const getUnreadCount = () => apiFetch<{ count: number }>("/api/notifications/unread-count");

export const markNotificationRead = (id: string) =>
  apiFetch(`/api/notifications/${id}/read`, { method: "PATCH" });

export const markAllNotificationsRead = (category?: string) => {
  const q = category ? `?category=${encodeURIComponent(category)}` : "";
  return apiFetch(`/api/notifications/mark-all-read${q}`, { method: "PATCH" });
};

export const archiveNotification = (id: string) =>
  apiFetch<{ message: string }>(`/api/notifications/${id}/archive`, { method: "POST" });

export interface NotificationPreference {
  type: string;
  category: string;
  severity: string;
  locked: boolean;
  in_app: boolean;
  email: boolean;
  has_email: boolean;
}

export const getNotificationPreferences = () =>
  apiFetch<{ preferences: NotificationPreference[] }>("/api/notifications/preferences");

export const updateNotificationPreference = (type: string, in_app: boolean, email: boolean) =>
  apiFetch<{ message: string; locked: boolean }>("/api/notifications/preferences", {
    method: "PUT",
    body: JSON.stringify({ type, in_app, email }),
  });

/**
 * Live notification stream — Server-Sent Events, with a 15s-poll fallback
 * if SSE can't connect (proxies/older browsers). Returns an unsubscribe
 * function; call it on unmount.
 */
export const subscribeToNotifications = (onNotification: (n: Notification) => void): (() => void) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("nexus_token") : null;
  if (!token) return () => {};

  let stopped = false;
  let pollId: ReturnType<typeof setInterval> | null = null;
  let es: EventSource | null = null;
  let seenIds = new Set<string>();

  const startPolling = () => {
    if (pollId) return;
    pollId = setInterval(async () => {
      try {
        const res = await getNotifications({ limit: 10 });
        for (const n of res.notifications) {
          if (!seenIds.has(n.id)) {
            seenIds.add(n.id);
            onNotification(n);
          }
        }
      } catch {
        // silent — next tick retries
      }
    }, 15000);
  };

  try {
    es = new EventSource(`${API_BASE_URL}/api/notifications/stream?token=${encodeURIComponent(token)}`);
    es.onmessage = (ev) => {
      try {
        const n = JSON.parse(ev.data) as Notification;
        seenIds.add(n.id);
        onNotification(n);
      } catch {
        // ignore malformed event
      }
    };
    es.onerror = () => {
      if (stopped) return;
      es?.close();
      es = null;
      startPolling();
    };
  } catch {
    startPolling();
  }

  return () => {
    stopped = true;
    es?.close();
    if (pollId) clearInterval(pollId);
  };
};

// ═══════════════════════════════════════════════════════════════════════════════
// OUTAGE / FORECAST (Module 1 — unchanged)
// ═══════════════════════════════════════════════════════════════════════════════
export interface ForecastDay {
  date: string;
  day: string;
  demand_kwh: number;
  outage_probability: number;
  risk_level: "Low" | "Medium" | "High";
  affected_zones: string[];
  weather_factors: string[];
  recommended_actions: string[];
}
export interface ForecastResponse {
  generated_at: string;
  forecast: ForecastDay[];
}
export const getOutageForecast = () =>
  apiFetch<ForecastResponse>("/api/forecast");
export const getForecastByDate = (date: string) =>
  apiFetch<ForecastDay>(`/api/forecast/${date}`);

// ═══════════════════════════════════════════════════════════════════════════════
// VEMA COMPLAINTS (Section 4/5/6)
// ═══════════════════════════════════════════════════════════════════════════════
export type ComplaintSeverity = "small" | "medium" | "critical";
export type ComplaintStatus = "open" | "auto_resolved" | "escalated" | "resolved";
export type ComplaintChannel = "voice" | "chat" | "manual";

export interface Complaint {
  id: string;
  ticket_code: string;
  reference_id: string | null;
  customer_id: string | null;
  customer_name: string | null;
  customer_email: string | null;
  channel: ComplaintChannel;
  category: string;
  subtype: string;
  severity: ComplaintSeverity;
  description: string;
  area: string | null;
  status: ComplaintStatus;
  vema_triggered: boolean;
  assigned_cr: string | null;
  escalated_at: string | null;
  resolved_at: string | null;
  resolution: string | null;
  next_reminder_due: string | null;
  reminder_count: number;
  created_at: string;
  updated_at: string;
}

export interface ComplaintEvent {
  id: string;
  complaint_id: string;
  event_type: "voice_transcript" | "chat_message" | "system_action" | "escalation" | "reminder" | "resolution";
  actor: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export const getComplaints = (params?: {
  status?: string; category?: string; severity?: string; search?: string;
  order?: "recent" | "priority"; limit?: number;
}) => {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.category) q.set("category", params.category);
  if (params?.severity) q.set("severity", params.severity);
  if (params?.search) q.set("search", params.search);
  if (params?.order) q.set("order", params.order);
  if (params?.limit) q.set("limit", String(params.limit));
  return apiFetch<{ total: number; tickets: Complaint[] }>(`/api/complaints?${q}`);
};

export const getMyComplaints = () => apiFetch<{ tickets: Complaint[] }>("/api/complaints/mine");

export const getComplaint = (id: string) =>
  apiFetch<{ ticket: Complaint; events: ComplaintEvent[] }>(`/api/complaints/${id}`);

export const resolveComplaint = (id: string, resolution: string) =>
  apiFetch<{ message: string }>(`/api/complaints/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ action: "resolve", resolution }),
  });

export const escalateComplaint = (id: string, note?: string) =>
  apiFetch<{ message: string }>(`/api/complaints/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ action: "escalate", note }),
  });

export const submitChatComplaint = (message: string, area?: string) =>
  apiFetch<{
    ticket_code: string; ticket_id: string; reference_id: string;
    classification: Record<string, unknown>; status: string; reply_text: string;
  }>(
    "/api/complaints/chat",
    { method: "POST", body: JSON.stringify({ message, area }) }
  );

/**
 * Step 1 of the voice flow: speech-to-text only. No ticket is created — the
 * customer reviews/edits the transcript, then calls submitVoiceComplaint().
 */
export const transcribeVoiceComplaint = async (audioBlob: Blob) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("nexus_token") : null;
  const form = new FormData();
  form.append("audio", audioBlob, "recording.webm");
  const res = await fetch(`${API_BASE_URL}/api/complaints/voice/transcribe`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error ${res.status}`);
  }
  return res.json() as Promise<{ transcript: string; transcription_engine: string }>;
};

/** Step 2: submit the confirmed (possibly edited) voice transcript. */
export const submitVoiceComplaint = (message: string, area?: string) =>
  apiFetch<{
    ticket_code: string; ticket_id: string; reference_id: string; transcript: string;
    classification: Record<string, unknown>; status: string; reply_text: string;
    reply_audio_base64: string | null; reply_audio_available: boolean;
  }>("/api/complaints/voice", { method: "POST", body: JSON.stringify({ message, area }) });

/**
 * Read-only preview: classifies a draft complaint and suggests at most one
 * clarifying follow-up question (e.g. "which area?") if something important
 * seems missing — never creates a ticket. Used by the voice call to ask a
 * natural follow-up before filing.
 */
export const previewComplaint = (message: string) =>
  apiFetch<{
    classification: { category: string; subtype: string; severity: string; summary: string };
    followup_question: string | null;
  }>("/api/complaints/preview", { method: "POST", body: JSON.stringify({ message }) });

/** Withdraw one of your own complaints (only while status is open/auto_resolved). */
export const deleteComplaint = (id: string) =>
  apiFetch<{ message: string }>(`/api/complaints/${id}`, { method: "DELETE" });

export const getComplaintTaxonomy = () => apiFetch<Record<string, string[]>>("/api/complaints/taxonomy");

// ─── Feature B: complaint category reference ────────────────────────────────
export interface ComplaintCategoryRef {
  category: string;
  code: string;
  description: string;
  default_severity: ComplaintSeverity;
  routing_hint: string;
  example_phrases: { en: string[]; roman_ur: string[] };
  subtypes: string[];
  required_fields: string[];
  guidance: string | null;
  ticket_count: number;
}

export const getComplaintCategories = () =>
  apiFetch<ComplaintCategoryRef[]>("/api/complaints/categories");

export const createManualComplaint = (payload: {
  description: string; category: string; subtype: string; severity?: string;
  customer_name?: string; customer_email?: string; area?: string;
}) =>
  apiFetch<{ ticket_id: string; ticket_code: string; status: string }>("/api/complaints/manual", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// ═══════════════════════════════════════════════════════════════════════════════
// DASHBOARD ANALYTICS (Module 1 — unchanged)
// ═══════════════════════════════════════════════════════════════════════════════
export interface SalesSummary { total_records: number; total_demand: number; avg_price: number; total_units_sold: number; total_promotions: number; }
export interface CategoryData { Category: string; total_demand: number; total_units_sold: number; avg_price: number; }
export interface RegionData { Region: string; total_demand: number; total_units_sold: number; record_count: number; }
export interface TrendData { period: string; total_demand: number; total_units_sold: number; avg_price: number; }
export interface InventoryStatus { Category: string; avg_inventory: number; min_inventory: number; max_inventory: number; avg_units_ordered: number; }
export interface PredictionRequest { Date: string; Store_ID?: string; Product_ID?: string; Category: string; Region: string; Inventory_Level: number; Units_Sold: number; Units_Ordered: number; Price: number; Discount: number; Weather_Condition: string; Promotion: number; Competitor_Pricing: number; Seasonality: string; Epidemic: number; }
export interface PredictionResponse { predicted_demand: number; status: string; reorder_needed: boolean; reorder_quantity: number; trigger_type: string; message: string; }

export const getSalesSummary = () => apiFetch<SalesSummary>("/sales/summary");
export const getSalesByCategory = () => apiFetch<{ data: CategoryData[] }>("/sales/by-category");
export const getSalesByRegion = () => apiFetch<{ data: RegionData[] }>("/sales/by-region");
export const getSalesTrend = (groupBy: "day" | "month" | "year" = "month") => apiFetch<{ data: TrendData[]; group_by: string }>(`/sales/trend?group_by=${groupBy}`);
export const getInventoryStatus = () => apiFetch<{ data: InventoryStatus[] }>("/sales/inventory-status");
export const predictDemand = (payload: PredictionRequest) => apiFetch<PredictionResponse>("/api/predict", { method: "POST", body: JSON.stringify(payload) });

// ═══════════════════════════════════════════════════════════════════════════════
// VEMA RAG — Q&A + complaint grounding (Features C/D, see VEMA_RAG.md)
// ═══════════════════════════════════════════════════════════════════════════════
export interface RagQueryResponse {
  reply: string;
  intent: "complaint_intake" | "information_question" | "smalltalk";
  grounded: boolean;
  sources: string[];
  retrieval_scores: number[];
}

export const ragQuery = (question: string, category?: string) =>
  apiFetch<RagQueryResponse>("/api/rag/query", {
    method: "POST",
    body: JSON.stringify({ question, category }),
  });

export interface RagStats {
  total: number;
  by_doc_type: Record<string, { count: number; last_updated: string | null }>;
  embedding_backend: "gemini" | "hashing";
}

export const getRagStats = () => apiFetch<RagStats>("/api/rag/stats");

export interface RagIngestResponse {
  ingested: number;
  skipped: number;
  duplicates: number;
  skip_reasons: string[];
}

export const ragIngest = async (file: File) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("nexus_token") : null;
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE_URL}/api/rag/ingest`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error ${res.status}`);
  }
  return res.json() as Promise<RagIngestResponse>;
};

export const ragReindex = () =>
  apiFetch<{ category_kb_documents: number; resolved_ticket_documents: number }>("/api/rag/reindex", { method: "POST" });

export interface SimilarCase {
  ticket_code: string | null;
  category: string | null;
  summary: string;
  resolution: string;
  score: number;
}

export const getSimilarCases = (ticketId: string) =>
  apiFetch<{ cases: SimilarCase[] }>(`/api/complaints/${ticketId}/similar`);

// ═══════════════════════════════════════════════════════════════════════════════
// VENDORS — registration, vetting, approved catalogue
// Vendors never get a login: everything here is either the public
// "Become a Vendor" form, or Admin/Procurement Manager review screens.
// ═══════════════════════════════════════════════════════════════════════════════

export interface VendorApplicationItemInput {
  name: string;
  sku?: string;
  category?: string;
  description?: string;
  unit: string;
  unit_price: number;
  moq?: number;
  lead_time_days?: number;
}

export interface VendorApplicationPayload {
  legal_company_name: string;
  trade_name?: string;
  business_type: string;
  ntn: string;
  strn?: string;
  secp_number?: string;
  year_established?: number;
  employee_range?: string;
  website?: string;
  categories: string[];

  contact_name: string;
  contact_designation?: string;
  order_email: string;
  mobile: string;
  alternate_phone?: string;
  address: string;
  city: string;
  province: string;
  postal_code?: string;
  coverage_provinces: string[];
  coverage_cities: string[];

  lead_time_days?: number;
  payment_terms?: string;
  min_order_value?: number;
  warranty?: string;
  bank_name?: string;
  bank_account_title?: string;
  bank_iban?: string;
  certifications: string[];

  items: VendorApplicationItemInput[];
  consent: boolean;
  website_hp?: string; // honeypot — always leave blank
}

export const getVendorCategories = () =>
  apiFetch<{ categories: string[] }>("/api/public/vendors/categories");

export const getVendorTemplateUrl = () => `${API_BASE_URL}/api/public/vendors/template`;

export interface ParsedCatalogueRow {
  row_number: number;
  name: string | null;
  sku: string | null;
  category: string | null;
  description: string | null;
  unit: string | null;
  unit_price: number | null;
  moq: number | null;
  lead_time_days: number | null;
}
export interface ParsedCatalogueInvalidRow extends ParsedCatalogueRow {
  errors: string[];
}
export interface ParseCatalogueResponse {
  valid_rows: ParsedCatalogueRow[];
  invalid_rows: ParsedCatalogueInvalidRow[];
  row_count: number;
  truncated: boolean;
}

export const parseVendorCatalogueFile = async (file: File): Promise<ParseCatalogueResponse> => {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE_URL}/api/public/vendors/items/parse`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error ${res.status}`);
  }
  return res.json();
};

export interface VendorDocumentUpload {
  file: File;
  doc_type: string;
}

export const applyVendor = async (
  payload: VendorApplicationPayload,
  documents: VendorDocumentUpload[]
): Promise<{ application_id: string; reference_code: string; message: string }> => {
  const form = new FormData();
  form.append("payload", JSON.stringify(payload));
  form.append("document_types", JSON.stringify(documents.map((d) => d.doc_type)));
  documents.forEach((d) => form.append("documents", d.file, d.file.name));

  const res = await fetch(`${API_BASE_URL}/api/public/vendors/apply`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error ${res.status}`);
  }
  return res.json();
};

export interface VendorApplicationSummary {
  id: string;
  reference_code: string;
  legal_company_name: string;
  trade_name?: string | null;
  business_type: string;
  order_email: string;
  email_verified: boolean;
  city: string;
  province: string;
  status: "pending" | "approved" | "rejected" | "needs_info";
  submitted_at: string;
  reviewed_at: string | null;
}

export const listVendorApplications = (params?: {
  status?: string;
  search?: string;
  limit?: number;
  offset?: number;
}) => {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.search) q.set("search", params.search);
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.offset) q.set("offset", String(params.offset));
  return apiFetch<{ applications: VendorApplicationSummary[]; counts: Record<string, number> }>(
    `/api/vendor-applications?${q.toString()}`
  );
};

export interface VendorApplicationDocument {
  id: string;
  doc_type: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface VendorApplicationItem {
  id: string;
  name: string;
  sku: string | null;
  category: string | null;
  description: string | null;
  unit: string;
  unit_price: number;
  moq: number | null;
  lead_time_days: number | null;
  row_source: string;
}

export interface VendorApplicationDetail extends VendorApplicationSummary {
  ntn: string;
  strn: string | null;
  secp_number: string | null;
  year_established: number | null;
  employee_range: string | null;
  website: string | null;
  categories: string[];
  contact_name: string;
  contact_designation: string | null;
  mobile: string;
  alternate_phone: string | null;
  address: string;
  postal_code: string | null;
  coverage_provinces: string[];
  coverage_cities: string[];
  lead_time_days: number | null;
  payment_terms: string | null;
  min_order_value: number | null;
  warranty: string | null;
  bank_name: string | null;
  bank_account_title: string | null;
  bank_iban: string | null;
  certifications: string[];
  rejection_reason: string | null;
  admin_notes: string | null;
  vetting_checklist: Record<string, boolean>;
  approved_vendor_id: string | null;
  items: VendorApplicationItem[];
  documents: VendorApplicationDocument[];
}

export const getVendorApplication = (id: string) =>
  apiFetch<VendorApplicationDetail>(`/api/vendor-applications/${id}`);

export const getVendorApplicationDocumentUrl = (applicationId: string, documentId: string) =>
  `${API_BASE_URL}/api/vendor-applications/${applicationId}/documents/${documentId}`;

export const updateVendorApplicationChecklist = (id: string, checklist: Record<string, boolean>) =>
  apiFetch<{ message: string }>(`/api/vendor-applications/${id}/checklist`, {
    method: "POST",
    body: JSON.stringify({ checklist }),
  });

export const approveVendorApplication = (id: string) =>
  apiFetch<{ message: string; vendor_id: string }>(`/api/vendor-applications/${id}/approve`, {
    method: "POST",
  });

export const rejectVendorApplication = (id: string, reason: string) =>
  apiFetch<{ message: string }>(`/api/vendor-applications/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const requestVendorApplicationInfo = (id: string, note: string) =>
  apiFetch<{ message: string }>(`/api/vendor-applications/${id}/request-info`, {
    method: "POST",
    body: JSON.stringify({ note }),
  });

export interface Vendor {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  order_email: string;
  status: "active" | "suspended";
  trade_name: string | null;
  business_type: string | null;
  city: string | null;
  province: string | null;
  categories: string[];
  lead_time_days: number | null;
  payment_terms: string | null;
  min_order_value: number | null;
  warranty: string | null;
  certifications: string[];
  item_count: number;
}

export interface VendorItem {
  id: string;
  vendor_id: string;
  name: string;
  sku: string | null;
  category: string | null;
  description: string | null;
  unit: string;
  unit_price: number;
  moq: number | null;
  lead_time_days: number | null;
  is_active: boolean;
}

export const listVendors = (params?: { search?: string; category?: string }) => {
  const q = new URLSearchParams();
  if (params?.search) q.set("search", params.search);
  if (params?.category) q.set("category", params.category);
  return apiFetch<{ vendors: Vendor[] }>(`/api/vendors?${q.toString()}`);
};

export const getVendor = (id: string) => apiFetch<Vendor>(`/api/vendors/${id}`);

export const getVendorItems = (id: string) =>
  apiFetch<{ items: VendorItem[] }>(`/api/vendors/${id}/items`);

// ═══════════════════════════════════════════════════════════════════════════════
// VENDOR ORDERS — order -> vendor accept (n8n) -> smart contract -> shipment
// -> orderer approval/dispute -> execution (Phase 2). "Receiver" = the
// orderer who placed the order; there is no separate receiver.
// ═══════════════════════════════════════════════════════════════════════════════

export interface VendorOrderItemInput {
  vendor_item_id: string;
  quantity: number;
}

export interface PlaceVendorOrderPayload {
  vendor_id: string;
  items: VendorOrderItemInput[];
  destination_name: string;
  destination_city?: string;
  destination_address?: string;
  requested_delivery_date?: string;
}

export const placeVendorOrder = (payload: PlaceVendorOrderPayload) =>
  apiFetch<{
    order_id: string; order_code: string; status: string; vendor_email_status: string; message: string;
    subtotal: number; platform_fee: number; total_amount: number; vendor_payout_amount: number;
  }>(
    "/api/vendor-orders",
    { method: "POST", body: JSON.stringify(payload) }
  );

export const resendVendorOrderRequest = (orderId: string) =>
  apiFetch<{ message: string; vendor_email_status: string }>(`/api/vendor-orders/${orderId}/resend-vendor-request`, { method: "POST" });

export const cancelVendorOrder = (orderId: string) =>
  apiFetch<{ message: string }>(`/api/vendor-orders/${orderId}/cancel`, { method: "POST" });

/** Admin-only: cancel an accepted, not-yet-arrived contract on-chain and release the payment hold. */
export const cancelVendorContract = (orderId: string, reason: string) =>
  apiFetch<{ message: string }>(`/api/vendor-orders/${orderId}/cancel-contract`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

// --- Public, no-login vendor pages ------------------------------------------

export interface PublicVendorOrderItem {
  name: string;
  unit: string;
  quantity: number;
  unit_price: number;
  line_total: number;
}

export interface PublicVendorOrderSummary {
  order_code: string;
  vendor_name: string;
  destination_name: string;
  destination_city: string | null;
  requested_delivery_date: string | null;
  status: string;
  subtotal: number;
  total_amount: number;
  platform_fee: number;
  vendor_payout_amount: number;
  currency: string;
  expires_at: string;
  already_responded: boolean;
  items: PublicVendorOrderItem[];
}

export const getPublicVendorOrder = (orderId: string, token: string) =>
  apiFetch<PublicVendorOrderSummary>(`/api/public/vendor-orders/${orderId}?token=${encodeURIComponent(token)}`);

export const respondVendorOrder = (orderId: string, token: string, decision: "accept" | "reject", reason?: string) =>
  apiFetch<{ message: string }>("/api/public/vendor-orders/respond", {
    method: "POST",
    body: JSON.stringify({ order_id: orderId, token, decision, reason }),
  });

export interface PublicShipment {
  status: string;
  carrier: string | null;
  tracking_no: string | null;
  dispatch_date: string | null;
  eta: string | null;
}

export const getPublicShipment = (orderId: string, token: string) =>
  apiFetch<{ order_code: string; vendor_name: string; contract_status: string; shipment: PublicShipment | null }>(
    `/api/public/vendor-orders/${orderId}/shipment?token=${encodeURIComponent(token)}`
  );

export interface ShipmentUpdateInput {
  order_id: string;
  token: string;
  action: "dispatch" | "checkpoint";
  carrier?: string;
  tracking_no?: string;
  eta?: string;
  dispatch_date?: string;
  status?: "InTransit" | "OutForDelivery";
  location?: string;
  note?: string;
}

export const submitVendorShipmentUpdate = (payload: ShipmentUpdateInput) =>
  apiFetch<{ message: string; chain: Record<string, unknown> }>("/api/public/vendor-orders/shipment-update", {
    method: "POST",
    body: JSON.stringify(payload),
  });

// --- Staff: checkpoints, chain status ---------------------------------------

export interface StaffShipmentUpdateInput {
  action: "dispatch" | "checkpoint";
  carrier?: string;
  tracking_no?: string;
  eta?: string;
  dispatch_date?: string;
  status?: "InTransit" | "OutForDelivery";
  location?: string;
  note?: string;
}

export const staffShipmentCheckpoint = (orderId: string, payload: StaffShipmentUpdateInput) =>
  apiFetch<{ message: string; chain: Record<string, unknown> }>(`/api/shipments/${orderId}/checkpoints`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export interface ChainStatus {
  rpc_configured: boolean;
  configured: boolean;
  connected: boolean;
  network: string;
  contract_address: string | null;
}

export const getChainStatus = () => apiFetch<ChainStatus>("/api/chain/status");

// --- Orderer-only: confirm arrival, approve receipt, dispute ----------------

export const confirmArrival = (orderId: string) =>
  apiFetch<{ message: string; chain: Record<string, unknown> }>(`/api/shipments/${orderId}/confirm-arrival`, { method: "POST" });

export const approveReceipt = (orderId: string) =>
  apiFetch<{ message: string; chain: Record<string, unknown> }>(`/api/shipments/${orderId}/approve-receipt`, { method: "POST" });

export const raiseDispute = (orderId: string, reason: string) =>
  apiFetch<{ message: string; chain: Record<string, unknown> }>(`/api/shipments/${orderId}/dispute`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const resolveDispute = (orderId: string, resolution: "Arrived" | "Cancelled" | "Executed", notes?: string) =>
  apiFetch<{ message: string; chain: Record<string, unknown> }>(`/api/shipments/${orderId}/resolve-dispute`, {
    method: "POST",
    body: JSON.stringify({ resolution, notes }),
  });

// --- Order Tracking ----------------------------------------------------------

export interface TrackingOrderRow {
  id: string;
  order_code: string;
  vendor_id: string;
  vendor_name: string;
  orderer_user_id: string;
  destination_name: string;
  destination_city: string | null;
  status: "PENDING_VENDOR" | "ACCEPTED" | "REJECTED" | "EXPIRED" | "CANCELLED";
  contract_status: string;
  payment_status: PaymentStatus;
  subtotal: number;
  platform_fee: number;
  total_amount: number;
  vendor_payout_amount: number | null;
  currency: string;
  payout_status: PayoutStatus;
  payout_due_at: string | null;
  payout_paid_at: string | null;
  payout_ref: string | null;
  payment_ref: string | null;
  payment_authorized_at: string | null;
  payment_captured_at: string | null;
  expires_at: string;
  requested_delivery_date: string | null;
  shipment_status: string | null;
  carrier: string | null;
  tracking_no: string | null;
  eta: string | null;
  action_needed: "confirm_arrival" | "approve_or_dispute" | null;
  delayed: boolean;
  created_at: string;
  updated_at: string;
}

export const listTracking = (params?: { scope?: "mine" | "all"; status?: string; vendor_id?: string; search?: string; limit?: number; offset?: number }) => {
  const q = new URLSearchParams();
  if (params?.scope) q.set("scope", params.scope);
  if (params?.status) q.set("status", params.status);
  if (params?.vendor_id) q.set("vendor_id", params.vendor_id);
  if (params?.search) q.set("search", params.search);
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.offset) q.set("offset", String(params.offset));
  return apiFetch<{ orders: TrackingOrderRow[] }>(`/api/tracking?${q.toString()}`);
};

export interface TrackingSummary {
  awaiting_vendor: number;
  in_progress: number;
  action_needed: number;
  delayed: number;
  completed: number;
  rejected_expired_disputed: number;
}

export const getTrackingSummary = (scope: "mine" | "all" = "mine") =>
  apiFetch<TrackingSummary>(`/api/tracking/summary?scope=${scope}`);

export interface ShipmentEvent {
  id: string;
  order_id: string;
  status: string;
  location: string | null;
  note: string | null;
  actor_type: "vendor_link" | "staff" | "receiver" | "system";
  actor_user_id: string | null;
  actor_label: string | null;
  tx_hash: string | null;
  block_number: number | null;
  chain_confirmed_at: string | null;
  created_at: string;
}

export interface TrackingOrderItem {
  id: string;
  name: string;
  sku: string | null;
  unit: string;
  quantity: number;
  unit_price: number;
  line_total: number;
}

export interface TrackingDetail {
  order: TrackingOrderRow & {
    vendor_email: string;
    orderer_name: string;
    orderer_email: string;
    chain_order_id: string | null;
    chain_network: string | null;
    dispute_reason: string | null;
    dispute_resolution: string | null;
    is_orderer: boolean;
  };
  items: TrackingOrderItem[];
  shipment: PublicShipment | null;
  events: ShipmentEvent[];
  chain_live_state: Record<string, unknown> | null;
  chain_txs: ChainTx[];
  payment_transactions: PaymentTransaction[];
  payment_config: { platform_fee_rate: number; payout_settlement_hours: number };
}

export interface ChainTx {
  id: string;
  action: string;
  status: "pending" | "confirmed" | "failed";
  attempts: number;
  last_error: string | null;
  tx_hash: string | null;
  block_number: number | null;
  created_at: string;
  updated_at: string;
}

export const getTrackingDetail = (orderId: string) => apiFetch<TrackingDetail>(`/api/tracking/${orderId}`);

export const downloadTrackingInvoicePdf = async (orderId: string, filenameHint?: string) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("nexus_token") : null;
  const res = await fetch(`${API_BASE_URL}/api/tracking/${orderId}/invoice/pdf`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new Error(`Failed to generate invoice PDF (${res.status})`);
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameHint ? `${filenameHint}.pdf` : `invoice-${orderId}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};

// ═══════════════════════════════════════════════════════════════════════════════
// PAYMENTS (PKR only) — payment methods, ledger, escrow -> capture -> payout
// ═══════════════════════════════════════════════════════════════════════════════
export type PaymentStatus = "Not Required" | "Payment Required" | "Authorized" | "Captured" | "Cancelled" | "Failed";
export type PayoutStatus = "Not Scheduled" | "Scheduled" | "Awaiting Transfer" | "Paid" | "Failed" | "Not Applicable";
export type PaymentMethodType = "bank_transfer" | "raast" | "jazzcash" | "easypaisa";

export interface PaymentsConfig {
  currency: "PKR";
  platform_fee_rate: number;
  payout_settlement_hours: number;
  method_types: { value: PaymentMethodType; label: string }[];
  has_default_method: boolean;
  /** mock = simulated; manual = admin makes the Raast/IBFT transfer and records its bank reference */
  provider: "mock" | "manual";
  provider_label: string;
  automatic_payouts: boolean;
  /** Per-order ceiling in PKR, or null for no cap */
  max_order_total: number | null;
}

export interface PaymentMethod {
  id: string;
  method_type: PaymentMethodType;
  method_type_label: string;
  label: string;
  account_title: string;
  bank_name: string | null;
  account_identifier: string; // masked
  currency: "PKR";
  is_default: boolean;
  created_at: string;
}

export interface PaymentMethodInput {
  method_type: PaymentMethodType;
  label: string;
  account_title: string;
  bank_name?: string;
  account_identifier: string;
  is_default?: boolean;
}

export interface PaymentsSummary {
  held_in_escrow: number;
  held_count: number;
  awaiting_method: number;
  awaiting_method_count: number;
  payouts_pending: number;
  payouts_pending_count: number;
  awaiting_transfer_count: number;
  paid_out: number;
  paid_out_count: number;
  fees_collected: number;
  failed_count: number;
  currency: "PKR";
}

export interface PaymentLedgerRow {
  id: string;
  order_code: string;
  status: string;
  contract_status: string;
  chain_order_id: string | null;
  chain_network: string | null;
  payment_status: PaymentStatus;
  payment_ref: string | null;
  payout_status: PayoutStatus;
  payout_ref: string | null;
  subtotal: number;
  platform_fee: number;
  total_amount: number;
  vendor_payout_amount: number | null;
  currency: "PKR";
  payment_authorized_at: string | null;
  payment_captured_at: string | null;
  payout_due_at: string | null;
  payout_paid_at: string | null;
  created_at: string;
  updated_at: string;
  vendor_name: string;
  vendor_bank_name: string | null;
  vendor_bank_iban: string | null; // masked
  vendor_payment_terms: string | null;
  orderer_name: string;
  payment_method_label: string | null;
  chain_pending: number;
  chain_confirmed: number;
}

export interface PaymentTransaction {
  id: string;
  kind: "authorize" | "capture" | "cancel" | "payout";
  amount: number;
  currency: "PKR";
  status: "Succeeded" | "Failed" | "Skipped";
  provider_ref: string | null;
  note: string | null;
  created_at: string;
  payment_method_label?: string | null;
  actor_name?: string | null;
}

export const getPaymentsConfig = () => apiFetch<PaymentsConfig>("/api/payments/config");

export const listPaymentMethods = () => apiFetch<{ methods: PaymentMethod[] }>("/api/payments/methods");

export const createPaymentMethod = (payload: PaymentMethodInput) =>
  apiFetch<{ id: string; message: string }>("/api/payments/methods", { method: "POST", body: JSON.stringify(payload) });

export const setDefaultPaymentMethod = (id: string) =>
  apiFetch<{ message: string }>(`/api/payments/methods/${id}/default`, { method: "POST" });

export const removePaymentMethod = (id: string) =>
  apiFetch<{ message: string }>(`/api/payments/methods/${id}`, { method: "DELETE" });

export const getPaymentsSummary = () => apiFetch<PaymentsSummary>("/api/payments/summary");

export const getPaymentsLedger = (params?: { payment_status?: string; payout_status?: string; search?: string }) => {
  const q = new URLSearchParams();
  if (params?.payment_status) q.set("payment_status", params.payment_status);
  if (params?.payout_status) q.set("payout_status", params.payout_status);
  if (params?.search) q.set("search", params.search);
  return apiFetch<{ orders: PaymentLedgerRow[] }>(`/api/payments/ledger?${q.toString()}`);
};

export const getOrderPaymentTransactions = (orderId: string) =>
  apiFetch<{ transactions: PaymentTransaction[] }>(`/api/payments/orders/${orderId}/transactions`);

export const authorizeOrderPayment = (orderId: string) =>
  apiFetch<{ message: string }>(`/api/payments/orders/${orderId}/authorize`, { method: "POST" });

export const retryOrderCapture = (orderId: string) =>
  apiFetch<{ message: string }>(`/api/payments/orders/${orderId}/capture`, { method: "POST" });

export const releaseVendorPayout = (orderId: string) =>
  apiFetch<{ message: string }>(`/api/payments/orders/${orderId}/release-payout`, { method: "POST" });

// --- Manual bank transfers (PAYMENT_PROVIDER=manual) -------------------------

export interface PendingTransfer {
  id: string;
  order_code: string;
  amount: number;
  subtotal: number;
  vendor_name: string;
  bank_name: string | null;
  bank_account_title: string | null;
  bank_iban: string | null; // full — admin-only endpoint
  transfer_reference: string;
  payment_captured_at: string | null;
  payout_due_at: string | null;
}

export const getPendingTransfers = () =>
  apiFetch<{ transfers: PendingTransfer[]; total: number }>("/api/payments/payouts/pending-transfers");

export const confirmManualPayout = (orderId: string, bankReference: string, note?: string) =>
  apiFetch<{ message: string }>(`/api/payments/orders/${orderId}/confirm-payout`, {
    method: "POST",
    body: JSON.stringify({ bank_reference: bankReference, note }),
  });

export const downloadPendingTransfersCsv = async () => {
  const token = typeof window !== "undefined" ? localStorage.getItem("nexus_token") : null;
  const res = await fetch(`${API_BASE_URL}/api/payments/payouts/pending-transfers.csv`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Failed to export transfers (${res.status})`);
  const url = window.URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `nexus-vendor-payouts-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};
