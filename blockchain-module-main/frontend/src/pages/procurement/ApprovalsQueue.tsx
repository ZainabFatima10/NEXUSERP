// src/pages/procurement/ApprovalsQueue.tsx
// Shared by /admin/approvals and /procurement/approvals. Pending tab = the
// approve/reject queue. Approved / Rejected tabs = read-only history of
// auto-reorders already decided (orders with pm_approval_status set).
import { useEffect, useState, useCallback } from "react";
import { CheckCircle2, XCircle, Loader2, ShoppingCart, X, Clock, Pencil, type LucideIcon } from "lucide-react";
import {
  listPendingApprovals, listOrders, approveReorder, rejectReorder, editReorder, ProcurementOrder,
} from "@/services/api";
import { useAuth } from "@/contexts/AuthContext";
import { orderQuantityError } from "@/lib/validation";
import { useToast } from "@/hooks/use-toast";
import { formatPKR } from "@/lib/currency";

import ModalPortal from "@/components/ModalPortal";

type Tab = "pending" | "approved" | "rejected";

const triggerBadge = (o: ProcurementOrder) =>
  o.below_20pct_trigger || o.trigger_type === "VEMA-Triggered"
    ? { label: "Critical Stock Trigger", cls: "bg-destructive/10 text-destructive" }
    : o.trigger_type === "Auto-Generated (Demand > Stock)"
      ? { label: "Predicted Shortage", cls: "bg-amber-500/10 text-amber-600" }
      : { label: "Low Stock Trigger", cls: "bg-amber-500/10 text-amber-600" };

const fmtDate = (v?: string | null) => (v ? new Date(v).toLocaleString() : "—");
const todayStr = () => new Date().toISOString().slice(0, 10);

const otherQuotes = (o: ProcurementOrder) =>
  (o.vendor_selection?.candidates ?? []).filter((c) => c.vendor_id !== o.vendor_selection?.selected_vendor_id);

/** Header row shared by every card: code, trigger, lowest-price chip, extra chips. */
const CardHeader = ({ o, children }: { o: ProcurementOrder; children?: React.ReactNode }) => {
  const badge = triggerBadge(o);
  const others = otherQuotes(o);
  return (
    <div className="flex items-center gap-2 flex-wrap mb-1.5">
      <span className="text-xs font-mono text-muted-foreground">{o.order_code}</span>
      <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${badge.cls}`}>{badge.label}</span>
      {others.length > 0 && (
        <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600">
          Lowest price of {others.length + 1} vendors
        </span>
      )}
      {children}
    </div>
  );
};

const Detail = ({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) => (
  <div className="min-w-0">
    <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
    <p className={`text-sm text-foreground truncate ${mono ? "font-mono text-xs" : ""}`} title={typeof value === "string" ? value : undefined}>
      {value}
    </p>
  </div>
);

const HistoryCard = ({ o }: { o: ProcurementOrder }) => {
  const approved = o.pm_approval_status === "Approved";
  const others = otherQuotes(o);
  return (
    <div className="glass-card p-5">
      <CardHeader o={o}>
        <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${approved ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive"}`}>
          {approved ? "Approved" : "Rejected"}
        </span>
      </CardHeader>
      <p className="text-sm text-foreground font-medium mb-3">
        {o.item_name} — {o.quantity} {o.unit}
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-x-6 gap-y-3">
        <Detail label="Vendor" value={o.vendor_name} />
        <Detail label="Unit price" value={o.unit_price != null ? `${formatPKR(o.unit_price)} / ${o.unit}` : "—"} />
        <Detail label="Total" value={o.total_price != null ? formatPKR(o.total_price) : "—"} />
        <Detail label="Expected delivery" value={o.expected_delivery || "—"} />
        <Detail label={approved ? "Approved on" : "Rejected on"} value={fmtDate(o.pm_approved_at)} />
        <Detail label="Current stage" value={o.stage} />
        {approved && (
          <Detail
            label="Vendor response"
            value={o.vendor_decision ? `${o.vendor_decision} · ${fmtDate(o.vendor_responded_at)}` : "Awaiting vendor"}
          />
        )}
        <Detail label="Contract status" value={o.contract_status} />
        <Detail label="Created" value={fmtDate(o.created_at)} />
      </div>
      {!approved && (
        <p className="text-xs text-muted-foreground mt-3">
          <span className="font-medium text-foreground">Reason:</span> {o.pm_decision_notes || "No reason given"}
        </p>
      )}
      {others.length > 0 && (
        <p className="text-[11px] text-muted-foreground mt-2">
          Also quoted:{" "}
          {others.map((c) => `${c.vendor_name} ${c.unit_price != null ? formatPKR(c.unit_price) : "(no price)"}`).join(" · ")}
        </p>
      )}
      {o.contract_hash && (
        <p className="text-[10px] font-mono text-muted-foreground mt-2 truncate">Contract: {o.contract_hash}</p>
      )}
    </div>
  );
};

