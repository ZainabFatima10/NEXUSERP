// src/pages/procurement/VemaReorders.tsx
// VEMA Auto-Reorders — deterministic stock-scan proposals (quantity, vendor
// ranking) with an LLM-phrased rationale, reviewed here by a Procurement
// Manager/Admin before a real order is ever created. Separate from, and
// additive alongside, the older /procurement/approvals queue. See
// docs/VEMA_AUTO_REORDER.md.
import { useEffect, useState, useCallback } from "react";
import { Bot, CheckCircle2, XCircle, Loader2, X, Search } from "lucide-react";
import {
  listVemaReorderRequests, getVemaReorderStats, approveVemaReorderRequest,
  rejectVemaReorderRequest, getVemaReorderRequest, VemaReorderRequest, VemaReorderStats,
} from "@/services/api";
import { useToast } from "@/hooks/use-toast";
import { formatPKR } from "@/lib/currency";
import FieldError from "@/components/FieldError";
import { validate, required, isInteger, isPositive, errorInputClass } from "@/lib/validation";

const STATUS_TABS: { key: string; label: string }[] = [
  { key: "pending_approval", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "", label: "All" },
];

const STATUS_STYLE: Record<string, string> = {
  pending_approval: "bg-warning/10 text-warning",
  approved: "bg-success/10 text-success",
  rejected: "bg-destructive/10 text-destructive",
  expired: "bg-muted text-muted-foreground",
};

