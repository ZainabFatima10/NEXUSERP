// src/pages/procurement/ApprovalsQueue.tsx
import { useEffect, useState, useCallback } from "react";
import { CheckCircle2, XCircle, Loader2, ShoppingCart, X } from "lucide-react";
import {
  listPendingApprovals, approveReorder, rejectReorder, ProcurementOrder,
} from "@/services/api";
import { useToast } from "@/hooks/use-toast";
import { formatPKR } from "@/lib/currency";

const ApprovalsQueue = () => {
  const { toast } = useToast();
  const [orders, setOrders] = useState<ProcurementOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<ProcurementOrder | null>(null);
  const [reason, setReason] = useState("");

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

  useEffect(() => { load(); }, [load]);

  const handleApprove = async (order: ProcurementOrder) => {
    setBusyId(order.id);
    try {
      const res = await approveReorder(order.id);
      toast({ title: `✅ ${order.order_code} approved`, description: `Vendor email: ${res.vendor_email_status}` });
      setOrders((prev) => prev.filter((o) => o.id !== order.id));
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Approval failed" });
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

  return (
    <div className="space-y-6 animate-slide-up max-w-4xl">
      <div>
        <h1 className="text-2xl font-heading font-bold">Reorder Approvals</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Auto-triggered when an item's stock falls to or below 20% of its minimum
          threshold. A smart contract is already created — approving here sends the
          vendor an itemized bill with Accept/Reject links via n8n.
        </p>
      </div>

      {orders.length === 0 && (
        <div className="glass-card p-10 text-center text-muted-foreground text-sm flex flex-col items-center gap-3">
          <ShoppingCart size={28} className="text-primary" />
          No reorders awaiting your approval right now.
        </div>
      )}

      <div className="space-y-3">
        {orders.map((o) => (
          <div key={o.id} className="glass-card p-4 flex items-start justify-between gap-4 flex-wrap glow-cyan-hover">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap mb-1.5">
                <span className="text-xs font-mono text-muted-foreground">{o.order_code}</span>
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-destructive/10 text-destructive">
                  Critical Stock Trigger
                </span>
              </div>
              <p className="text-sm text-foreground font-medium">
                {o.item_name} — {o.quantity} {o.unit}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Vendor: {o.vendor_name} · Expected delivery {o.expected_delivery} ·{" "}
                {o.total_price != null ? formatPKR(o.total_price) : "Pricing pending"}
              </p>
              {o.contract_hash && (
                <p className="text-[10px] font-mono text-muted-foreground mt-1 truncate">
                  Contract: {o.contract_hash}
                </p>
              )}
            </div>
            <div className="flex gap-2 flex-shrink-0">
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
        ))}
      </div>

      {rejecting && (
        <div
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
        </div>
      )}
    </div>
  );
};

export default ApprovalsQueue;
