// src/pages/vendors/VendorCatalogue.tsx
// Shared across /admin/vendor-catalogue and /procurement/vendor-catalogue.
// Approved vendors only (enforced server-side too) — browse their catalogue
// and jump into Place Vendor Order with a vendor preselected, the same
// navigate()-with-state pattern Inventory -> Procurement already uses.
import { useEffect, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Loader2, Search, Building2, MapPin, Clock, ShoppingCart, ChevronDown, ChevronUp } from "lucide-react";
import { listVendors, getVendorItems, Vendor, VendorItem } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

const VendorCatalogue = () => {
  const { toast } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const placeOrderBase = location.pathname.startsWith("/admin") ? "/admin/place-order" : "/procurement/place-order";

  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [items, setItems] = useState<Record<string, VendorItem[]>>({});
  const [itemsLoading, setItemsLoading] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listVendors({ search: search || undefined, category: category || undefined });
      setVendors(res.vendors);
    } catch {
      toast({ title: "Failed to load vendors", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [search, category, toast]);

  useEffect(() => { load(); }, [load]);

  const categories = Array.from(new Set(vendors.flatMap((v) => v.categories || [])));

  const toggleExpand = async (vendorId: string) => {
    if (expanded === vendorId) { setExpanded(null); return; }
    setExpanded(vendorId);
    if (!items[vendorId]) {
      setItemsLoading(vendorId);
      try {
        const res = await getVendorItems(vendorId);
        setItems((prev) => ({ ...prev, [vendorId]: res.items }));
      } catch {
        toast({ title: "Failed to load vendor catalogue", variant: "destructive" });
      } finally {
        setItemsLoading(null);
      }
    }
  };

  const createOrderWithVendor = (vendor: Vendor) => {
    navigate(placeOrderBase, { state: { prefillVendorId: vendor.id, prefillVendorName: vendor.name } });
  };

  return (
    <div className="space-y-6 animate-slide-up">
      <div>
        <h1 className="text-2xl font-heading font-bold">Vendor Catalogue</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Approved vendors only — pending or rejected applications never appear here.
        </p>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search vendors or items..."
            className="pl-9 pr-3 py-2 text-sm rounded-lg border border-border bg-background w-full"
          />
        </div>
        <select value={category} onChange={(e) => setCategory(e.target.value)} className="px-3 py-2 text-sm rounded-lg border border-border bg-background">
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-primary" size={36} /></div>
      ) : vendors.length === 0 ? (
        <div className="glass-card p-10 text-center text-muted-foreground text-sm">
          No approved vendors yet — approve a vendor application to see it here.
        </div>
      ) : (
        <div className="space-y-3">
          {vendors.map((v) => (
            <div key={v.id} className="glass-card overflow-hidden">
              <button onClick={() => toggleExpand(v.id)} className="w-full text-left p-4 flex items-center justify-between gap-4">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <Building2 size={18} className="text-primary" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-medium truncate">{v.name}</p>
                    <p className="text-xs text-muted-foreground flex items-center gap-3 flex-wrap">
                      {v.city && <span className="flex items-center gap-1"><MapPin size={11} /> {v.city}, {v.province}</span>}
                      {v.lead_time_days != null && <span className="flex items-center gap-1"><Clock size={11} /> {v.lead_time_days}d lead time</span>}
                      <span>{v.item_count} item{v.item_count === 1 ? "" : "s"}</span>
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    onClick={(e) => { e.stopPropagation(); createOrderWithVendor(v); }}
                    className="flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg bg-primary text-white hover:opacity-90"
                  >
                    <ShoppingCart size={13} /> Create Order
                  </button>
                  {expanded === v.id ? <ChevronUp size={16} className="text-muted-foreground" /> : <ChevronDown size={16} className="text-muted-foreground" />}
                </div>
              </button>

              {expanded === v.id && (
                <div className="border-t border-border p-4">
                  {itemsLoading === v.id ? (
                    <Loader2 className="animate-spin text-primary" size={20} />
                  ) : (items[v.id]?.length ?? 0) === 0 ? (
                    <p className="text-sm text-muted-foreground">No catalogue items.</p>
                  ) : (
                    <div className="overflow-x-auto scroll-thin">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs text-muted-foreground uppercase">
                            <th className="py-1.5 pr-3">Item</th><th className="py-1.5 pr-3">Category</th>
                            <th className="py-1.5 pr-3">Unit</th><th className="py-1.5 pr-3">Unit Price</th><th className="py-1.5 pr-3">MOQ</th>
                          </tr>
                        </thead>
                        <tbody>
                          {items[v.id].map((it) => (
                            <tr key={it.id} className="border-t border-border">
                              <td className="py-1.5 pr-3">{it.name}</td>
                              <td className="py-1.5 pr-3">{it.category || "—"}</td>
                              <td className="py-1.5 pr-3">{it.unit}</td>
                              <td className="py-1.5 pr-3 font-mono">PKR {it.unit_price.toLocaleString()}</td>
                              <td className="py-1.5 pr-3">{it.moq ?? "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default VendorCatalogue;
