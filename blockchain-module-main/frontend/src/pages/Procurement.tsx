// src/pages/Procurement.tsx
import { useState, useEffect, useCallback } from "react";
import { useLocation } from "react-router-dom";
import {
  ShoppingCart, Loader2, Info, RefreshCw, TruckIcon, History,
  ShieldCheck, Receipt, FileText,
} from "lucide-react";
import {
  getInventoryOverview, listOrders, manualReorder,
  InventoryItem, ProcurementOrder,
} from "@/services/api";
import { useToast } from "@/hooks/use-toast";
import OrderDetailModal from "@/components/OrderDetailModal";
import InvoiceModal from "@/components/InvoiceModal";
import { formatPKR } from "@/lib/currency";
import FieldError from "@/components/FieldError";
import { validate, isInteger, errorInputClass, orderQuantityError, unitPriceError } from "@/lib/validation";

const StatusBadge = ({ status }: { status: string }) => {
  const colors: Record<string, string> = {
    Verified: "bg-success/10 text-success",
    Pending: "bg-warning/10 text-warning",
    Signed: "bg-success/10 text-success",
    Executed: "bg-primary/10 text-primary",
    Rejected: "bg-destructive/10 text-destructive",
    Unverified: "bg-destructive/10 text-destructive",
  };
  return (
    <span className={`inline-flex items-center justify-center whitespace-nowrap text-xs px-2 py-0.5 rounded-full font-medium ${colors[status] || "bg-muted text-muted-foreground"}`}>
      {status}
    </span>
  );
};

const TriggerBadge = ({ type }: { type: string }) => {
  const styles: Record<string, string> = {
    "VEMA-Triggered": "bg-destructive/10 text-destructive border border-destructive/20",
    "Auto-Generated": "bg-warning/10 text-warning border border-warning/20",
    Manual: "bg-muted text-muted-foreground border border-border",
  };
  return (
    <span className={`inline-flex items-center justify-center whitespace-nowrap text-xs px-2 py-0.5 rounded-full font-medium ${styles[type] || "bg-muted text-muted-foreground"}`}>
      {type}
    </span>
  );
};

const STAGE_STEPS = [
  "Pending Verification", "Vendor Notified", "Email Confirmed",
  "Contract Signed", "Manufacturing", "Shipping", "Delivered",
];