const VemaReorders = () => {
  const { toast } = useToast();
  const [stats, setStats] = useState<VemaReorderStats | null>(null);
  const [tab, setTab] = useState<string>("pending_approval");
  const [search, setSearch] = useState("");
  const [requests, setRequests] = useState<VemaReorderRequest[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<VemaReorderRequest | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [editQty, setEditQty] = useState("");
  const [editVendor, setEditVendor] = useState("");
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState<VemaReorderRequest | null>(null);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [approving, setApproving] = useState<VemaReorderRequest | null>(null);
  const [qtyError, setQtyError] = useState<string | null>(null);

  const vQty = () => validate(editQty, required("Quantity is required"), isInteger(), isPositive("Quantity must be greater than 0"));
  const vReason = () => validate(reason, required("A reason is required"));

  const loadStats = useCallback(() => {
    getVemaReorderStats().then(setStats).catch(() => {});
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listVemaReorderRequests({ status: tab || undefined, search: search || undefined, limit: 100 });
      setRequests(res.requests);
      setTotal(res.total);
    } catch {
      toast({ title: "Failed to load reorder proposals", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [tab, search, toast]);

  useEffect(() => { loadStats(); }, [loadStats]);
  useEffect(() => { loadList(); }, [loadList]);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    setDetailLoading(true);
    getVemaReorderRequest(selectedId)
      .then((d) => {
        setDetail(d);
        setEditQty(String(d.suggested_qty));
        setEditVendor(d.vendor_id || "");
      })
      .catch(() => toast({ title: "Failed to load request detail", variant: "destructive" }))
      .finally(() => setDetailLoading(false));
  }, [selectedId, toast]);

  const refreshAfterDecision = (id: string) => {
    setRequests((prev) => prev.filter((r) => r.id !== id));
    setTotal((t) => Math.max(0, t - 1));
    setSelectedId(null);
    setDetail(null);
    loadStats();
  };

  const handleApproveConfirm = async () => {
    if (!approving) return;
    const err = vQty();
    setQtyError(err);
    if (err) return;
    setBusy(true);
    try {
      const qty = editQty && Number(editQty) !== approving.suggested_qty ? Number(editQty) : undefined;
      const vendor_id = editVendor && editVendor !== approving.vendor_id ? editVendor : undefined;
      const res = await approveVemaReorderRequest(approving.id, { qty, vendor_id });
      toast({
        title: `${approving.request_code} approved`,
        description: `Order ${res.order_code} — vendor email ${res.vendor_email_status.toLowerCase()}`,
      });
      refreshAfterDecision(approving.id);
      setApproving(null);
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Approval failed", variant: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    if (!rejecting) return;
    const err = vReason();
    setReasonError(err);
    if (err) return;
    setBusy(true);
    try {
      await rejectVemaReorderRequest(rejecting.id, reason.trim());
      toast({ title: `${rejecting.request_code} rejected` });
      refreshAfterDecision(rejecting.id);
      setRejecting(null);
      setReason("");
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Rejection failed", variant: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center gap-2">
        <Bot size={22} className="text-primary" />
        <div>
          <h1 className="text-2xl font-heading font-bold">VEMA Auto-Reorders</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Deterministic stock-scan proposals — quantity and vendor are computed from real
            numbers; VEMA only phrases the rationale. Nothing is ordered until you decide.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Pending", value: stats?.pending ?? "—" },
          { label: "Approved", value: stats?.approved ?? "—" },
          { label: "Rejected", value: stats?.rejected ?? "—" },
          { label: "Approval rate", value: stats?.approval_rate != null ? `${stats.approval_rate}%` : "—" },
        ].map((c) => (
          <div key={c.label} className="glass-card p-4">
            <p className="text-2xl font-heading font-bold">{c.value}</p>
            <p className="text-xs text-muted-foreground">{c.label}</p>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-1 glass-card p-1">
          {STATUS_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                tab === t.key ? "btn-navy" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">{total} result{total === 1 ? "" : "s"}</span>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search request code or item…"
              className="pl-8 pr-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-40">
          <Loader2 className="animate-spin text-primary" size={32} />
        </div>
      ) : requests.length === 0 ? (
        <div className="glass-card p-10 text-center text-muted-foreground text-sm flex flex-col items-center gap-3">
          <Bot size={28} className="text-primary" />
          No reorder proposals here.
        </div>
      ) : (
        <div className="glass-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground border-b border-border">
                <th className="px-4 py-3 font-medium">Request</th>
                <th className="px-4 py-3 font-medium">Item</th>
                <th className="px-4 py-3 font-medium">Stock vs par</th>
                <th className="px-4 py-3 font-medium">Qty</th>
                <th className="px-4 py-3 font-medium">Vendor</th>
                <th className="px-4 py-3 font-medium">Est. total</th>
                <th className="px-4 py-3 font-medium">Triggered</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {requests.map((r) => {
                const pct = r.par_level ? Math.min(100, Math.round((r.stock_at_trigger / r.par_level) * 100)) : 0;
                return (
                  <tr
                    key={r.id}
                    onClick={() => setSelectedId(r.id)}
                    className="border-b border-border/50 last:border-0 hover:bg-muted/20 cursor-pointer"
                  >
                    <td className="px-4 py-3 font-mono text-xs">{r.request_code}</td>
                    <td className="px-4 py-3">{r.item_name}</td>
                    <td className="px-4 py-3 w-32">
                      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                        <div
                          className={`h-full ${pct <= 20 ? "bg-destructive" : pct <= 50 ? "bg-warning" : "bg-success"}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <p className="text-[10px] text-muted-foreground mt-1">
                        {r.stock_at_trigger} / {r.par_level} {r.unit}
                      </p>
                    </td>
                    <td className="px-4 py-3">{r.suggested_qty} {r.unit}</td>
                    <td className="px-4 py-3">
                      {r.vendor_name || <span className="text-warning">None found</span>}
                    </td>
                    <td className="px-4 py-3">{formatPKR(r.total_est)}</td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${STATUS_STYLE[r.status]}`}>
                        {r.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                      {r.status === "pending_approval" && (
                        <div className="flex gap-2 justify-end">
                          <button onClick={() => { setRejecting(r); setReason(""); setReasonError(null); }} className="text-xs text-destructive hover:underline">
                            Reject
                          </button>
                          <button
                            onClick={() => { setApproving(r); setEditQty(String(r.suggested_qty)); setEditVendor(r.vendor_id || ""); setQtyError(null); }}
                            className="text-xs text-primary hover:underline"
                          >
                            Approve
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail drawer */}
      {selectedId && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-background/60 backdrop-blur-sm" onClick={() => setSelectedId(null)} />
          <div className="relative w-full sm:w-[480px] bg-background border-l border-border shadow-xl overflow-y-auto">
            {detailLoading || !detail ? (
              <div className="flex items-center justify-center h-40">
                <Loader2 className="animate-spin text-primary" size={32} />
              </div>
            ) : (
              <div className="p-5 space-y-5">
                <div className="flex items-center justify-between">
                  <h3 className="font-heading font-bold text-lg">{detail.request_code}</h3>
                  <button onClick={() => setSelectedId(null)} className="text-muted-foreground hover:text-foreground">
                    <X size={20} />
                  </button>
                </div>
                <span className={`inline-block text-[10px] font-semibold px-2 py-0.5 rounded-full ${STATUS_STYLE[detail.status]}`}>
                  {detail.status.replace("_", " ")}
                </span>

                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">VEMA's rationale</p>
                  <p className="text-sm text-foreground glass-card p-3">{detail.rationale}</p>
                </div>

                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div><p className="text-xs text-muted-foreground">Item</p><p>{detail.item_name}</p></div>
                  <div><p className="text-xs text-muted-foreground">Category</p><p>{detail.category}</p></div>
                  <div><p className="text-xs text-muted-foreground">Stock at trigger</p><p>{detail.stock_at_trigger} {detail.unit}</p></div>
                  <div><p className="text-xs text-muted-foreground">Par level</p><p>{detail.par_level} {detail.unit}</p></div>
                  <div><p className="text-xs text-muted-foreground">Suggested qty</p><p>{detail.suggested_qty} {detail.unit}</p></div>
                  <div><p className="text-xs text-muted-foreground">Est. total</p><p>{formatPKR(detail.total_est)}</p></div>
                </div>

                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Vendor ranking</p>
                  {Object.keys(detail.vendor_score_breakdown).length === 0 ? (
                    <p className="text-sm text-warning">No eligible vendor was found — choose one manually to approve.</p>
                  ) : (
                    <div className="space-y-2">
                      {Object.values(detail.vendor_score_breakdown)
                        .sort((a, b) => b.score - a.score)
                        .map((v) => (
                          <div
                            key={v.vendor_id}
                            className={`glass-card p-3 text-sm ${v.vendor_id === detail.vendor_id ? "ring-1 ring-primary" : ""}`}
                          >
                            <div className="flex items-center justify-between">
                              <p className="font-medium">
                                {v.vendor_name}
                                {v.vendor_id === detail.vendor_id && (
                                  <span className="ml-2 text-[10px] text-primary">Recommended</span>
                                )}
                              </p>
                              <p className="text-xs font-mono">score {v.score.toFixed(2)}</p>
                            </div>
                            <p className="text-xs text-muted-foreground mt-1">
                              {formatPKR(v.unit_price)}/unit · {v.lead_time_days}-day lead time · accept rate{" "}
                              {v.accept_rate == null ? "n/a" : `${Math.round(v.accept_rate * 100)}%`}
                            </p>
                          </div>
                        ))}
                    </div>
                  )}
                </div>

                {detail.status !== "pending_approval" && (
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">Decision</p>
                    <p className="text-sm">{detail.decision_note || "—"}</p>
                    {detail.resulting_order_id && (
                      <p className="text-xs text-muted-foreground mt-1">Order created — see Order Tracking.</p>
                    )}
                  </div>
                )}

                {detail.status === "pending_approval" && (
                  <div className="space-y-3 pt-3 border-t border-border">
                    <div>
                      <label className="text-xs text-muted-foreground">Quantity (edit if needed)</label>
                      <input
                        type="number"
                        value={editQty}
                        onChange={(e) => setEditQty(e.target.value)}
                        onBlur={() => setQtyError(vQty())}
                        className={`w-full mt-1 px-3 py-2 text-sm rounded-lg bg-muted/50 border focus:outline-none focus:ring-2 focus:ring-primary/50 ${qtyError ? errorInputClass : "border-border"}`}
                      />
                      <FieldError message={qtyError} />
                    </div>
                    {Object.keys(detail.vendor_score_breakdown).length > 0 && (
                      <div>
                        <label className="text-xs text-muted-foreground">Vendor</label>
                        <select
                          value={editVendor}
                          onChange={(e) => setEditVendor(e.target.value)}
                          className="w-full mt-1 px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                        >
                          {Object.values(detail.vendor_score_breakdown).map((v) => (
                            <option key={v.vendor_id} value={v.vendor_id}>
                              {v.vendor_name} (score {v.score.toFixed(2)})
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                    <div className="flex gap-2">
                      <button
                        onClick={() => { setRejecting(detail); setReason(""); setReasonError(null); }}
                        className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-destructive/30 text-destructive hover:bg-destructive/10"
                      >
                        <XCircle size={14} /> Reject
                      </button>
                      <button
                        onClick={() => { setApproving(detail); setQtyError(null); }}
                        className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium btn-navy"
                      >
                        <CheckCircle2 size={14} /> Approve
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Approve confirm dialog */}
      {approving && (
        <div
          className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-[60] p-4"
          onClick={() => setApproving(null)}
        >
          <div className="glass-card p-6 w-full max-w-md glow-cyan animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-heading font-bold text-lg">Approve {approving.request_code}</h3>
              <button onClick={() => setApproving(null)} className="text-muted-foreground hover:text-foreground">
                <X size={20} />
              </button>
            </div>
            <div className="text-sm space-y-1 mb-4">
              <p><span className="text-muted-foreground">Item:</span> {approving.item_name}</p>
              <p><span className="text-muted-foreground">Quantity:</span> {editQty || approving.suggested_qty} {approving.unit}</p>
              <p>
                <span className="text-muted-foreground">Vendor:</span>{" "}
                {Object.values(approving.vendor_score_breakdown).find(
                  (v) => v.vendor_id === (editVendor || approving.vendor_id)
                )?.vendor_name || "— (choose one in the drawer before approving)"}
              </p>
              <p><span className="text-muted-foreground">Est. total:</span> {formatPKR(approving.total_est)}</p>
            </div>
            <p className="text-xs text-warning bg-warning/10 rounded-lg p-2.5 mb-4">
              Approving creates a real order and emails the vendor an Accept/Reject link.
            </p>
            <button
              onClick={handleApproveConfirm}
              disabled={busy}
              className="w-full py-2.5 font-semibold rounded-lg btn-navy flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
              Confirm Approval
            </button>
          </div>
        </div>
      )}

      {/* Reject dialog */}
      {rejecting && (
        <div
          className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-[60] p-4"
          onClick={() => setRejecting(null)}
        >
          <div className="glass-card p-6 w-full max-w-md glow-cyan animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-heading font-bold text-lg">Reject {rejecting.request_code}</h3>
              <button onClick={() => setRejecting(null)} className="text-muted-foreground hover:text-foreground">
                <X size={20} />
              </button>
            </div>
            <p className="text-sm text-muted-foreground mb-4">No order will be created. A reason is required.</p>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              onBlur={() => setReasonError(vReason())}
              rows={3}
              placeholder="Reason (required)…"
              className={`w-full px-4 py-2.5 rounded-lg bg-muted/50 border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm ${reasonError ? errorInputClass : "border-border"}`}
            />
            <FieldError message={reasonError} />
            <button
              onClick={handleReject}
              disabled={busy || !reason.trim()}
              className="w-full mt-4 py-2.5 font-semibold rounded-lg bg-destructive text-destructive-foreground flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : <XCircle size={16} />}
              Confirm Rejection
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default VemaReorders;
