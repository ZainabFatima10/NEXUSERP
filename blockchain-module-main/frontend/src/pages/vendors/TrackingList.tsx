// src/pages/vendors/TrackingList.tsx
// Shared across /admin/tracking and /procurement/tracking. The orderer's
// (Receiver's) dedicated view of every order they've placed, from
// placement through payment. "My orders" by default; Admin/PM can toggle
// "All orders" — everyone else would only ever see their own (enforced
// server-side too, not just hidden in the UI).
import { useEffect, useState, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Loader2, Search, Clock, TruckIcon, AlertTriangle, CheckCircle2, XCircle,
  ChevronRight,
} from "lucide-react";
import { listTracking, getTrackingSummary, subscribeToNotifications, TrackingOrderRow, TrackingSummary } from "@/services/api";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/hooks/use-toast";
import { formatPKR } from "@/lib/currency";

const SUMMARY_CARDS: { key: keyof TrackingSummary; label: string; icon: typeof Clock; color: string }[] = [
  { key: "awaiting_vendor", label: "Awaiting Vendor", icon: Clock, color: "text-warning" },
  { key: "in_progress", label: "In Progress", icon: TruckIcon, color: "text-primary" },
  { key: "action_needed", label: "Action Needed", icon: AlertTriangle, color: "text-destructive" },
  { key: "delayed", label: "Delayed", icon: AlertTriangle, color: "text-warning" },
  { key: "completed", label: "Completed", icon: CheckCircle2, color: "text-success" },
  { key: "rejected_expired_disputed", label: "Rejected/Expired/Cancelled/Disputed", icon: XCircle, color: "text-muted-foreground" },
];

const statusChip = (order: TrackingOrderRow) => {
  if (order.status === "PENDING_VENDOR") return <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-warning/10 text-warning">Awaiting Vendor</span>;
  if (order.status === "REJECTED") return <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-destructive/10 text-destructive">Rejected</span>;
  if (order.status === "EXPIRED") return <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-muted text-muted-foreground">Expired</span>;
  if (order.status === "CANCELLED") return <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-muted text-muted-foreground">Cancelled</span>;
  if (order.contract_status === "Disputed") return <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-destructive/10 text-destructive">Disputed</span>;
  if (order.contract_status === "Executed") return <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-success/10 text-success">Completed</span>;
  return <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-primary/10 text-primary">{order.contract_status}</span>;
};

const PROGRESS_STEPS = ["Preparing", "Dispatched", "InTransit", "OutForDelivery", "Arrived", "Approved", "Executed"];

const MiniProgress = ({ order }: { order: TrackingOrderRow }) => {
  if (order.status !== "ACCEPTED") return null;
  const idx = PROGRESS_STEPS.indexOf(order.contract_status);
  return (
    <div className="flex items-center gap-0.5 mt-2">
      {PROGRESS_STEPS.map((s, i) => (
        <div key={s} className={`h-1 flex-1 rounded-full ${i <= idx ? "bg-primary" : "bg-muted/40"}`} />
      ))}
    </div>
  );
};

