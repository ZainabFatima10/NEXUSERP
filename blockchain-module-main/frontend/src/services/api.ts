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
}

export const getNotifications = (params?: {
  user_id?: string;
  unread?: boolean;
  category?: string;
}) => {
  const q = new URLSearchParams();
  if (params?.user_id) q.set("user_id", params.user_id);
  if (params?.unread) q.set("unread", "true");
  if (params?.category) q.set("category", params.category);
  return apiFetch<{ unread_count: number; notifications: Notification[] }>(
    `/api/notifications?${q}`
  );
};

export const markNotificationRead = (id: string) =>
  apiFetch(`/api/notifications/${id}/read`, { method: "PATCH" });

export const markAllNotificationsRead = (userId?: string) => {
  const q = userId ? `?user_id=${userId}` : "";
  return apiFetch(`/api/notifications/mark-all-read${q}`, { method: "PATCH" });
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

export const getComplaints = (params?: { status?: string; category?: string; severity?: string; limit?: number }) => {
  const q = new URLSearchParams();
  if (params?.status) q.set("status", params.status);
  if (params?.category) q.set("category", params.category);
  if (params?.severity) q.set("severity", params.severity);
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
  apiFetch<{ ticket_code: string; ticket_id: string; classification: Record<string, unknown>; status: string; reply_text: string }>(
    "/api/complaints/chat",
    { method: "POST", body: JSON.stringify({ message, area }) }
  );

export const submitVoiceComplaint = async (audioBlob: Blob, area?: string) => {
  const token = typeof window !== "undefined" ? localStorage.getItem("nexus_token") : null;
  const form = new FormData();
  form.append("audio", audioBlob, "recording.webm");
  if (area) form.append("area", area);
  const res = await fetch(`${API_BASE_URL}/api/complaints/voice`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error ${res.status}`);
  }
  return res.json() as Promise<{
    ticket_code: string; ticket_id: string; transcript: string; transcription_engine: string;
    classification: Record<string, unknown>; status: string; reply_text: string;
    reply_audio_base64: string | null; reply_audio_available: boolean;
  }>;
};

export const getComplaintTaxonomy = () => apiFetch<Record<string, string[]>>("/api/complaints/taxonomy");

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
