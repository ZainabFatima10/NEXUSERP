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
  FileText, Download, Package, ShieldCheck, Mail, RefreshCw, Ban,
} from "lucide-react";
import {
  getTrackingDetail, confirmArrival, approveReceipt, raiseDispute, resolveDispute,
  resendVendorOrderRequest, cancelVendorOrder, staffShipmentCheckpoint, downloadTrackingInvoicePdf,
  subscribeToNotifications, TrackingDetail as TrackingDetailType,
} from "@/services/api";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/hooks/use-toast";

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
  const [staffLocation, setStaffLocation] = useState("");
  const [staffNote, setStaffNote] = useState("");
  const [staffStatus, setStaffStatus] = useState<"InTransit" | "OutForDelivery">("InTransit");

  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

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

  const { order, items, shipment, events, chain_live_state } = detail;
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

      <div className="grid lg:grid-cols-3 gap-4">
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
          <div className="border-t border-border pt-2 flex justify-between font-semibold">
            <span>Total</span><span className="font-mono text-primary">{order.currency} {order.total_amount.toLocaleString()}</span>
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
          <p className="text-xs pt-2 border-t border-border">
            Payment: <span className="font-medium">{order.payment_status === "Authorized" ? "Funds authorized — held until you approve receipt" : order.payment_status === "Captured" ? "Payment captured" : order.payment_status}</span>
          </p>
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
          <div className="flex gap-2">
            <button onClick={() => run(() => resendVendorOrderRequest(order.id))} disabled={acting} className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg border border-border hover:bg-muted/30 disabled:opacity-50">
              <Mail size={14} /> Resend Request
            </button>
            <button onClick={() => run(() => cancelVendorOrder(order.id))} disabled={acting} className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 rounded-lg bg-destructive/10 text-destructive hover:bg-destructive/20 disabled:opacity-50">
              <Ban size={14} /> Cancel Order
            </button>
          </div>
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
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-background rounded-xl p-6 max-w-md w-full space-y-4">
            <h3 className="font-heading font-bold text-lg">Approve Receipt?</h3>
            <p className="text-sm text-muted-foreground">
              This executes the smart contract and captures payment of {order.currency} {order.total_amount.toLocaleString()}.
            </p>
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
        </div>
      )}

      {/* Dispute modal */}
      {showDisputeModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-background rounded-xl p-6 max-w-md w-full space-y-4">
            <h3 className="font-heading font-bold text-lg">Raise Dispute</h3>
            <textarea value={disputeReason} onChange={(e) => setDisputeReason(e.target.value)} placeholder="What's wrong with this delivery?" rows={3} className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-muted/30" />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowDisputeModal(false)} className="px-4 py-2 text-sm rounded-lg border border-border">Cancel</button>
              <button
                onClick={async () => { setShowDisputeModal(false); await run(() => raiseDispute(order.id, disputeReason)); setDisputeReason(""); }}
                disabled={!disputeReason.trim()}
                className="px-4 py-2 text-sm rounded-lg bg-destructive text-white disabled:opacity-50"
              >
                Submit Dispute
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Resolve dispute modal (admin) */}
      {showResolveModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-background rounded-xl p-6 max-w-md w-full space-y-4">
            <h3 className="font-heading font-bold text-lg">Resolve Dispute</h3>
            <div className="flex flex-col gap-2">
              {(["Arrived", "Cancelled", "Executed"] as const).map((r) => (
                <button
                  key={r}
                  onClick={async () => { setShowResolveModal(false); await run(() => resolveDispute(order.id, r)); }}
                  className="text-sm font-medium px-4 py-2 rounded-lg border border-border hover:bg-muted/30 text-left"
                >
                  {r === "Arrived" ? "Back to Arrived (vendor to re-deliver/clarify)" : r === "Cancelled" ? "Cancel order (release payment hold)" : "Force Executed (capture payment anyway)"}
                </button>
              ))}
            </div>
            <button onClick={() => setShowResolveModal(false)} className="text-sm text-muted-foreground">Close</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default TrackingDetail;
