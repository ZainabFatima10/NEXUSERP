// src/pages/procurement/ProcurementDashboard.tsx
import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { ShoppingCart, Clock, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { listOrders, listPendingApprovals, ProcurementOrder } from "@/services/api";
import { STOCK_RANGES } from "@/lib/stockThresholds";

const StatCard = ({
  label, value, icon: Icon, tone,
}: {
  label: string; value: number; icon: typeof ShoppingCart; tone: string;
}) => (
  <div className="glass-card p-4 flex items-center gap-3">
    <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${tone}`}>
      <Icon size={18} />
    </div>
    <div>
      <p className="text-2xl font-heading font-bold leading-tight">{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  </div>
);

const ProcurementDashboard = () => {
  const [pendingCount, setPendingCount] = useState(0);
  const [orders, setOrders] = useState<ProcurementOrder[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [pending, all] = await Promise.all([
        listPendingApprovals(),
        listOrders({ limit: 100 }),
      ]);
      setPendingCount(pending.orders.length);
      setOrders(all.orders.filter((o) => o.below_20pct_trigger));
    } catch {
      // keep previous state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const placed = orders.filter((o) => o.vendor_decision === "Accepted");
  const rejected = orders.filter(
    (o) => o.vendor_decision === "Rejected" || o.pm_approval_status === "Rejected"
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <div>
        <h1 className="text-2xl font-heading font-bold">Procurement Manager Dashboard</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Auto-triggered reorders (Critical stock {STOCK_RANGES.Critical}, Low {STOCK_RANGES.Low} of
          minimum threshold), vendor responses, and order status.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard label="Awaiting your approval" value={pendingCount} icon={Clock} tone="bg-warning/10 text-warning" />
        <StatCard label="Placed (vendor accepted)" value={placed.length} icon={CheckCircle2} tone="bg-success/10 text-success" />
        <StatCard label="Rejected / declined" value={rejected.length} icon={XCircle} tone="bg-destructive/10 text-destructive" />
      </div>

      {pendingCount > 0 && (
        <Link
          to="/procurement/approvals"
          className="glass-card p-4 flex items-center justify-between glow-cyan-hover"
        >
          <span className="text-sm font-medium">
            {pendingCount} reorder{pendingCount === 1 ? "" : "s"} waiting for your approval
          </span>
          <span className="text-xs text-primary font-semibold">Review now →</span>
        </Link>
      )}

      <div>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
          Recent Auto-Triggered Orders
        </p>
        {orders.length === 0 ? (
          <div className="glass-card p-10 text-center text-muted-foreground text-sm flex flex-col items-center gap-3">
            <ShoppingCart size={28} className="text-primary" />
            No auto-triggered reorders yet.
          </div>
        ) : (
          <div className="space-y-2">
            {orders.slice(0, 10).map((o) => (
              <div key={o.id} className="glass-card p-3 flex items-center justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <span className="text-xs font-mono text-muted-foreground mr-2">{o.order_code}</span>
                  <span className="text-sm">{o.item_name}</span>
                </div>
                <span className="text-xs text-muted-foreground">{o.stage}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ProcurementDashboard;
