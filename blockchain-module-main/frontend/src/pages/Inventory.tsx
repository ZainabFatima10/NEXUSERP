// src/pages/Inventory.tsx
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowUpDown, Download, Info, RefreshCw,
  CheckCircle2, AlertTriangle, XCircle, Loader2,
  Package, TruckIcon, FileCheck, History, ShoppingCart,
} from "lucide-react";
import {
  getInventoryOverview, listOrders, runInventoryCheck,
  InventoryItem, ProcurementOrder,
  getNotifications, Notification
} from "@/services/api";
import { useToast } from "@/hooks/use-toast";
import OrderDetailModal from "@/components/OrderDetailModal";
import InvoiceModal from "@/components/InvoiceModal";
import { formatPKR } from "@/lib/currency";

type SortDir = "asc" | "desc";

const StatusBadge = ({ status }: { status: string }) => {
  const colors: Record<string, string> = {
    OK:         "bg-success/10 text-success",
    Low:        "bg-warning/10 text-warning",
    Critical:   "bg-destructive/10 text-destructive",
    "Out of Stock": "bg-destructive text-destructive-foreground",
    Verified:   "bg-success/10 text-success",
    Pending:    "bg-warning/10 text-warning",
    Signed:     "bg-success/10 text-success",
    Executed:   "bg-primary/10 text-primary",
    Rejected:   "bg-destructive/10 text-destructive",
    Unverified: "bg-destructive/10 text-destructive",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors[status] || "bg-muted text-muted-foreground"}`}>
      {status}
    </span>
  );
};

const TriggerBadge = ({ type }: { type: string }) => {
  const styles: Record<string, string> = {
    "VEMA-Triggered":  "bg-destructive/10 text-destructive border border-destructive/20",
    "Auto-Generated":  "bg-warning/10 text-warning border border-warning/20",
    "Manual":          "bg-muted text-muted-foreground border border-border",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${styles[type] || "bg-muted text-muted-foreground"}`}>
      {type}
    </span>
  );
};

const StockBar = ({ pct }: { pct: number }) => {
  const color = pct <= 20 ? "bg-destructive" : pct < 100 ? "bg-warning" : "bg-success";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-muted/50 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="text-xs text-muted-foreground w-10 text-right">{pct}%</span>
    </div>
  );
};

const STAGE_STEPS = [
  "Pending Verification",
  "Vendor Notified",
  "Email Confirmed",
  "Contract Signed",
  "Manufacturing",
  "Shipping",
  "Delivered",
];

