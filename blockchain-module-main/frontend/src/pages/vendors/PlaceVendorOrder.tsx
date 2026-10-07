// src/pages/vendors/PlaceVendorOrder.tsx
// Shared across /admin/place-order and /procurement/place-order. Orders
// placed from the approved vendor catalogue (vendor_items) — distinct from
// Procurement.tsx's item-first internal-inventory reorder flow. Reached via
// the Vendor Catalogue's "Create Order" button (navigate()-with-state,
// prefillVendorId) or directly from the sidebar.
import { useState, useEffect, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Loader2, Plus, Trash2, ShoppingCart } from "lucide-react";
import { listVendors, getVendorItems, placeVendorOrder, getPaymentsConfig, Vendor, VendorItem } from "@/services/api";
import { formatPKR } from "@/lib/currency";
import { useToast } from "@/hooks/use-toast";

interface LocationState {
  prefillVendorId?: string;
  prefillVendorName?: string;
}

interface OrderRow {
  vendor_item_id: string;
  quantity: number;
}

const PlaceVendorOrder = () => {
  const { toast } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const trackingBase = location.pathname.startsWith("/admin") ? "/admin/tracking" : "/procurement/tracking";

  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [vendorId, setVendorId] = useState("");
  const [items, setItems] = useState<VendorItem[]>([]);
  const [rows, setRows] = useState<OrderRow[]>([]);
  const [destinationName, setDestinationName] = useState("");
  const [destinationCity, setDestinationCity] = useState("");
  const [destinationAddress, setDestinationAddress] = useState("");
  const [requestedDate, setRequestedDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [placing, setPlacing] = useState(false);
  const [feeRate, setFeeRate] = useState(0.005);
  const [maxOrderTotal, setMaxOrderTotal] = useState<number | null>(null);

  useEffect(() => {
    getPaymentsConfig().then((c) => { setFeeRate(c.platform_fee_rate); setMaxOrderTotal(c.max_order_total); }).catch(() => {});
  }, []);

  useEffect(() => {
    listVendors().then((res) => setVendors(res.vendors)).catch(() => {
      toast({ title: "Failed to load vendors", variant: "destructive" });
    }).finally(() => setLoading(false));
  }, [toast]);

  useEffect(() => {
    const state = location.state as LocationState | null;
    if (state?.prefillVendorId) setVendorId(state.prefillVendorId);
  }, [location.state]);

  const loadItems = useCallback(async (vid: string) => {
    if (!vid) { setItems([]); return; }
    setItemsLoading(true);
    try {
      const res = await getVendorItems(vid);
      setItems(res.items);
    } catch {
      toast({ title: "Failed to load vendor catalogue", variant: "destructive" });
    } finally {
      setItemsLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadItems(vendorId); setRows([]); }, [vendorId, loadItems]);

  const addRow = () => setRows((r) => [...r, { vendor_item_id: "", quantity: 1 }]);
  const updateRow = (idx: number, patch: Partial<OrderRow>) =>
    setRows((r) => r.map((row, i) => (i === idx ? { ...row, ...patch } : row)));
  const removeRow = (idx: number) => setRows((r) => r.filter((_, i) => i !== idx));

  const itemById = (id: string) => items.find((i) => i.id === id);
  const subtotal = rows.reduce((sum, r) => {
    const it = itemById(r.vendor_item_id);
    return sum + (it ? it.unit_price * r.quantity : 0);
  }, 0);

  const overCap = maxOrderTotal != null && subtotal * (1 + feeRate) > maxOrderTotal;
  const canSubmit = vendorId && destinationName.trim() && rows.length > 0 && rows.every((r) => r.vendor_item_id && r.quantity > 0) && !overCap;

  const handleSubmit = async () => {
    setPlacing(true);
    try {
      const res = await placeVendorOrder({
        vendor_id: vendorId,
        items: rows.map((r) => ({ vendor_item_id: r.vendor_item_id, quantity: r.quantity })),
        destination_name: destinationName,
        destination_city: destinationCity || undefined,
        destination_address: destinationAddress || undefined,
        requested_delivery_date: requestedDate || undefined,
      });
      toast({ title: `Order ${res.order_code} placed — vendor notified` });
      navigate(`${trackingBase}/${res.order_id}`);
    } catch (e: unknown) {
      toast({ title: e instanceof Error ? e.message : "Failed to place order", variant: "destructive" });
    } finally {
      setPlacing(false);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-primary" size={36} /></div>;
  }

  return (
    <div className="space-y-6 animate-slide-up max-w-3xl">
      <div>
        <h1 className="text-2xl font-heading font-bold">Place Vendor Order</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Orders go to the vendor's own catalogue — they'll accept or reject by email, no login needed.
        </p>
      </div>

      <div className="glass-card p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-muted-foreground mb-1.5">Vendor</label>
          <select value={vendorId} onChange={(e) => setVendorId(e.target.value)} className="w-full px-4 py-2.5 rounded-lg bg-muted/50 border border-border">
            <option value="">— Select an approved vendor —</option>
            {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </div>

        <div className="grid sm:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-muted-foreground mb-1.5">Destination Name *</label>
            <input value={destinationName} onChange={(e) => setDestinationName(e.target.value)} placeholder="e.g. Main Warehouse" className="w-full px-4 py-2.5 rounded-lg bg-muted/50 border border-border" />
          </div>
          <div>
            <label className="block text-sm font-medium text-muted-foreground mb-1.5">City</label>
            <input value={destinationCity} onChange={(e) => setDestinationCity(e.target.value)} className="w-full px-4 py-2.5 rounded-lg bg-muted/50 border border-border" />
          </div>
          <div>
            <label className="block text-sm font-medium text-muted-foreground mb-1.5">Requested Delivery</label>
            <input type="date" value={requestedDate} onChange={(e) => setRequestedDate(e.target.value)} className="w-full px-4 py-2.5 rounded-lg bg-muted/50 border border-border" />
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium text-muted-foreground mb-1.5">Address</label>
          <input value={destinationAddress} onChange={(e) => setDestinationAddress(e.target.value)} className="w-full px-4 py-2.5 rounded-lg bg-muted/50 border border-border" />
        </div>

        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="block text-sm font-medium text-muted-foreground">Items</label>
            {itemsLoading && <Loader2 className="animate-spin text-primary" size={14} />}
          </div>
          {vendorId && items.length === 0 && !itemsLoading && (
            <p className="text-sm text-muted-foreground mb-2">This vendor has no catalogue items.</p>
          )}
          <div className="space-y-2">
            {rows.map((row, idx) => {
              const it = itemById(row.vendor_item_id);
              return (
                <div key={idx} className="flex items-center gap-2">
                  <select
                    value={row.vendor_item_id}
                    onChange={(e) => updateRow(idx, { vendor_item_id: e.target.value })}
                    className="flex-1 px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border"
                  >
                    <option value="">— Select item —</option>
                    {items.map((i) => <option key={i.id} value={i.id}>{i.name} ({formatPKR(i.unit_price)}/{i.unit})</option>)}
                  </select>
                  <input
                    type="number" min={0.01} step="any" value={row.quantity}
                    onChange={(e) => updateRow(idx, { quantity: Number(e.target.value) })}
                    className="w-24 px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border"
                  />
                  <span className="text-sm text-muted-foreground w-28 text-right font-mono">
                    {it ? formatPKR(it.unit_price * row.quantity) : "—"}
                  </span>
                  <button onClick={() => removeRow(idx)} className="text-muted-foreground hover:text-destructive"><Trash2 size={16} /></button>
                </div>
              );
            })}
          </div>
          <button onClick={addRow} disabled={!vendorId} className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-muted/40 hover:bg-muted/60 disabled:opacity-50">
            <Plus size={14} /> Add Item
          </button>
        </div>

        {rows.length > 0 && (
          <div className="ml-auto max-w-xs text-sm space-y-1 font-mono">
            <p className="flex justify-between text-muted-foreground"><span className="font-sans">Subtotal (paid to vendor)</span><span>{formatPKR(subtotal)}</span></p>
            <p className="flex justify-between text-muted-foreground">
              <span className="font-sans">Platform fee ({(feeRate * 100).toFixed(1)}%)</span><span>{formatPKR(Math.round(subtotal * feeRate * 100) / 100)}</span>
            </p>
            <p className="flex justify-between font-semibold text-primary border-t border-border pt-1">
              <span className="font-sans">Total</span><span>{formatPKR(Math.round(subtotal * (1 + feeRate) * 100) / 100)}</span>
            </p>
            <p className="text-[11px] text-muted-foreground font-sans text-right">Held in escrow once the vendor accepts; captured after you approve delivery.</p>
            {overCap && (
              <p className="text-xs text-destructive font-sans text-right">
                Over the per-order payment limit of {formatPKR(maxOrderTotal, { decimals: false })} — split this into smaller orders.
              </p>
            )}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={!canSubmit || placing}
          className="w-full py-2.5 font-semibold btn-navy disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {placing ? <Loader2 size={16} className="animate-spin" /> : <ShoppingCart size={16} />}
          Place Order
        </button>
      </div>
    </div>
  );
};

export default PlaceVendorOrder;