const ApprovalsQueue = () => {
  const { toast } = useToast();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState<Tab>("pending");
  const [editing, setEditing] = useState<ProcurementOrder | null>(null);
  const [editQty, setEditQty] = useState("");
  const [editDelivery, setEditDelivery] = useState("");
  const [orders, setOrders] = useState<ProcurementOrder[]>([]);
  const [history, setHistory] = useState<ProcurementOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<ProcurementOrder | null>(null);
  const [reason, setReason] = useState("");

  const loadHistory = useCallback(async () => {
    try {
      const res = await listOrders({ limit: 200 });
      setHistory(
        res.orders
          .filter((o) => o.pm_approval_status === "Approved" || o.pm_approval_status === "Rejected")
          .sort((a, b) => (b.pm_approved_at ?? b.updated_at).localeCompare(a.pm_approved_at ?? a.updated_at)),
      );
    } catch {
      toast({ title: "Failed to load approval history", variant: "destructive" });
    }
  }, [toast]);

  const load = useCallback(async () => {
    try {
      const res = await listPendingApprovals();
      setOrders(res.orders);
    } catch {
      toast({ title: "Failed to load pending approvals", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); loadHistory(); }, [load, loadHistory]);

  const handleApprove = async (order: ProcurementOrder) => {
    setBusyId(order.id);
    try {
      const res = await approveReorder(order.id);
      toast({ title: `✅ ${order.order_code} approved`, description: `Vendor email: ${res.vendor_email_status}` });
      setOrders((prev) => prev.filter((o) => o.id !== order.id));
      loadHistory();
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Approval failed" });
    } finally {
      setBusyId(null);
    }
  };

  const openEdit = (o: ProcurementOrder) => {
    setEditing(o);
    setEditQty(String(o.quantity));
    setEditDelivery(o.expected_delivery ? String(o.expected_delivery).slice(0, 10) : "");
  };

  const editQtyError = orderQuantityError(editQty);
  const editDateError = editDelivery && editDelivery < todayStr() ? "Expected delivery cannot be in the past" : null;
  const editUnchanged = !!editing &&
    Number(editQty) === Number(editing.quantity) &&
    editDelivery === (editing.expected_delivery ? String(editing.expected_delivery).slice(0, 10) : "");

  const handleSaveEdit = async () => {
    if (!editing || editQtyError || editDateError || editUnchanged) return;
    setBusyId(editing.id);
    try {
      const res = await editReorder(editing.id, {
        quantity: Number(editQty),
        expected_delivery: editDelivery || undefined,
      });
      toast({ title: `✏️ ${editing.order_code} updated`, description: "New smart contract issued with the edited terms." });
      setOrders((prev) => prev.map((o) => (o.id === editing.id ? { ...o, ...res.order } : o)));
      setEditing(null);
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Edit failed", variant: "destructive" });
    } finally {
      setBusyId(null);
    }
  };

  const handleReject = async () => {
    if (!rejecting) return;
    setBusyId(rejecting.id);
    try {
      await rejectReorder(rejecting.id, reason || undefined);
      toast({ title: `${rejecting.order_code} rejected` });
      setOrders((prev) => prev.filter((o) => o.id !== rejecting.id));
      setRejecting(null);
      setReason("");
      loadHistory();
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Rejection failed" });
    } finally {
      setBusyId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  const approved = history.filter((o) => o.pm_approval_status === "Approved");
  const rejected = history.filter((o) => o.pm_approval_status === "Rejected");
  const tabs: { key: Tab; label: string; icon: LucideIcon; count: number }[] = [
    { key: "pending", label: "Pending", icon: Clock, count: orders.length },
    { key: "approved", label: "Approved", icon: CheckCircle2, count: approved.length },
    { key: "rejected", label: "Rejected", icon: XCircle, count: rejected.length },
  ];
  const shownHistory = tab === "approved" ? approved : rejected;

  return (
    <div className="space-y-6 animate-slide-up w-full">
      <div>
        <h1 className="text-2xl font-heading font-bold">Reorder Approvals</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Every automatic reorder (critical stock, low stock or predicted shortage)
          waits here for approval. The vendor with the lowest unit price for the item
          is selected and a smart contract is already created — approving here sends
          that vendor an itemized bill with Accept/Reject links via n8n.
        </p>
      </div>

      <div className="flex gap-1 bg-muted/30 p-1 w-fit flex-wrap" style={{ borderRadius: 20 }}>
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{ borderRadius: 20 }}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium transition-all ${
              tab === t.key ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <t.icon size={14} />
            {t.label}
            <span className="text-[11px] font-semibold px-1.5 rounded-full bg-muted/60">{t.count}</span>
          </button>
        ))}
      </div>

      {tab === "pending" && (
        <>
          {orders.length === 0 && (
            <div className="glass-card p-10 text-center text-muted-foreground text-sm flex flex-col items-center gap-3">
              <ShoppingCart size={28} className="text-primary" />
              No reorders awaiting your approval right now.
            </div>
          )}

          <div className="space-y-3">
            {orders.map((o) => {
              const others = otherQuotes(o);
              return (
              <div key={o.id} className="glass-card p-4 flex items-start justify-between gap-4 flex-wrap glow-cyan-hover">
                <div className="min-w-0 flex-1">
                  <CardHeader o={o} />
                  <p className="text-sm text-foreground font-medium">
                    {o.item_name} — {o.quantity} {o.unit}
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Vendor: {o.vendor_name} · Expected delivery {o.expected_delivery} ·{" "}
                    {o.unit_price != null && `${formatPKR(o.unit_price)} / ${o.unit} · `}
                    {o.total_price != null ? formatPKR(o.total_price) : "Pricing pending"}
                  </p>
                  {others.length > 0 && (
                    <p className="text-[11px] text-muted-foreground mt-1">
                      Also quoted:{" "}
                      {others
                        .map((c) => `${c.vendor_name} ${c.unit_price != null ? formatPKR(c.unit_price) : "(no price)"}`)
                        .join(" · ")}
                    </p>
                  )}
                  {o.contract_hash && (
                    <p className="text-[10px] font-mono text-muted-foreground mt-1 truncate">
                      Contract: {o.contract_hash}
                    </p>
                  )}
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  {isAdmin && (
                    <button
                      onClick={() => openEdit(o)}
                      disabled={busyId === o.id}
                      className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-border text-foreground hover:bg-muted/40 disabled:opacity-50"
                    >
                      <Pencil size={14} /> Edit
                    </button>
                  )}
                  <button
                    onClick={() => setRejecting(o)}
                    disabled={busyId === o.id}
                    className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-destructive/30 text-destructive hover:bg-destructive/10 disabled:opacity-50"
                  >
                    <XCircle size={14} /> Reject
                  </button>
                  <button
                    onClick={() => handleApprove(o)}
                    disabled={busyId === o.id}
                    className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium btn-navy disabled:opacity-60"
                  >
                    {busyId === o.id ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                    Approve
                  </button>
                </div>
              </div>
              );
            })}
          </div>
        </>
      )}

      {tab !== "pending" && (
        <>
          {shownHistory.length === 0 ? (
            <div className="glass-card p-10 text-center text-muted-foreground text-sm flex flex-col items-center gap-3">
              <ShoppingCart size={28} className="text-primary" />
              No {tab} auto-reorders yet.
            </div>
          ) : (
            <div className="space-y-3">
              {shownHistory.map((o) => <HistoryCard key={o.id} o={o} />)}
            </div>
          )}
        </>
      )}

      {editing && (
        <ModalPortal><div
          className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={() => setEditing(null)}
        >
          <div className="glass-card p-6 w-full max-w-md glow-cyan animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-1">
              <h3 className="font-heading font-bold text-lg">Edit {editing.order_code}</h3>
              <button onClick={() => setEditing(null)} className="text-muted-foreground hover:text-foreground">
                <X size={20} />
              </button>
            </div>
            <p className="text-sm text-muted-foreground mb-4">
              {editing.item_name} · {editing.vendor_name}
              {editing.unit_price != null && ` · ${formatPKR(editing.unit_price)} / ${editing.unit}`}
            </p>

            <label className="block text-sm font-medium text-muted-foreground mb-1.5">Quantity ({editing.unit})</label>
            <input
              type="number" min={0} step="any" value={editQty}
              onChange={(e) => setEditQty(e.target.value)}
              aria-invalid={!!editQtyError}
              className={`w-full px-4 py-2.5 rounded-lg bg-muted/50 border text-foreground focus:outline-none focus:ring-2 ${editQtyError ? "border-destructive focus:ring-destructive/40" : "border-border focus:ring-primary/50"}`}
            />
            {editQtyError && <p className="text-xs text-destructive mt-1.5">{editQtyError}</p>}

            <label className="block text-sm font-medium text-muted-foreground mb-1.5 mt-4">Expected delivery</label>
            <input
              type="date" min={todayStr()} value={editDelivery}
              onChange={(e) => setEditDelivery(e.target.value)}
              aria-invalid={!!editDateError}
              className={`w-full px-4 py-2.5 rounded-lg bg-muted/50 border text-foreground focus:outline-none focus:ring-2 ${editDateError ? "border-destructive focus:ring-destructive/40" : "border-border focus:ring-primary/50"}`}
            />
            {editDateError && <p className="text-xs text-destructive mt-1.5">{editDateError}</p>}

            {editing.unit_price != null && !editQtyError && (
              <p className="text-sm mt-4 flex justify-between">
                <span className="text-muted-foreground">New total</span>
                <span className="font-mono font-semibold text-primary">{formatPKR(Number(editQty) * editing.unit_price)}</span>
              </p>
            )}
            <p className="text-xs text-muted-foreground mt-3">
              Vendor and unit price stay as selected (lowest price). Saving replaces the pending smart
              contract with one using the new terms — the vendor is still only emailed once you approve.
            </p>

            <div className="flex gap-2 mt-5">
              <button onClick={() => setEditing(null)} className="flex-1 py-2.5 text-sm rounded-lg border border-border">Cancel</button>
              <button
                onClick={handleSaveEdit}
                disabled={busyId === editing.id || !!editQtyError || !!editDateError || editUnchanged}
                className="flex-1 py-2.5 font-semibold btn-navy flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {busyId === editing.id ? <Loader2 size={16} className="animate-spin" /> : <Pencil size={16} />}
                Save changes
              </button>
            </div>
          </div>
        </div></ModalPortal>
      )}

      {rejecting && (
        <ModalPortal><div
          className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={() => setRejecting(null)}
        >
          <div className="glass-card p-6 w-full max-w-md glow-cyan animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-heading font-bold text-lg">Reject {rejecting.order_code}</h3>
              <button onClick={() => setRejecting(null)} className="text-muted-foreground hover:text-foreground">
                <X size={20} />
              </button>
            </div>
            <p className="text-sm text-muted-foreground mb-4">
              No vendor email will be sent. The smart contract is marked Rejected.
            </p>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="Reason (optional)…"
              className="w-full px-4 py-2.5 rounded-lg bg-muted/50 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm"
            />
            <button
              onClick={handleReject}
              disabled={busyId === rejecting.id}
              className="w-full mt-4 py-2.5 font-semibold rounded-lg bg-destructive text-destructive-foreground flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {busyId === rejecting.id ? <Loader2 size={16} className="animate-spin" /> : <XCircle size={16} />}
              Confirm Rejection
            </button>
          </div>
        </div></ModalPortal>
      )}
    </div>
  );
};

export default ApprovalsQueue;