const OrderStepper = ({ stage }: { stage: string }) => {
  const idx = STAGE_STEPS.indexOf(stage);
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {STAGE_STEPS.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
            i < idx ? "bg-success" : i === idx ? "bg-primary" : "bg-muted/40"
          }`} />
          {i < STAGE_STEPS.length - 1 && (
            <div className={`h-px w-3 ${i < idx ? "bg-success" : "bg-muted/30"}`} />
          )}
        </div>
      ))}
      <span className="text-xs ml-1 text-muted-foreground">{stage}</span>
    </div>
  );
};

const Inventory = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [tab, setTab] = useState<"overview" | "orders" | "history" | "reorders">("overview");
  const [sortCol, setSortCol]   = useState<string | null>(null);
  const [sortDir, setSortDir]   = useState<SortDir>("asc");
  const [showModal, setShowModal] = useState(false);
  const [selectedOrder, setSelectedOrder] = useState<ProcurementOrder | null>(null);

  // Data
  const [items, setItems]           = useState<InventoryItem[]>([]);
  const [summary, setSummary]       = useState<{
    total_items: number;
    ok: number;
    low: number;
    critical: number;
    out_of_stock: number;
    predicted_demand?: number;
    by_category?: Record<string, { total: number; ok: number; low: number; critical: number; predicted_demand: number }>;
  }>({ total_items: 0, ok: 0, low: 0, critical: 0, out_of_stock: 0, predicted_demand: 0 });
  const [invoiceOrderId, setInvoiceOrderId] = useState<string | null>(null);
  const [activeOrders, setActive]   = useState<ProcurementOrder[]>([]);
  const [pastOrders, setPast]       = useState<ProcurementOrder[]>([]);
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const load = useCallback(async () => {
    try {
      const [inv, ordersRes, notifsRes] = await Promise.all([
        getInventoryOverview(),
        listOrders({ limit: 200 }),
        getNotifications({ unread: true })
      ]);
      setItems(inv.items);
      setSummary(inv.summary);
      setNotifications(notifsRes.notifications.slice(0, 5));
      const all = ordersRes.orders;
      setActive(all.filter((o) => o.stage !== "Delivered" && o.stage !== "Cancelled"));
      setPast(all.filter((o) => o.stage === "Delivered"));
    } catch {
      toast({ title: "Failed to load inventory", variant: "destructive" });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  // Real-time notification polling
  useEffect(() => {
    const interval = setInterval(() => {
      getNotifications({ unread: true })
        .then(res => setNotifications(res.notifications.slice(0, 5)))
        .catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => { setRefreshing(true); load(); };

  const handleInventoryCheck = async () => {
    setRefreshing(true);
    try {
      const res = await runInventoryCheck();
      toast({ title: `✅ ${res.message}` });
      await load();
    } catch (e: unknown) {
      toast({ title: "Check failed", description: String(e), variant: "destructive" });
    }
  };

  // Manual reorder now lives on the Procurement tab (smart-contract order
  // placement + billing). Send the user there, prefilling the item/qty
  // when we already know what needs reordering.
  const goToProcurement = (itemId?: string, qty?: number) => {
    navigate("/admin/procurement", {
      state: itemId ? { prefillItemId: itemId, prefillQty: qty } : undefined,
    });
  };

  const toggleSort = (col: string) => {
    if (sortCol === col) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir("asc"); }
  };

  const SortHeader = ({ col, children }: { col: string; children: React.ReactNode }) => (
    <th
      className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider cursor-pointer hover:text-foreground transition-colors"
      onClick={() => toggleSort(col)}
    >
      <div className="flex items-center gap-1">{children}<ArrowUpDown size={12} /></div>
    </th>
  );

  const tabs = [
    { key: "overview" as const,  label: "Overview",       icon: Package },
    { key: "orders" as const,    label: "Current Orders", icon: TruckIcon },
    { key: "history" as const,   label: "History",        icon: History },
    { key: "reorders" as const,  label: "Reorders",       icon: FileCheck },
  ];

  const banners: Record<string, string> = {
    overview: "Real-time inventory from PostgreSQL. Critical items (≤20% threshold) auto-trigger VEMA reorders.",
    orders:   "Live procurement orders. Click any order to view contract details, tracking, and check-in history.",
    history:  "Delivered orders with blockchain execution hashes — immutably recorded on Hyperledger Fabric.",
    reorders: "Items below threshold flagged for reorder. VEMA auto-triggers critical items; Auto-Generated handles Low stock.",
  };

  const criticalItems = items.filter((i) => i.status === "Critical");
  const lowItems      = items.filter((i) => i.status === "Low");

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-heading font-bold">Inventory Management</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Track stock, procurement orders, blockchain contracts, and delivery check-ins.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={handleRefresh}
            className="flex items-center gap-2 px-3 py-2 text-sm border border-border rounded-lg hover:bg-muted/30 transition-colors"
          >
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>
          <button onClick={handleInventoryCheck} className="flex items-center gap-2 px-4 py-2 text-sm font-medium btn-navy">
            <RefreshCw size={14} /> Run Inventory Check
          </button>
        </div>
      </div>

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-4">
        {[
          { label: "Total Items",  value: summary.total_items, icon: Package,       color: "text-primary" },
          { label: "Predicted Demand", value: summary.predicted_demand || 0, icon: Package, color: "text-accent-cyan" },
          { label: "OK",           value: summary.ok,          icon: CheckCircle2,  color: "text-success" },
          { label: "Low Stock",    value: summary.low,         icon: AlertTriangle, color: "text-warning" },
          { label: "Critical",     value: summary.critical,    icon: XCircle,       color: "text-destructive" },
          { label: "Out of Stock", value: summary.out_of_stock, icon: XCircle,       color: "text-destructive" },
        ].map((k) => (
          <div key={k.label} className="glass-card p-4 glow-cyan-hover flex flex-col justify-between">
            <div className="flex items-center gap-2 mb-2">
              <k.icon size={18} className={k.color} />
              <span className="text-xs text-muted-foreground whitespace-nowrap">{k.label}</span>
            </div>
            <p className="text-2xl font-heading font-bold">{k.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { label: "Generation", value: items.filter(i => i.category === "Generation").length, color: "text-primary" },
          { label: "Infrastructure", value: items.filter(i => i.category === "Infrastructure").length, color: "text-secondary" },
          { label: "Operational", value: items.filter(i => i.category === "Operational").length, color: "text-accent-cyan" },
        ].map((k) => (
          <div key={k.label} className="glass-card p-4 flex items-center justify-between">
            <span className="text-sm font-medium text-muted-foreground">{k.label}</span>
            <p className="text-xl font-bold">{k.value}</p>
          </div>
        ))}
      </div>

      {/* Analytics & Notifications */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-3">
          <h2 className="text-sm font-heading font-bold text-muted-foreground uppercase tracking-wider">Inventory Usage & Predictions (Category-wise)</h2>
          <div className="glass-card p-6 h-64 flex flex-col justify-end overflow-hidden">
             <div className="flex items-end h-full gap-8 w-full px-4">
                {["Generation", "Infrastructure", "Operational"].map(cat => {
                   const catItems = items.filter(i => i.category === cat);
                   const count = catItems.length;
                   const totalStock = catItems.reduce((acc, i) => acc + Number(i.current_stock), 0);
                   const totalPredicted = catItems.reduce((acc, i) => acc + Number(i.predicted_demand || 0), 0);
                   const maxVal = Math.max(totalStock, totalPredicted) || 1;
                   const stockPct = (totalStock / maxVal) * 100;
                   const predPct = (totalPredicted / maxVal) * 100;

                   return (
                     <div key={cat} className="flex-1 flex flex-col items-center justify-end h-full group">
                       <div className="flex items-end gap-1 w-full h-full justify-center">
                         {/* Stock Bar */}
                         <div className="w-1/3 bg-primary/40 rounded-t-md relative flex flex-col items-center justify-start pt-2 group-hover:bg-primary/60 transition-all" style={{ height: `${Math.max(stockPct, 5)}%` }}>
                           <span className="text-[10px] font-bold -mt-5 bg-background/80 px-1 py-0.5 rounded text-primary">{totalStock > 1000 ? (totalStock/1000).toFixed(1)+'k' : totalStock}</span>
                         </div>
                         {/* Predicted Bar */}
                         <div className="w-1/3 bg-accent-cyan/40 rounded-t-md relative flex flex-col items-center justify-start pt-2 group-hover:bg-accent-cyan/60 transition-all" style={{ height: `${Math.max(predPct, 5)}%` }}>
                           <span className="text-[10px] font-bold -mt-5 bg-background/80 px-1 py-0.5 rounded text-accent-cyan">{totalPredicted > 1000 ? (totalPredicted/1000).toFixed(1)+'k' : totalPredicted}</span>
                         </div>
                       </div>
                       <span className="text-xs text-muted-foreground mt-3 font-medium text-center">{cat} ({count} items)</span>
                     </div>
                   );
                })}
             </div>
             <div className="flex justify-center gap-4 mt-2">
               <div className="flex items-center gap-1.5"><div className="w-3 h-3 bg-primary/40 rounded"></div><span className="text-xs text-muted-foreground">Current Stock</span></div>
               <div className="flex items-center gap-1.5"><div className="w-3 h-3 bg-accent-cyan/40 rounded"></div><span className="text-xs text-muted-foreground">Predicted Demand</span></div>
             </div>
          </div>
        </div>
        
        <div className="space-y-3">
          <h2 className="text-sm font-heading font-bold text-muted-foreground uppercase tracking-wider">Recent Alerts</h2>
          <div className="glass-card p-4 h-64 overflow-y-auto space-y-3">
             {notifications.length === 0 ? (
               <div className="h-full flex items-center justify-center">
                 <p className="text-xs text-muted-foreground">No recent alerts.</p>
               </div>
             ) : (
               notifications.map(n => (
                 <div key={n.id} className="border-l-2 border-primary pl-3 py-1 bg-muted/30 rounded-r-md px-2">
                   <h4 className="text-xs font-bold text-foreground truncate">{n.title}</h4>
                   <p className="text-[10px] text-muted-foreground line-clamp-2 mt-1">{n.description}</p>
                 </div>
               ))
             )}
          </div>
        </div>
      </div>

      {/* Alert strip for critical items */}
      {criticalItems.length > 0 && (
        <div className="glass-card p-3 border-destructive/40 bg-destructive/5 flex items-center gap-2">
          <XCircle size={16} className="text-destructive flex-shrink-0" />
          <p className="text-xs text-destructive font-medium">
            🔴 CRITICAL: {criticalItems.map((i) => i.name).join(", ")} — VEMA reorder triggered automatically.
          </p>
        </div>
      )}

      {/* Tabs */}
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
          </button>
        ))}
      </div>

      {/* Info banner */}
      <div className="flex items-start gap-2 glass-card p-3 border-accent-cyan">
        <Info size={16} className="text-primary mt-0.5 flex-shrink-0" />
        <p className="text-xs text-muted-foreground">{banners[tab]}</p>
      </div>

      {/* ── OVERVIEW TAB ────────────────────────────────────────────────── */}
      {tab === "overview" && (
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
              <table className="w-full">
              <thead className="bg-muted/20">
                <tr>
                  <SortHeader col="name">Item Name</SortHeader>
                  <SortHeader col="stock">Stock</SortHeader>
                  <SortHeader col="predicted_demand">Pred. Demand</SortHeader>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Level</th>
                  <SortHeader col="status">Status</SortHeader>
                  <SortHeader col="days_until_reorder">Days to Reorder</SortHeader>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Unit Price</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Vendor</th>
                  <SortHeader col="last_updated">Updated</SortHeader>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {items.map((item) => (
                  <tr key={item.item_id} className="hover:bg-muted/10 transition-colors">
                    <td className="px-4 py-3 text-sm font-medium">{item.name}</td>
                    <td className="px-4 py-3 text-sm font-mono">
                      {item.current_stock.toLocaleString()} {item.unit}
                    </td>
                    <td className="px-4 py-3 text-sm font-mono text-accent-cyan">
                      {item.predicted_demand ? item.predicted_demand.toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-3 w-32"><StockBar pct={item.stock_pct} /></td>
                    <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                    <td className="px-4 py-3 text-sm text-center">
                      {item.days_until_reorder === 0
                        ? <span className="text-destructive font-semibold">Now</span>
                        : item.days_until_reorder}
                    </td>
                    <td className="px-4 py-3 text-sm font-mono text-muted-foreground">
                      {item.unit_price != null ? formatPKR(item.unit_price) : "—"}
                    </td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">{item.vendor_name}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {new Date(item.last_updated).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── CURRENT ORDERS TAB ──────────────────────────────────────────── */}
      {tab === "orders" && (
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
              <table className="w-full">
              <thead className="bg-muted/20">
                <tr>
                  <SortHeader col="order_code">Order ID</SortHeader>
                  <SortHeader col="item_name">Item</SortHeader>
                  <SortHeader col="quantity">Qty</SortHeader>
                  <SortHeader col="vendor_name">Vendor</SortHeader>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Trigger</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Contract</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Progress</th>
                  <SortHeader col="expected_delivery">Delivery</SortHeader>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {activeOrders.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-sm text-muted-foreground">
                      No active orders. Run Inventory Check to generate orders.
                    </td>
                  </tr>
                )}
                {activeOrders.map((order) => (
                  <tr key={order.id} className="hover:bg-muted/10 transition-colors">
                    <td className="px-4 py-3 text-sm font-mono text-primary">{order.order_code}</td>
                    <td className="px-4 py-3 text-sm font-medium">{order.item_name}</td>
                    <td className="px-4 py-3 text-sm">{order.quantity.toLocaleString()} {order.unit}</td>
                    <td className="px-4 py-3 text-sm">{order.vendor_name}</td>
                    <td className="px-4 py-3"><TriggerBadge type={order.trigger_type} /></td>
                    <td className="px-4 py-3"><StatusBadge status={order.contract_status} /></td>
                    <td className="px-4 py-3 min-w-[200px]"><OrderStepper stage={order.stage} /></td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">{order.expected_delivery}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3 whitespace-nowrap">
                        <button
                          onClick={() => { setSelectedOrder(order); setShowModal(true); }}
                          className="text-xs text-primary hover:underline"
                        >
                          View Details
                        </button>
                        <button
                          onClick={() => setInvoiceOrderId(order.id)}
                          className="text-xs text-accent-cyan hover:underline"
                        >
                          View Bill
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── HISTORY TAB ─────────────────────────────────────────────────── */}
      {tab === "history" && (
        <>
          <div className="flex justify-end">
            <button className="flex items-center gap-2 px-4 py-2 text-sm font-medium btn-navy">
              <Download size={16} /> Export
            </button>
          </div>
          <div className="glass-card overflow-hidden">
            <div className="overflow-x-auto">
                <table className="w-full">
                <thead className="bg-muted/20">
                  <tr>
                    <SortHeader col="order_code">Order ID</SortHeader>
                    <SortHeader col="item_name">Item</SortHeader>
                    <SortHeader col="quantity">Qty</SortHeader>
                    <SortHeader col="vendor_name">Vendor</SortHeader>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Tx Hash</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Condition</th>
                    <SortHeader col="actual_delivery">Delivered</SortHeader>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {pastOrders.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-4 py-8 text-center text-sm text-muted-foreground">
                        No delivered orders yet.
                      </td>
                    </tr>
                  )}
                  {pastOrders.map((order) => (
                    <tr key={order.id} className="hover:bg-muted/10 transition-colors">
                      <td className="px-4 py-3 text-sm font-mono text-primary">{order.order_code}</td>
                      <td className="px-4 py-3 text-sm">{order.item_name}</td>
                      <td className="px-4 py-3 text-sm">{order.quantity.toLocaleString()}</td>
                      <td className="px-4 py-3 text-sm">{order.vendor_name}</td>
                      <td className="px-4 py-3 text-xs font-mono text-muted-foreground">
                        {order.contract_hash
                          ? `${order.contract_hash.slice(0, 10)}…${order.contract_hash.slice(-6)}`
                          : "—"}
                      </td>
                      <td className="px-4 py-3">
                        {order.delivery_condition && <StatusBadge status={order.delivery_condition} />}
                      </td>
                      <td className="px-4 py-3 text-sm text-muted-foreground">{order.actual_delivery || "—"}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3 whitespace-nowrap">
                          <button
                            onClick={() => { setSelectedOrder(order); setShowModal(true); }}
                            className="text-xs text-primary hover:underline"
                          >
                            View
                          </button>
                          <button
                            onClick={() => setInvoiceOrderId(order.id)}
                            className="text-xs text-accent-cyan hover:underline"
                          >
                            Bill
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── REORDERS TAB ────────────────────────────────────────────────── */}
      {tab === "reorders" && (
        <>
          <div className="flex justify-end">
            <button
              onClick={() => goToProcurement()}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium btn-navy"
            >
              <ShoppingCart size={16} /> Manually Place Reorder
            </button>
          </div>
          <div className="glass-card overflow-hidden">
            <div className="overflow-x-auto">
                <table className="w-full">
                <thead className="bg-muted/20">
                  <tr>
                    <SortHeader col="name">Item Name</SortHeader>
                    <SortHeader col="current_stock">Current Stock</SortHeader>
                    <SortHeader col="min_threshold">Min Threshold</SortHeader>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Status</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Trigger Type</th>
                    <SortHeader col="days_until_critical">Days to Critical</SortHeader>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Reorder Qty</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {[...criticalItems, ...lowItems].map((item) => (
                    <tr key={item.item_id} className="hover:bg-muted/10 transition-colors">
                      <td className="px-4 py-3 text-sm font-medium">{item.name}</td>
                      <td className="px-4 py-3 text-sm text-destructive font-semibold">
                        {item.current_stock.toLocaleString()} {item.unit}
                      </td>
                      <td className="px-4 py-3 text-sm">{item.min_threshold.toLocaleString()}</td>
                      <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
                      <td className="px-4 py-3">
                        <TriggerBadge type={item.status === "Critical" ? "VEMA-Triggered" : "Auto-Generated"} />
                      </td>
                      <td className="px-4 py-3 text-sm text-center">
                        {item.days_until_critical === 0
                          ? <span className="text-destructive font-semibold">Now</span>
                          : item.days_until_critical}
                      </td>
                      <td className="px-4 py-3 text-sm">{item.reorder_quantity.toLocaleString()}</td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => goToProcurement(item.item_id, item.reorder_quantity)}
                          className="flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
                        >
                          <ShoppingCart size={13} /> Reorder
                        </button>
                      </td>
                    </tr>
                  ))}
                  {criticalItems.length === 0 && lowItems.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-4 py-8 text-center text-sm text-muted-foreground">
                        ✅ All inventory levels are healthy.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── ORDER DETAIL MODAL ──────────────────────────────────────────── */}
      {showModal && selectedOrder && (
        <OrderDetailModal
          order={selectedOrder}
          onClose={() => { setShowModal(false); setSelectedOrder(null); }}
          onUpdate={load}
        />
      )}

      {/* ── INVOICE MODAL ──────────────────────────────────────────────── */}
      {invoiceOrderId && (
        <InvoiceModal
          orderId={invoiceOrderId}
          onClose={() => setInvoiceOrderId(null)}
        />
      )}

    </div>
  );
};

export default Inventory;