const OrderStepper = ({ stage }: { stage: string }) => {
  const idx = STAGE_STEPS.indexOf(stage);
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {STAGE_STEPS.map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${i < idx ? "bg-success" : i === idx ? "bg-primary" : "bg-muted/40"}`} />
          {i < STAGE_STEPS.length - 1 && (
            <div className={`h-px w-3 ${i < idx ? "bg-success" : "bg-muted/30"}`} />
          )}
        </div>
      ))}
      <span className="text-xs ml-1 text-muted-foreground">{stage}</span>
    </div>
  );
};

interface LocationState {
  prefillItemId?: string;
  prefillQty?: number;
  prefillVendorId?: string;
  prefillVendorName?: string;
}

const Procurement = () => {
  const { toast } = useToast();
  const location = useLocation();

  const [tab, setTab] = useState<"place" | "active" | "history">("place");
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [activeOrders, setActive] = useState<ProcurementOrder[]>([]);
  const [pastOrders, setPast] = useState<ProcurementOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [showModal, setShowModal] = useState(false);
  const [selectedOrder, setSelectedOrder] = useState<ProcurementOrder | null>(null);
  const [invoiceOrderId, setInvoiceOrderId] = useState<string | null>(null);

  // Place-order form
  const [formItem, setFormItem] = useState("");
  const [formQty, setFormQty] = useState("100");
  const [formPrice, setFormPrice] = useState("");
  const [placing, setPlacing] = useState(false);
  const [vendorFilter, setVendorFilter] = useState<{ id: string; name: string } | null>(null);


  const load = useCallback(async () => {
    try {
      const [inv, ordersRes] = await Promise.all([
        getInventoryOverview(),
        listOrders({ limit: 200 }),
      ]);
      setItems(inv.items);
      const all = ordersRes.orders;
      setActive(all.filter((o) => o.stage !== "Delivered" && o.stage !== "Cancelled"));
      setPast(all.filter((o) => o.stage === "Delivered"));
    } catch {
      toast({ title: "Failed to load procurement data", variant: "destructive" });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  // Prefill the form when arriving via a "Reorder" link from Inventory /
  // Demand Prediction, or a "Create order with this vendor" link from the
  // Vendor Catalogue — same navigate()-with-state pattern either way.
  useEffect(() => {
    const state = location.state as LocationState | null;
    if (state?.prefillItemId) {
      setFormItem(state.prefillItemId);
      if (state.prefillQty) setFormQty(String(state.prefillQty));
      setTab("place");
    }
    if (state?.prefillVendorId) {
      setVendorFilter({ id: state.prefillVendorId, name: state.prefillVendorName || "selected vendor" });
      setTab("place");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-fill catalog unit price (still editable) once the items load or
  // the selected item changes.
  useEffect(() => {
    if (!formItem) return;
    const item = items.find((i) => i.item_id === formItem);
    if (item?.unit_price != null) setFormPrice(String(item.unit_price));
  }, [formItem, items]);

  const handleRefresh = () => { setRefreshing(true); load(); };

  // Live checks (error shows as you type): > 0, and a whole number.
  const qtyError = orderQuantityError(formQty) ?? validate(String(formQty), isInteger());
  const priceError = unitPriceError(formPrice);

  const handlePlaceOrder = async () => {
    if (!formItem || qtyError || priceError) return;
    setPlacing(true);
    try {
      const res = await manualReorder(formItem, Number(formQty), formPrice ? Number(formPrice) : undefined);
      toast({ title: "✅ Blockchain procurement order placed" });
      setFormItem("");
      setFormQty("100");
      setFormPrice("");
      await load();
      if (res?.order_id) setInvoiceOrderId(res.order_id);
      setTab("active");
    } catch (e: unknown) {
      toast({ title: "Order failed", description: String(e), variant: "destructive" });
    } finally {
      setPlacing(false);
    }
  };

  const tabs = [
    { key: "place" as const, label: "Place Order", icon: ShoppingCart },
    { key: "active" as const, label: "Active Orders", icon: TruckIcon },
    { key: "history" as const, label: "History", icon: History },
  ];

  const banners: Record<string, string> = {
    place: "Every order is logged to the blockchain queue as a smart contract, billed automatically, and emailed to the vendor for confirmation.",
    active: "Live procurement orders. Click any order to track its contract, delivery check-in, and billing.",
    history: "Delivered orders with blockchain execution hashes — immutably recorded on Hyperledger Fabric.",
  };

  const estimatedTotal =
    formItem && !qtyError && !priceError && formPrice
      ? Number(formQty) * Number(formPrice)
      : null;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-heading font-bold">Procurement</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Place blockchain-verified purchase orders and manage vendor contracts, deliveries, and billing.
          </p>
        </div>
        <button
          onClick={handleRefresh}
          className="flex items-center gap-2 px-3 py-2 text-sm border border-border rounded-lg hover:bg-muted/30 transition-colors"
        >
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Active Orders", value: activeOrders.length, icon: TruckIcon, color: "text-primary" },
          { label: "Delivered", value: pastOrders.length, icon: ShieldCheck, color: "text-success" },
          {
            label: "Awaiting Vendor",
            value: activeOrders.filter((o) => o.stage === "Pending Verification" || o.stage === "Vendor Notified").length,
            icon: Receipt, color: "text-warning",
          },
          {
            label: "Contracts Signed",
            value: activeOrders.filter((o) => o.contract_status === "Signed" || o.contract_status === "Executed").length,
            icon: FileText, color: "text-accent-cyan",
          },
        ].map((k) => (
          <div key={k.label} className="glass-card p-4 flex flex-col justify-between">
            <div className="flex items-center gap-2 mb-2">
              <k.icon size={18} className={k.color} />
              <span className="text-xs text-muted-foreground whitespace-nowrap">{k.label}</span>
            </div>
            <p className="text-2xl font-heading font-bold">{k.value}</p>
          </div>
        ))}
      </div>

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

      <div className="flex items-start gap-2 glass-card p-3 border-accent-cyan">
        <Info size={16} className="text-primary mt-0.5 flex-shrink-0" />
        <p className="text-xs text-muted-foreground">{banners[tab]}</p>
      </div>

      {/* ── PLACE ORDER TAB ─────────────────────────────────────────────── */}
      {tab === "place" && (
        <div className="glass-card p-6 max-w-xl">
          <h2 className="font-heading font-bold text-lg mb-4">New Smart Contract Order</h2>
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-sm font-medium text-muted-foreground">Select Item</label>
                {vendorFilter && (
                  <button
                    type="button"
                    onClick={() => setVendorFilter(null)}
                    className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary hover:bg-primary/20"
                    title="Clear vendor filter"
                  >
                    Filtered to {vendorFilter.name} ✕
                  </button>
                )}
              </div>
              <select
                value={formItem}
                onChange={(e) => setFormItem(e.target.value)}
                className="w-full px-4 py-2.5 rounded-lg bg-muted/50 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <option value="">— Select an item —</option>
                {items
                  .filter((i) => !vendorFilter || i.vendor_id === vendorFilter.id)
                  .map((i) => (
                    <option key={i.item_id} value={i.item_id}>
                      {i.name} (Stock: {i.current_stock} {i.unit})
                    </option>
                  ))}
              </select>
              {vendorFilter && items.filter((i) => i.vendor_id === vendorFilter.id).length === 0 && (
                <p className="text-xs text-warning mt-1.5">
                  {vendorFilter.name} has no items in internal inventory yet — an admin needs to add one
                  and assign this vendor before it can be ordered here.
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-muted-foreground mb-1.5">Quantity</label>
              <input
                type="number"
                min={0}
                step="any"
                value={formQty}
                onChange={(e) => setFormQty(e.target.value)}
                aria-invalid={!!qtyError}
                className={`w-full px-4 py-2.5 rounded-lg bg-muted/50 border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 ${qtyError ? errorInputClass : "border-border"}`}
              />
              <FieldError message={qtyError} />
            </div>
            <div>
              <label className="block text-sm font-medium text-muted-foreground mb-1.5">
                Unit Price (PKR) <span className="text-muted-foreground text-xs">— auto-filled from catalog, editable</span>
              </label>
              <input
                type="number"
                min={0}
                step="any"
                value={formPrice}
                onChange={(e) => setFormPrice(e.target.value)}
                placeholder="Leave blank to omit"
                aria-invalid={!!priceError}
                className={`w-full px-4 py-2.5 rounded-lg bg-muted/50 border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 ${priceError ? errorInputClass : "border-border"}`}
              />
              <FieldError message={priceError} />
              {estimatedTotal != null && (
                <p className="text-xs text-muted-foreground mt-1.5">
                  Estimated total:{" "}
                  <span className="font-mono font-semibold text-primary">
                    {formatPKR(estimatedTotal)}
                  </span>{" "}
                  + blockchain verification fee — you'll see the full bill after placing the order.
                </p>
              )}
            </div>
            <button
              onClick={handlePlaceOrder}
              disabled={!formItem || placing || !!qtyError || !!priceError}
              className="w-full py-2.5 font-semibold btn-navy disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {placing && <Loader2 size={16} className="animate-spin" />}
              Place Order via Smart Contract
            </button>
          </div>
        </div>
      )}

      {/* ── ACTIVE ORDERS TAB ───────────────────────────────────────────── */}
      {tab === "active" && (
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-muted/20">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Order ID</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Item</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Qty</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Vendor</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Trigger</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Contract</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Progress</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Delivery</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {activeOrders.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-sm text-muted-foreground">
                      No active orders. Place one above, or run an Inventory Check to auto-generate one.
                    </td>
                  </tr>
                )}
                {activeOrders.map((order) => (
                  <tr key={order.id} className="hover:bg-muted/10 transition-colors align-middle">
                    <td className="px-4 py-3 text-sm font-mono text-primary whitespace-nowrap">{order.order_code}</td>
                    <td className="px-4 py-3 text-sm font-medium whitespace-nowrap">{order.item_name}</td>
                    <td className="px-4 py-3 text-sm whitespace-nowrap">{order.quantity.toLocaleString()} {order.unit}</td>
                    <td className="px-4 py-3 text-sm whitespace-nowrap">{order.vendor_name}</td>
                    <td className="px-4 py-3 whitespace-nowrap"><TriggerBadge type={order.trigger_type} /></td>
                    <td className="px-4 py-3 whitespace-nowrap"><StatusBadge status={order.contract_status} /></td>
                    <td className="px-4 py-3 min-w-[200px]"><OrderStepper stage={order.stage} /></td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">{order.expected_delivery}</td>
                    <td className="px-4 py-3 flex items-center gap-3">
                      <button
                        onClick={() => { setSelectedOrder(order); setShowModal(true); }}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        Details
                      </button>
                      <button
                        onClick={() => setInvoiceOrderId(order.id)}
                        className="text-xs font-medium text-muted-foreground hover:text-foreground hover:underline"
                      >
                        Invoice
                      </button>
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
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-muted/20">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Order ID</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Item</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Qty</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Vendor</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Contract</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Delivered</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {pastOrders.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-muted-foreground">
                      No delivered orders yet.
                    </td>
                  </tr>
                )}
                {pastOrders.map((order) => (
                  <tr key={order.id} className="hover:bg-muted/10 transition-colors">
                    <td className="px-4 py-3 text-sm font-mono text-primary">{order.order_code}</td>
                    <td className="px-4 py-3 text-sm font-medium">{order.item_name}</td>
                    <td className="px-4 py-3 text-sm">{order.quantity.toLocaleString()} {order.unit}</td>
                    <td className="px-4 py-3 text-sm">{order.vendor_name}</td>
                    <td className="px-4 py-3"><StatusBadge status={order.contract_status} /></td>
                    <td className="px-4 py-3 text-sm text-muted-foreground">{order.expected_delivery}</td>
                    <td className="px-4 py-3 flex items-center gap-3">
                      <button
                        onClick={() => { setSelectedOrder(order); setShowModal(true); }}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        Details
                      </button>
                      <button
                        onClick={() => setInvoiceOrderId(order.id)}
                        className="text-xs font-medium text-muted-foreground hover:text-foreground hover:underline"
                      >
                        Invoice
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── ORDER DETAIL MODAL ──────────────────────────────────────────── */}
      {showModal && selectedOrder && (
        <OrderDetailModal
          order={selectedOrder}
          onClose={() => { setShowModal(false); setSelectedOrder(null); }}
          onUpdate={load}
        />
      )}

      {/* ── INVOICE / BILL MODAL ────────────────────────────────────────── */}
      {invoiceOrderId && (
        <InvoiceModal
          orderId={invoiceOrderId}
          onClose={() => setInvoiceOrderId(null)}
          successNote="Order placed and logged to the blockchain queue. Here's your bill — download it as a PDF for your records."
        />
      )}
    </div>
  );
};

export default Procurement;
