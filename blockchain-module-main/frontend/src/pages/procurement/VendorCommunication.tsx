// src/pages/procurement/VendorCommunication.tsx
import { useEffect, useState, useCallback } from "react";
import { Mail, RefreshCw, Loader2, CheckCircle2, XCircle, Clock } from "lucide-react";
import {
  listOrders, getVendorCommLog, resendVendorEmail,
  ProcurementOrder, VendorCommLogEntry,
} from "@/services/api";
import { useToast } from "@/hooks/use-toast";

const decisionBadge = (order: ProcurementOrder) => {
  if (order.vendor_decision === "Accepted")
    return <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-success/10 text-success"><CheckCircle2 size={11} /> Accepted</span>;
  if (order.vendor_decision === "Rejected")
    return <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-destructive/10 text-destructive"><XCircle size={11} /> Rejected</span>;
  if (order.pm_approval_status === "Approved")
    return <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-warning/10 text-warning"><Clock size={11} /> Awaiting vendor</span>;
  return null;
};

const VendorCommunication = () => {
  const { toast } = useToast();
  const [orders, setOrders] = useState<ProcurementOrder[]>([]);
  const [selected, setSelected] = useState<ProcurementOrder | null>(null);
  const [log, setLog] = useState<VendorCommLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [logLoading, setLogLoading] = useState(false);
  const [resending, setResending] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await listOrders({ limit: 100 });
      const withVendorEmail = res.orders.filter((o) => o.vendor_response_token);
      setOrders(withVendorEmail);
      if (withVendorEmail.length > 0) setSelected((prev) => prev || withVendorEmail[0]);
    } catch {
      toast({ title: "Failed to load orders", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selected) return;
    setLogLoading(true);
    getVendorCommLog(selected.id)
      .then((res) => setLog(res.log))
      .catch(() => setLog([]))
      .finally(() => setLogLoading(false));
  }, [selected]);

  const handleResend = async () => {
    if (!selected) return;
    setResending(true);
    try {
      const res = await resendVendorEmail(selected.id);
      toast({ title: res.message });
      const logRes = await getVendorCommLog(selected.id);
      setLog(logRes.log);
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Resend failed" });
    } finally {
      setResending(false);
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
    <div className="space-y-6 animate-slide-up">
      <div>
        <h1 className="text-2xl font-heading font-bold">Vendor Communication</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Every reorder email sent via n8n, and each vendor's Accept/Reject status in
          near-real time.
        </p>
      </div>

      {orders.length === 0 ? (
        <div className="glass-card p-10 text-center text-muted-foreground text-sm flex flex-col items-center gap-3">
          <Mail size={28} className="text-primary" />
          No vendor emails have been sent yet — approve a reorder to see it here.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Order list */}
          <div className="lg:col-span-1 space-y-2">
            {orders.map((o) => (
              <button
                key={o.id}
                onClick={() => setSelected(o)}
                className={`w-full text-left glass-card p-3 transition-all ${
                  selected?.id === o.id ? "ring-2 ring-primary/50" : "glow-cyan-hover"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-mono text-muted-foreground">{o.order_code}</span>
                  {decisionBadge(o)}
                </div>
                <p className="text-sm font-medium mt-1 truncate">{o.item_name}</p>
                <p className="text-xs text-muted-foreground truncate">{o.vendor_name}</p>
              </button>
            ))}
          </div>

          {/* Detail panel */}
          <div className="lg:col-span-2">
            {selected && (
              <div className="glass-card p-5 space-y-4">
                <div className="flex items-start justify-between flex-wrap gap-3">
                  <div>
                    <p className="font-heading font-bold text-lg">{selected.order_code}</p>
                    <p className="text-sm text-muted-foreground">
                      {selected.item_name} — {selected.quantity} {selected.unit} to {selected.vendor_name}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {decisionBadge(selected)}
                    <button
                      onClick={handleResend}
                      disabled={resending || !!selected.vendor_decision}
                      className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium border border-border rounded-lg hover:bg-muted/30 disabled:opacity-50"
                    >
                      {resending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                      Resend
                    </button>
                  </div>
                </div>

                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                    Send History
                  </p>
                  {logLoading ? (
                    <Loader2 className="animate-spin text-primary" size={20} />
                  ) : log.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No send history yet.</p>
                  ) : (
                    <div className="space-y-2">
                      {log.map((entry) => (
                        <div key={entry.id} className="flex items-center justify-between text-sm bg-muted/30 rounded-lg px-3 py-2">
                          <span className="flex items-center gap-2">
                            <Mail size={14} className="text-muted-foreground" />
                            {entry.channel}
                            <span
                              className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${
                                entry.status === "Sent"
                                  ? "bg-success/10 text-success"
                                  : entry.status === "Failed"
                                  ? "bg-destructive/10 text-destructive"
                                  : "bg-warning/10 text-warning"
                              }`}
                            >
                              {entry.status}
                            </span>
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {new Date(entry.sent_at).toLocaleString()}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default VendorCommunication;