const TrackingList = () => {
  const { toast } = useToast();
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const base = location.pathname.startsWith("/admin") ? "/admin/tracking" : "/procurement/tracking";

  // Staff with org-wide oversight (admin / procurement manager) land on
  // "All Orders" by default — defaulting to "My Orders" made this page look
  // broken/empty for them whenever the order they came to check was placed
  // by a different staff member.
  const isOversightRole = user?.role === "admin" || user?.role === "procurement_manager";
  const [scope, setScope] = useState<"mine" | "all">(isOversightRole ? "all" : "mine");
  const [filter, setFilter] = useState<keyof TrackingSummary | null>(null);
  const [search, setSearch] = useState("");
  const [orders, setOrders] = useState<TrackingOrderRow[]>([]);
  const [summary, setSummary] = useState<TrackingSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [ordersRes, summaryRes] = await Promise.all([
        listTracking({ scope, search: search || undefined, limit: 100 }),
        getTrackingSummary(scope),
      ]);
      setOrders(ordersRes.orders);
      setSummary(summaryRes);
    } catch {
      if (!silent) toast({ title: "Failed to load order tracking", variant: "destructive" });
    } finally {
      if (!silent) setLoading(false);
    }
  }, [scope, search, toast]);

  useEffect(() => { load(); }, [load]);

  // Live updates: any vendor_order event (placed, accepted, shipment
  // checkpoint, approved, disputed...) refreshes the list/summary in the
  // background — no manual refresh needed to see a vendor's email reply
  // reflected here.
  useEffect(() => {
    const unsubscribe = subscribeToNotifications((n) => {
      if (n.entity_type === "vendor_order") load(true);
    });
    return unsubscribe;
  }, [load]);

  const filtered = orders.filter((o) => {
    if (!filter) return true;
    if (filter === "awaiting_vendor") return o.status === "PENDING_VENDOR";
    if (filter === "action_needed") return !!o.action_needed;
    if (filter === "delayed") return o.delayed;
    if (filter === "completed") return o.contract_status === "Executed";
    if (filter === "rejected_expired_disputed") return ["REJECTED", "EXPIRED", "CANCELLED"].includes(o.status) || ["Disputed", "Cancelled"].includes(o.contract_status);
    if (filter === "in_progress") return o.status === "ACCEPTED" && !["Executed", "Disputed", "Cancelled"].includes(o.contract_status);
    return true;
  });

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-heading font-bold">Order Tracking</h1>
          <p className="text-muted-foreground text-sm mt-1">Follow every order from placement to payment.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setScope("mine")} className={`text-sm px-4 py-2 rounded-lg ${scope === "mine" ? "bg-primary text-white" : "bg-muted/40 text-muted-foreground"}`}>My Orders</button>
          <button onClick={() => setScope("all")} className={`text-sm px-4 py-2 rounded-lg ${scope === "all" ? "bg-primary text-white" : "bg-muted/40 text-muted-foreground"}`}>All Orders</button>
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {SUMMARY_CARDS.map((c) => {
            const Icon = c.icon;
            const active = filter === c.key;
            return (
              <button
                key={c.key}
                onClick={() => setFilter(active ? null : c.key)}
                className={`glass-card p-4 text-left transition-all ${active ? "ring-2 ring-primary/50" : "glow-cyan-hover"}`}
              >
                <Icon size={16} className={c.color} />
                <p className="text-2xl font-heading font-bold mt-1">{summary[c.key]}</p>
                <p className="text-xs text-muted-foreground">{c.label}</p>
              </button>
            );
          })}
        </div>
      )}

      <div className="relative max-w-sm">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search order code or vendor..."
          className="pl-9 pr-3 py-2 text-sm rounded-lg border border-border bg-background w-full"
        />
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-primary" size={36} /></div>
      ) : filtered.length === 0 ? (
        <div className="glass-card p-10 text-center text-muted-foreground text-sm space-y-3">
          <p>{orders.length === 0 && scope === "mine" ? "You haven't placed any orders yet." : "No orders match this filter."}</p>
          {orders.length === 0 && scope === "mine" && (
            <button onClick={() => setScope("all")} className="text-sm font-medium text-primary hover:underline">
              Show all orders instead →
            </button>
          )}
          {orders.length > 0 && filter && (
            <button onClick={() => setFilter(null)} className="text-sm font-medium text-primary hover:underline">
              Clear filter
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((o) => (
            <button
              key={o.id}
              onClick={() => navigate(`${base}/${o.id}`)}
              className="w-full text-left glass-card p-4 glow-cyan-hover flex items-center justify-between gap-4"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-sm font-semibold">{o.order_code}</span>
                  {statusChip(o)}
                  {o.delayed && <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-warning/10 text-warning flex items-center gap-1"><AlertTriangle size={10} /> Delayed</span>}
                </div>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {o.vendor_name} → {o.destination_name} · {formatPKR(o.total_amount)}
                </p>
                <MiniProgress order={o} />
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                {o.action_needed && (
                  <span className="text-xs font-medium px-3 py-1.5 rounded-lg bg-destructive/10 text-destructive">
                    {o.action_needed === "confirm_arrival" ? "Confirm arrival" : "Approve / dispute"}
                  </span>
                )}
                <ChevronRight size={18} className="text-muted-foreground" />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default TrackingList;
