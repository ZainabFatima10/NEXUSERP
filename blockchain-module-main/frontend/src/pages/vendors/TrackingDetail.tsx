// src/pages/vendors/TrackingDetail.tsx
// Shared across /admin/tracking/:orderId and /procurement/tracking/:orderId.
// Full order lifecycle: progress bar, shipment timeline with on-chain tx
// hashes, contract panel, and the orderer-only action panel (confirm
// arrival / approve & execute / dispute). Admins/PMs viewing someone
// else's order see everything but the action buttons are hidden — the
// backend also rejects the calls, this isn't just a UI nicety.
import { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import {
  Loader2, CheckCircle2, XCircle, Clock, AlertTriangle, Truck, MapPin,
  FileText, Download, Package, ShieldCheck, Mail, RefreshCw, Ban, Wallet, Link2,
} from "lucide-react";
import {
  getTrackingDetail, confirmArrival, approveReceipt, raiseDispute, resolveDispute,
  resendVendorOrderRequest, cancelVendorOrder, cancelVendorContract, staffShipmentCheckpoint, downloadTrackingInvoicePdf,
  subscribeToNotifications, TrackingDetail as TrackingDetailType,
} from "@/services/api";
import { formatPKR } from "@/lib/currency";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/hooks/use-toast";
import FieldError from "@/components/FieldError";
import { validate, required, errorInputClass } from "@/lib/validation";

import ModalPortal from "@/components/ModalPortal";
const PROGRESS_STEPS = [
  { key: "PLACED", label: "Order Placed" },
  { key: "NOTIFIED", label: "Vendor Notified" },
  { key: "ACCEPTED", label: "Accepted (Contract Created)" },
  { key: "Preparing", label: "Preparing" },
  { key: "Dispatched", label: "Dispatched" },
  { key: "InTransit", label: "In Transit" },
  { key: "OutForDelivery", label: "Out for Delivery" },
  { key: "Arrived", label: "Arrived" },
  { key: "Approved", label: "Receipt Approved" },
  { key: "Executed", label: "Executed & Paid" },
];

function currentStepIndex(order: TrackingDetailType["order"]): number {
  if (order.status === "PENDING_VENDOR") return 1;
  if (order.status !== "ACCEPTED") return -1; // end state, rendered separately
  const idx = PROGRESS_STEPS.findIndex((s) => s.key === order.contract_status);
  return idx >= 0 ? idx : 2;
}

const EndStateBanner = ({ order }: { order: TrackingDetailType["order"] }) => {
  const map: Record<string, { label: string; cls: string; icon: typeof XCircle }> = {
    REJECTED: { label: "Vendor Rejected This Order", cls: "bg-destructive/10 text-destructive border-destructive/30", icon: XCircle },
    EXPIRED: { label: "Vendor Did Not Respond — Expired", cls: "bg-muted text-muted-foreground border-border", icon: Clock },
    CANCELLED: { label: "Order Cancelled", cls: "bg-muted text-muted-foreground border-border", icon: Ban },
  };
  let entry = map[order.status];
  if (!entry && order.contract_status === "Disputed") {
    entry = { label: "Disputed — Awaiting Admin Resolution", cls: "bg-warning/10 text-warning border-warning/30", icon: AlertTriangle };
  }
  if (!entry) return null;
  const Icon = entry.icon;
  return (
    <div className={`flex items-center gap-2 border rounded-xl px-4 py-3 ${entry.cls}`}>
      <Icon size={18} /> <span className="font-semibold">{entry.label}</span>
    </div>
  );
};

const ProgressBar = ({ order }: { order: TrackingDetailType["order"] }) => {
  const idx = currentStepIndex(order);
  if (idx < 0) return <EndStateBanner order={order} />;

  const pct = PROGRESS_STEPS.length > 1 ? (idx / (PROGRESS_STEPS.length - 1)) * 100 : 0;
  const currentLabel = PROGRESS_STEPS[idx]?.label ?? "";

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-foreground">{currentLabel}</span>
        <span className="text-xs text-muted-foreground">Step {idx + 1} of {PROGRESS_STEPS.length}</span>
      </div>

      <div className="relative">
        {/* Track + fill, laid out under the step dots so the line never
            crosses through them and stays perfectly centered. */}
        <div className="absolute top-4 left-0 right-0 h-1 rounded-full bg-muted/50" />
        <div
          className="absolute top-4 left-0 h-1 rounded-full bg-gradient-to-r from-success to-primary transition-all duration-500"
          style={{ width: `${pct}%` }}
        />

        <div className="relative flex items-start justify-between gap-1 overflow-x-auto scroll-thin pb-1">
          {PROGRESS_STEPS.map((s, i) => (
            <div key={s.key} className="flex flex-col items-center gap-2 flex-1 min-w-[64px]">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold ring-4 ring-background transition-colors ${
                  i < idx
                    ? "bg-success text-white"
                    : i === idx
                    ? "bg-primary text-white shadow-[0_0_0_4px_rgba(59,130,246,0.15)] animate-pulse"
                    : "bg-muted text-muted-foreground"
                }`}
              >
                {i < idx ? <CheckCircle2 size={15} /> : i + 1}
              </div>
              <span
                className={`text-[10px] text-center leading-tight ${
                  i === idx ? "text-foreground font-semibold" : i < idx ? "text-muted-foreground" : "text-muted-foreground/70"
                }`}
              >
                {s.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      {order.delayed && (
        <span className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded-full bg-warning/10 text-warning mt-3">
          <AlertTriangle size={12} /> Delayed — ETA has passed
        </span>
      )}
    </div>
  );
};

const ACTOR_LABELS: Record<string, string> = { vendor_link: "Vendor", staff: "Staff", receiver: "You", system: "System" };

const CHAIN_ACTION_LABELS: Record<string, string> = {
  create_contract: "Contract created", record_checkpoint: "Checkpoint", confirm_arrival: "Arrival confirmed",
  approve_receipt: "Receipt approved → executed", dispute: "Dispute opened", resolve_dispute: "Dispute resolved", cancel: "Contract cancelled",
};

/** Plain-language "where is the money and what happens next". */
function paymentNarrative(order: TrackingDetailType["order"], settlementHours: number): { headline: string; detail: string; tone: string } {
  const payout = formatPKR(order.vendor_payout_amount ?? order.subtotal);
  const when = settlementHours === 0 ? "immediately" : `${settlementHours}h`;
  if (order.status === "PENDING_VENDOR")
    return { headline: "Not charged yet", detail: "Funds are held only once the vendor accepts.", tone: "text-muted-foreground" };
  if (["REJECTED", "EXPIRED", "CANCELLED"].includes(order.status) || order.payment_status === "Cancelled")
    return { headline: "No payment", detail: "Nothing was captured — any hold has been released.", tone: "text-muted-foreground" };
  if (order.payment_status === "Payment Required")
    return { headline: "Waiting for a payment method", detail: "An admin must add a default payment method under Payments before receipt can be approved.", tone: "text-warning" };
  if (order.payment_status === "Failed")
    return { headline: "Payment failed", detail: "An admin can retry it from Payments.", tone: "text-destructive" };
  if (order.payment_status === "Authorized")
    return {
      headline: "Held in escrow",
      detail: order.contract_status === "Disputed"
        ? "Frozen while the dispute is open."
        : `Captured when you approve receipt after delivery; the vendor is then paid ${payout} ${when} later.`,
      tone: "text-primary",
    };
  if (order.payout_status === "Paid")
    return { headline: "Vendor paid", detail: `${payout} transferred ${order.payout_paid_at ? new Date(order.payout_paid_at).toLocaleString() : ""}${order.payout_ref ? ` · ref ${order.payout_ref}` : ""}`, tone: "text-success" };
  if (order.payout_status === "Awaiting Transfer")
    return { headline: "Captured — bank transfer to vendor in progress", detail: `An admin is sending ${payout} to the vendor by Raast/IBFT; it's marked paid once the bank reference is recorded.`, tone: "text-warning" };
  if (order.payout_status === "Failed")
    return { headline: "Captured — vendor payout failed", detail: "An admin can retry the payout from Payments.", tone: "text-destructive" };
  return {
    headline: "Captured — vendor payout scheduled",
    detail: `${payout} will be paid to the vendor ${order.payout_due_at ? `on ${new Date(order.payout_due_at).toLocaleString()}` : "shortly"}.`,
    tone: "text-warning",
  };
}

const TrackingDetail = () => {
  const { orderId } = useParams<{ orderId: string }>();
  const { user } = useAuth();
  const { toast } = useToast();

  const [detail, setDetail] = useState<TrackingDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [checklistConfirmed, setChecklistConfirmed] = useState(false);
  const [showDisputeModal, setShowDisputeModal] = useState(false);
  const [disputeReason, setDisputeReason] = useState("");
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [showResolveModal, setShowResolveModal] = useState(false);
  const [showStaffCheckpoint, setShowStaffCheckpoint] = useState(false);
  const [showCancelContract, setShowCancelContract] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [showCancelOrder, setShowCancelOrder] = useState(false);
  const [cancelOrderReason, setCancelOrderReason] = useState("");
  const [staffLocation, setStaffLocation] = useState("");
  const [staffNote, setStaffNote] = useState("");
  const [staffStatus, setStaffStatus] = useState<"InTransit" | "OutForDelivery">("InTransit");
  const [cancelReasonError, setCancelReasonError] = useState<string | null>(null);
  const [disputeReasonError, setDisputeReasonError] = useState<string | null>(null);

  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const vCancelReason = () => validate(cancelReason, required("A reason is required"));
  const vDisputeReason = () => validate(disputeReason, required("Please describe the issue"));

  const load = useCallback((silent = false) => {
    if (!orderId) return;
    if (!silent) setLoading(true);
    getTrackingDetail(orderId)
      .then((res) => { setDetail(res); setLastUpdated(new Date()); })
      .catch(() => { if (!silent) toast({ title: "Failed to load order", variant: "destructive" }); })
      .finally(() => { if (!silent) setLoading(false); });
  }, [orderId, toast]);

  useEffect(() => { load(); }, [load]);

  // Live updates: a status change made via the vendor link (or by anyone
  // else acting on this order) shows up here within seconds, no reload —
  // the same stream the topbar bell uses (SSE, with its own polling
  // fallback already handled inside subscribeToNotifications).
  useEffect(() => {
    if (!orderId) return;
    const unsubscribe = subscribeToNotifications((n) => {
      if (n.entity_type === "vendor_order" && n.entity_id === orderId) {
        load(true);
      }
    });
    return unsubscribe;
  }, [orderId, load]);

  if (loading || !detail) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-primary" size={36} /></div>;
  }

  const { order, items, shipment, events, chain_live_state, chain_txs = [], payment_config } = detail;
  const settlementHours = payment_config?.payout_settlement_hours ?? 24;
  const narrative = paymentNarrative(order, settlementHours);
  const IN_FLIGHT = ["Preparing", "Dispatched", "InTransit", "OutForDelivery"];
  const isOrderer = order.is_orderer;
  const isAdmin = user?.role === "admin";

  const run = async (fn: () => Promise<{ message: string }>) => {
    setActing(true);
    try {
      const res = await fn();
      toast({ title: res.message });
      load();
    } catch (e: unknown) {
      toast({ title: e instanceof Error ? e.message : "Action failed", variant: "destructive" });
    } finally {
      setActing(false);
    }
  };

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-heading font-bold font-mono">{order.order_code}</h1>
          <p className="text-muted-foreground text-sm mt-1">{order.vendor_name} → {order.destination_name}</p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-[11px] text-muted-foreground">Last updated {lastUpdated.toLocaleTimeString()}</span>
          )}
          <button onClick={() => load()} className="flex items-center gap-1.5 text-xs font-medium px-3 py-2 border border-border rounded-lg hover:bg-muted/30">
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      <div className="glass-card p-6">
        <ProgressBar order={order} />
      </div>

      <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* Order card */}
        <div className="glass-card p-5 space-y-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase flex items-center gap-1"><Package size={13} /> Order</p>
          <div className="text-sm space-y-1">
            {items.map((i) => (
              <div key={i.id} className="flex justify-between">
                <span>{i.name} × {i.quantity} {i.unit}</span>
                <span className="font-mono">{i.line_total.toLocaleString()}</span>
              </div>
            ))}
          </div>
          <div className="border-t border-border pt-2 space-y-1 text-sm">
            <div className="flex justify-between text-muted-foreground"><span>Subtotal</span><span className="font-mono">{formatPKR(order.subtotal)}</span></div>
            <div className="flex justify-between text-muted-foreground">
              <span>Platform fee{payment_config ? ` (${(payment_config.platform_fee_rate * 100).toFixed(1)}%)` : ""}</span>
              <span className="font-mono">{formatPKR(order.platform_fee ?? 0)}</span>
            </div>
            <div className="flex justify-between font-semibold"><span>Total</span><span className="font-mono text-primary">{formatPKR(order.total_amount)}</span></div>
          </div>
          <p className="text-xs text-muted-foreground">Destination: {order.destination_name}{order.destination_city ? `, ${order.destination_city}` : ""}</p>
        </div>

        {/* Shipment card */}
        <div className="glass-card p-5 space-y-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase flex items-center gap-1"><Truck size={13} /> Shipment</p>
          {shipment ? (
            <div className="text-sm space-y-1 text-muted-foreground">
              <p>Carrier: {shipment.carrier || "—"}</p>
              <p>Tracking #: {shipment.tracking_no || "—"}</p>
              <p>Dispatch date: {shipment.dispatch_date || "—"}</p>
              <p>ETA: {shipment.eta || "—"}</p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Not yet created — vendor hasn't accepted.</p>
          )}
        </div>

        {/* Payment card */}
        <div className="glass-card p-5 space-y-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase flex items-center gap-1"><Wallet size={13} /> Payment</p>
          <div>
            <p className={`text-sm font-semibold ${narrative.tone}`}>{narrative.headline}</p>
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{narrative.detail}</p>
          </div>
          <div className="text-xs text-muted-foreground space-y-1 border-t border-border pt-2">
            <p className="flex justify-between"><span>Escrow</span><span className="font-medium text-foreground">{order.payment_status}</span></p>
            <p className="flex justify-between"><span>Vendor payout</span><span className="font-mono">{formatPKR(order.vendor_payout_amount ?? order.subtotal)}</span></p>
            <p className="flex justify-between"><span>Payout status</span><span className="font-medium text-foreground">{order.payout_status}</span></p>
          </div>
        </div>

        {/* Contract panel */}
        <div className="glass-card p-5 space-y-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase flex items-center gap-1"><ShieldCheck size={13} /> Smart Contract</p>
          {order.chain_order_id ? (
            <div className="text-sm space-y-1 text-muted-foreground">
              <p>Status: <span className="font-medium text-foreground">{order.contract_status}</span></p>
              <p className="font-mono text-xs break-all">Order hash: {order.chain_order_id}</p>
              <p className="text-xs">Network: {order.chain_network || "—"}</p>
              {chain_live_state && (
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-success/10 text-success">
                  <CheckCircle2 size={10} /> Verified on-chain
                </span>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Created once the vendor accepts.</p>
          )}
          {chain_txs.length > 0 && (
            <div className="border-t border-border pt-2 space-y-1">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase flex items-center gap-1"><Link2 size={11} /> On-chain transactions</p>
              {chain_txs.map((t) => (
                <div key={t.id} className="flex items-center gap-2 text-[11px]">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${t.status === "confirmed" ? "bg-success" : t.status === "pending" ? "bg-warning" : "bg-destructive"}`} />
                  <span className="flex-1 truncate">{CHAIN_ACTION_LABELS[t.action] || t.action}</span>
                  <span className={t.status === "confirmed" ? "text-success" : "text-warning"} title={t.last_error || undefined}>
                    {t.status === "confirmed" ? `block ${t.block_number}` : `pending (${t.attempts} tries)`}
                  </span>
                </div>
              ))}
            </div>
          )}
          {order.contract_status === "Executed" && (
            <button
              onClick={() => downloadTrackingInvoicePdf(order.id, order.order_code)}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg bg-muted/40 hover:bg-muted/60"
            >
              <Download size={13} /> Download Invoice
            </button>
          )}
        </div>
      </div>

      {/* Action panel — orderer only */}
      {isOrderer && order.status === "PENDING_VENDOR" && (
        <div className="glass-card p-5 space-y-3">
          <p className="text-sm text-muted-foreground">
            Waiting for {order.vendor_name} to respond (expires {new Date(order.expires_at).toLocaleString()}).
          </p>
          {!showCancelOrder ? (
            <div className="flex gap-2">
              <button onClick={() => run(() => resendVendorOrderRequest(order.id))} disabled={acting} className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg border border-border hover:bg-muted/30 disabled:opacity-50">
                <Mail size={14} /> Resend Request
              </button>
              <button onClick={() => setShowCancelOrder(true)} disabled={acting} className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg bg-destructive/10 text-destructive hover:bg-destructive/20 disabled:opacity-50">
                <Ban size={14} /> Cancel Order
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                {order.vendor_name} will be emailed that this order is cancelled, with your reason.
              </p>
              <textarea value={cancelOrderReason} onChange={(e) => setCancelOrderReason(e.target.value)} rows={3} placeholder="Reason for cancellation (required, sent to the vendor)" className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-muted/30" />
              <div className="flex gap-2 justify-end">
                <button onClick={() => { setShowCancelOrder(false); setCancelOrderReason(""); }} className="text-sm px-4 py-2 rounded-lg border border-border">Back</button>
                <button
                  onClick={async () => { await run(() => cancelVendorOrder(order.id, cancelOrderReason.trim())); setShowCancelOrder(false); setCancelOrderReason(""); }}
                  disabled={acting || !cancelOrderReason.trim()}
                  className="flex items-center gap-1.5 text-sm font-semibold px-4 py-2 rounded-lg bg-destructive text-white disabled:opacity-50"
                >
                  <Ban size={14} /> Cancel order &amp; notify vendor
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {isOrderer && order.status === "ACCEPTED" && (order.contract_status === "OutForDelivery" || order.contract_status === "InTransit") && (
        <div className="glass-card p-5">
          <p className="text-sm text-muted-foreground mb-3">Shipment arrived?</p>
          <button onClick={() => run(() => confirmArrival(order.id))} disabled={acting} className="flex items-center gap-1.5 text-sm font-semibold px-5 py-2.5 rounded-lg bg-primary text-white hover:opacity-90 disabled:opacity-50">
            {acting && <Loader2 size={14} className="animate-spin" />} Confirm Arrival
          </button>
        </div>
      )}

      {isOrderer && order.status === "ACCEPTED" && order.contract_status === "Arrived" && (
        <div className="glass-card p-5 space-y-3">
          <p className="text-sm text-muted-foreground">Inspect the delivery, then approve receipt or raise a dispute.</p>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={checklistConfirmed} onChange={(e) => setChecklistConfirmed(e.target.checked)} />
            I have verified items and quantities against this order
          </label>
          <div className="flex gap-2">
            <button
              onClick={() => setShowApproveModal(true)}
              disabled={!checklistConfirmed}
              className="flex items-center gap-1.5 text-sm font-semibold px-5 py-2.5 rounded-lg bg-success text-white hover:opacity-90 disabled:opacity-40"
            >
              <CheckCircle2 size={15} /> Approve Receipt & Execute Contract
            </button>
            <button onClick={() => setShowDisputeModal(true)} className="flex items-center gap-1.5 text-sm font-semibold px-5 py-2.5 rounded-lg bg-destructive/10 text-destructive hover:bg-destructive/20">
              <AlertTriangle size={15} /> Raise Dispute
            </button>
          </div>
        </div>
      )}

      {isAdmin && order.status === "ACCEPTED" && IN_FLIGHT.includes(order.contract_status) && (
        <div className="glass-card p-5 space-y-3">
          {!showCancelContract ? (
            <button onClick={() => setShowCancelContract(true)} className="text-sm font-medium text-destructive flex items-center gap-1.5">
              <Ban size={14} /> Cancel this contract (admin) — releases the payment hold
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Cancels the escrow contract on-chain and releases the held funds. Only possible before arrival.</p>
              <input
                value={cancelReason}
                onChange={(e) => setCancelReason(e.target.value)}
                onBlur={() => setCancelReasonError(vCancelReason())}
                placeholder="Reason (required)"
                className={`w-full px-3 py-2 text-sm rounded-lg border bg-muted/30 ${cancelReasonError ? errorInputClass : "border-border"}`}
              />
              <FieldError message={cancelReasonError} />
              <div className="flex gap-2">
                <button onClick={() => { setShowCancelContract(false); setCancelReason(""); setCancelReasonError(null); }} className="text-sm px-4 py-2 rounded-lg border border-border">Back</button>
                <button
                  onClick={async () => {
                    const err = vCancelReason();
                    setCancelReasonError(err);
                    if (err) return;
                    await run(() => cancelVendorContract(order.id, cancelReason)); setShowCancelContract(false); setCancelReason("");
                  }}
                  disabled={acting || !cancelReason.trim()}
                  className="text-sm font-medium px-4 py-2 rounded-lg bg-destructive text-white disabled:opacity-50"
                >
                  Cancel contract
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {order.cancellation_reason && (order.status === "CANCELLED" || order.contract_status === "Cancelled") && (
        <div className="glass-card p-5">
          <p className="text-sm font-medium text-destructive">Cancelled: {order.cancellation_reason}</p>
          <p className="text-xs text-muted-foreground mt-1">This reason was emailed to {order.vendor_name}.</p>
        </div>
      )}

      {isAdmin && order.contract_status === "Disputed" && (
        <div className="glass-card p-5 space-y-2">
          <p className="text-sm text-warning font-medium">Dispute: {order.dispute_reason}</p>
          <button onClick={() => setShowResolveModal(true)} className="text-sm font-medium px-4 py-2 rounded-lg bg-primary text-white">Resolve Dispute</button>
        </div>
      )}

      {/* Staff checkpoint entry */}
      {!isOrderer && order.status === "ACCEPTED" && ["Preparing", "Dispatched", "InTransit", "OutForDelivery"].includes(order.contract_status) && (
        <div className="glass-card p-5 space-y-3">
          <button onClick={() => setShowStaffCheckpoint((s) => !s)} className="text-sm font-medium text-primary">
            {showStaffCheckpoint ? "Hide" : "Post a checkpoint manually (e.g. after a call with the carrier)"}
          </button>
          {showStaffCheckpoint && (
            <div className="space-y-2">
              <div className="flex gap-2">
                <button onClick={() => setStaffStatus("InTransit")} className={`flex-1 py-2 text-sm rounded-lg ${staffStatus === "InTransit" ? "bg-primary/10 text-primary" : "bg-muted/40"}`}>In Transit</button>
                <button onClick={() => setStaffStatus("OutForDelivery")} className={`flex-1 py-2 text-sm rounded-lg ${staffStatus === "OutForDelivery" ? "bg-primary/10 text-primary" : "bg-muted/40"}`}>Out for Delivery</button>
              </div>
              <input value={staffLocation} onChange={(e) => setStaffLocation(e.target.value)} placeholder="Location" className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-muted/30" />
              <input value={staffNote} onChange={(e) => setStaffNote(e.target.value)} placeholder="Note" className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-muted/30" />
              <button
                onClick={() => run(() => staffShipmentCheckpoint(order.id, { action: "checkpoint", status: staffStatus, location: staffLocation, note: staffNote }))}
                disabled={acting}
                className="text-sm font-medium px-4 py-2 rounded-lg bg-primary text-white disabled:opacity-50"
              >
                Post Checkpoint
              </button>
            </div>
          )}
        </div>
      )}

      {/* Timeline */}
      <div className="glass-card p-5">
        <p className="text-xs font-semibold text-muted-foreground uppercase mb-3 flex items-center gap-1"><FileText size={13} /> Shipment Timeline</p>
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground">No events yet.</p>
        ) : (
          <div className="space-y-3">
            {events.map((e) => (
              <div key={e.id} className="flex items-start gap-3 text-sm border-l-2 border-border pl-3">
                <div className="flex-1">
                  <p className="font-medium">{e.status} <span className="text-xs text-muted-foreground">— {ACTOR_LABELS[e.actor_type]}{e.actor_label ? ` (${e.actor_label})` : ""}</span></p>
                  {e.location && <p className="text-xs text-muted-foreground flex items-center gap-1"><MapPin size={10} /> {e.location}</p>}
                  {e.note && <p className="text-xs text-muted-foreground">{e.note}</p>}
                  <p className="text-xs text-muted-foreground">{new Date(e.created_at).toLocaleString()}</p>
                  {e.tx_hash && <p className="text-[11px] font-mono text-primary break-all">tx: {e.tx_hash}</p>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Approve confirmation modal */}
      {showApproveModal && (
        <ModalPortal><div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-background rounded-xl p-6 max-w-md w-full space-y-4">
            <h3 className="font-heading font-bold text-lg">Approve Receipt?</h3>
            <p className="text-sm text-muted-foreground">
              This executes the smart contract on-chain and captures the {formatPKR(order.total_amount)} held in escrow.
              The vendor is then paid {formatPKR(order.vendor_payout_amount ?? order.subtotal)}{" "}
              {settlementHours === 0 ? "immediately" : `${settlementHours} hours later`}. This can't be undone.
            </p>
            {order.payment_status !== "Authorized" && (
              <p className="text-sm text-warning">Funds aren't held for this order yet — approval will fail until an admin sets a default payment method.</p>
            )}
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowApproveModal(false)} className="px-4 py-2 text-sm rounded-lg border border-border">Cancel</button>
              <button
                onClick={async () => { setShowApproveModal(false); await run(() => approveReceipt(order.id)); }}
                className="px-4 py-2 text-sm rounded-lg bg-success text-white"
              >
                Confirm
              </button>
            </div>
          </div>
        </div></ModalPortal>
      )}

      {/* Dispute modal */}
      {showDisputeModal && (
        <ModalPortal><div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-background rounded-xl p-6 max-w-md w-full space-y-4">
            <h3 className="font-heading font-bold text-lg">Raise Dispute</h3>
            <textarea
              value={disputeReason}
              onChange={(e) => setDisputeReason(e.target.value)}
              onBlur={() => setDisputeReasonError(vDisputeReason())}
              placeholder="What's wrong with this delivery? (sent to the vendor)"
              rows={3}
              className={`w-full px-3 py-2 text-sm rounded-lg border bg-muted/30 ${disputeReasonError ? errorInputClass : "border-border"}`}
            />
            <FieldError message={disputeReasonError} />
            <div className="flex gap-2 justify-end">
              <button onClick={() => { setShowDisputeModal(false); setDisputeReasonError(null); }} className="px-4 py-2 text-sm rounded-lg border border-border">Cancel</button>
              <button
                onClick={async () => {
                  const err = vDisputeReason();
                  setDisputeReasonError(err);
                  if (err) return;
                  setShowDisputeModal(false); await run(() => raiseDispute(order.id, disputeReason)); setDisputeReason("");
                }}
                disabled={!disputeReason.trim()}
                className="px-4 py-2 text-sm rounded-lg bg-destructive text-white disabled:opacity-50"
              >
                Submit Dispute
              </button>
            </div>
          </div>
        </div></ModalPortal>
      )}

      {/* Resolve dispute modal (admin) */}
      {showResolveModal && (
        <ModalPortal><div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-background rounded-xl p-6 max-w-md w-full space-y-4">
            <h3 className="font-heading font-bold text-lg">Resolve Dispute</h3>
            <div className="flex flex-col gap-2">
              {(["Arrived", "Cancelled", "Executed"] as const).map((r) => (
                <button
                  key={r}
                  onClick={async () => { setShowResolveModal(false); await run(() => resolveDispute(order.id, r)); }}
                  className="text-sm font-medium px-4 py-2 rounded-lg border border-border hover:bg-muted/30 text-left"
                >
                  {r === "Arrived" ? "Back to Arrived (vendor to re-deliver/clarify)" : r === "Cancelled" ? "Cancel order (release payment hold)" : "Execute (capture payment, schedule vendor payout)"}
                </button>
              ))}
            </div>
            <button onClick={() => setShowResolveModal(false)} className="text-sm text-muted-foreground">Close</button>
          </div>
        </div></ModalPortal>
      )}
    </div>
  );
};

export default TrackingDetail;
