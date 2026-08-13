// src/components/OrderDetailModal.tsx
import { useState, useEffect } from "react";
import {
  X, Loader2, CheckCircle2, Package, Truck, FileText,
  Clock, MapPin, ShieldCheck, AlertTriangle,
} from "lucide-react";
import {
  getOrder, signContract, submitDeliveryCheckin,
  ProcurementOrder, DeliveryCheckin, ContractAuditEntry,
} from "@/services/api";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/contexts/AuthContext";

interface Props {
  order: ProcurementOrder;
  onClose: () => void;
  onUpdate: () => void;
}

type ModalTab = "overview" | "contract" | "tracking" | "checkin";

const STAGE_STEPS = [
  "Pending Verification",
  "Vendor Notified",
  "Email Confirmed",
  "Contract Signed",
  "Manufacturing",
  "Shipping",
  "Delivered",
];

const StatusPill = ({ v, label }: { v: boolean; label: string }) => (
  <span className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${
    v ? "bg-success/10 text-success" : "bg-muted text-muted-foreground"
  }`}>
    {v ? <CheckCircle2 size={10} /> : <Clock size={10} />} {label}
  </span>
);

const OrderDetailModal = ({ order: initialOrder, onClose, onUpdate }: Props) => {
  const { user } = useAuth();
  const { toast } = useToast();
  const [tab, setTab] = useState<ModalTab>("overview");
  const [order, setOrder]     = useState(initialOrder);
  const [checkins, setCheckins] = useState<DeliveryCheckin[]>([]);
  const [audit, setAudit]     = useState<ContractAuditEntry[]>([]);
  const [loading, setLoading] = useState(true);

  // Check-in form state
  const [ciStatus, setCiStatus]   = useState("Arrived at Warehouse");
  const [ciQty, setCiQty]         = useState(order.quantity);
  const [ciCond, setCiCond]       = useState<"Good" | "Partial" | "Damaged">("Good");
  const [ciLoc, setCiLoc]         = useState("Main Warehouse");
  const [ciNotes, setCiNotes]     = useState("");
  const [ciFinal, setCiFinal]     = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [signing, setSigning]     = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const detail = await getOrder(order.id);
        setOrder(detail.order);
        setCheckins(detail.checkins);
        setAudit(detail.audit);
      } catch { /* use initial data */ }
      finally { setLoading(false); }
    })();
  }, [order.id]);

  const handleSign = async () => {
    setSigning(true);
    try {
      await signContract(order.id, user?.name || "Operator");
      toast({ title: "✅ Contract signed successfully" });
      const detail = await getOrder(order.id);
      setOrder(detail.order);
      setAudit(detail.audit);
      onUpdate();
    } catch (e: unknown) {
      toast({ title: "Sign failed", description: String(e), variant: "destructive" });
    } finally { setSigning(false); }
  };

  const handleCheckin = async () => {
    setSubmitting(true);
    try {
      const res = await submitDeliveryCheckin(order.id, {
        location:          ciLoc,
        status:            ciStatus,
        quantity_received: ciQty,
        condition:         ciCond,
        notes:             ciNotes,
        is_final:          ciFinal,
        checked_by:        user?.name,
      });
      toast({
        title: ciFinal && res.contract_executed
          ? "✅ Delivery accepted & smart contract executed!"
          : "✅ Check-in recorded",
      });
      const detail = await getOrder(order.id);
      setOrder(detail.order);
      setCheckins(detail.checkins);
      setAudit(detail.audit);
      onUpdate();
    } catch (e: unknown) {
      toast({ title: "Check-in failed", description: String(e), variant: "destructive" });
    } finally { setSubmitting(false); }
  };

  const stageIdx = STAGE_STEPS.indexOf(order.stage);

  const tabs: { key: ModalTab; label: string; icon: React.ElementType }[] = [
    { key: "overview",  label: "Overview",  icon: Package },
    { key: "contract",  label: "Contract",  icon: FileText },
    { key: "tracking",  label: "Tracking",  icon: Truck },
    { key: "checkin",   label: "Check-In",  icon: ShieldCheck },
  ];

  return (
    <div
      className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="glass-card w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col glow-cyan animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal header */}
        <div className="flex items-center justify-between p-5 border-b border-border/50">
          <div>
            <h3 className="font-heading font-bold text-lg">{order.order_code}</h3>
            <p className="text-xs text-muted-foreground mt-0.5">{order.item_name} · {order.vendor_name}</p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={20} />
          </button>
        </div>

        {/* Status pills */}
        <div className="flex gap-2 flex-wrap px-5 pt-3">
          <StatusPill v={order.vendor_email_sent} label="Email Sent" />
          <StatusPill v={order.vendor_confirmed} label="Vendor Confirmed" />
          <StatusPill v={order.contract_status === "Signed" || order.contract_status === "Executed"} label="Contract Signed" />
          <StatusPill v={order.contract_status === "Executed"} label="Contract Executed" />
          <StatusPill v={order.delivery_confirmed} label="Delivered" />
        </div>

        {/* Stage stepper */}
        <div className="px-5 pt-3 pb-1">
          <div className="flex items-center gap-0.5 overflow-x-auto pb-1">
            {STAGE_STEPS.map((s, i) => (
              <div key={s} className="flex items-center flex-shrink-0">
                <div className="flex flex-col items-center gap-1">
                  <div className={`w-3 h-3 rounded-full ${
                    i < stageIdx ? "bg-success" : i === stageIdx ? "bg-primary" : "bg-muted/40"
                  }`} />
                  <span className="text-[9px] text-muted-foreground whitespace-nowrap">{s.split(" ")[0]}</span>
                </div>
                {i < STAGE_STEPS.length - 1 && (
                  <div className={`h-px w-6 mb-3 ${i < stageIdx ? "bg-success" : "bg-muted/30"}`} />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Sub-tabs */}
        <div className="flex gap-1 px-5 pb-2">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
                tab === t.key ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <t.icon size={12} /> {t.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading && (
            <div className="flex justify-center py-8">
              <Loader2 className="animate-spin text-primary" size={28} />
            </div>
          )}

          {/* ── OVERVIEW ── */}
          {!loading && tab === "overview" && (
            <div className="space-y-3">
              {[
                ["Order Code",      order.order_code],
                ["Item",            order.item_name],
                ["Quantity",        `${order.quantity.toLocaleString()} ${order.unit}`],
                ["Vendor",          order.vendor_name],
                ["Vendor Email",    order.vendor_email],
                ["Trigger",         order.trigger_type],
                ["Unit Price",      order.unit_price ? `USD ${order.unit_price.toLocaleString()}` : "—"],
                ["Total Price",     order.total_price ? `USD ${order.total_price.toLocaleString()}` : "—"],
                ["Expected Delivery", order.expected_delivery],
                ["Actual Delivery",   order.actual_delivery || "—"],
                ["Delivery Condition", order.delivery_condition || "—"],
                ["Stage",           order.stage],
                ["Contract Status", order.contract_status],
                ["Created",         new Date(order.created_at).toLocaleString()],
              ].map(([label, val]) => (
                <div key={label} className="flex justify-between py-1.5 border-b border-border/30 text-sm">
                  <span className="text-muted-foreground">{label}</span>
                  <span className="font-medium text-right max-w-[60%]">{val}</span>
                </div>
              ))}
            </div>
          )}

          {/* ── CONTRACT ── */}
          {!loading && tab === "contract" && (
            <div className="space-y-4">
              {order.contract_hash ? (
                <>
                  <div className="glass-card p-4 space-y-2">
                    <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">Contract Hash</p>
                    <p className="text-xs font-mono break-all text-primary">{order.contract_hash}</p>
                  </div>
                  {order.smart_contract_data && (
                    <div className="glass-card p-4">
                      <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider mb-2">Smart Contract Data</p>
                      <pre className="text-xs font-mono text-muted-foreground overflow-x-auto whitespace-pre-wrap">
                        {JSON.stringify(order.smart_contract_data, null, 2)}
                      </pre>
                    </div>
                  )}
                  {/* Sign button — show if not yet operator-signed */}
                  {order.contract_status === "Pending" && (
                    <button
                      onClick={handleSign}
                      disabled={signing}
                      className="w-full py-2.5 btn-navy font-semibold flex items-center justify-center gap-2"
                    >
                      {signing && <Loader2 size={14} className="animate-spin" />}
                      <ShieldCheck size={14} /> Sign Contract as Operator
                    </button>
                  )}
                  {/* Audit log */}
                  <div>
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Audit Log</p>
                    <div className="space-y-2">
                      {audit.map((a) => (
                        <div key={a.id} className="glass-card p-3 flex items-start gap-2">
                          <CheckCircle2 size={14} className="text-success mt-0.5 flex-shrink-0" />
                          <div>
                            <p className="text-xs font-medium">{a.action}</p>
                            <p className="text-[10px] text-muted-foreground font-mono">{a.tx_hash?.slice(0, 20)}…</p>
                            <p className="text-[10px] text-muted-foreground">{new Date(a.performed_at).toLocaleString()}</p>
                          </div>
                        </div>
                      ))}
                      {audit.length === 0 && (
                        <p className="text-xs text-muted-foreground text-center py-4">No audit entries yet.</p>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  <FileText size={32} className="mx-auto mb-2 opacity-40" />
                  No smart contract yet. Contract is created after vendor confirms the order via email.
                </div>
              )}
            </div>
          )}

          {/* ── TRACKING ── */}
          {!loading && tab === "tracking" && (
            <div className="space-y-3">
              {(order.tracking_events || []).length === 0 ? (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  <Truck size={32} className="mx-auto mb-2 opacity-40" />
                  No tracking events yet.
                </div>
              ) : (
                <div className="relative">
                  <div className="absolute left-3 top-0 bottom-0 w-px bg-border/50" />
                  {(order.tracking_events || []).map((evt, i) => (
                    <div key={i} className="relative pl-8 pb-4">
                      <div className="absolute left-1.5 top-1.5 w-3 h-3 rounded-full bg-primary border-2 border-card" />
                      <div className="glass-card p-3">
                        <div className="flex items-center gap-2 mb-1">
                          <MapPin size={12} className="text-muted-foreground" />
                          <span className="text-xs font-medium">{evt.location}</span>
                          <span className="text-[10px] text-muted-foreground ml-auto">
                            {new Date(evt.ts).toLocaleString()}
                          </span>
                        </div>
                        <p className="text-xs text-primary font-medium">{evt.status}</p>
                        {evt.notes && <p className="text-xs text-muted-foreground mt-1">{evt.notes}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {checkins.length > 0 && (
                <>
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider pt-2">Check-In History</p>
                  {checkins.map((c) => (
                    <div key={c.id} className="glass-card p-3 flex items-start gap-3">
                      {c.condition === "Good" ? (
                        <CheckCircle2 size={14} className="text-success mt-0.5 flex-shrink-0" />
                      ) : (
                        <AlertTriangle size={14} className="text-warning mt-0.5 flex-shrink-0" />
                      )}
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-xs font-medium">{c.status}</p>
                          {c.is_final && (
                            <span className="text-[9px] bg-success/10 text-success px-1.5 py-0.5 rounded-full">Final</span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {c.quantity_received} units · Condition: {c.condition} · {c.location}
                        </p>
                        {c.notes && <p className="text-xs text-muted-foreground mt-0.5 italic">{c.notes}</p>}
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          {new Date(c.checkin_at).toLocaleString()}
                        </p>
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
          )}

          {/* ── CHECK-IN FORM ── */}
          {!loading && tab === "checkin" && (
            <div className="space-y-4">
              {order.stage === "Delivered" ? (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  <CheckCircle2 size={32} className="mx-auto mb-2 text-success opacity-80" />
                  This order has been fully delivered and closed.
                </div>
              ) : (
                <>
                  <p className="text-xs text-muted-foreground">
                    Record each delivery event. Set <strong>Final Check-In</strong> when the full order is received — this automatically executes the smart contract if condition is Good.
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-muted-foreground mb-1">Status</label>
                      <select
                        value={ciStatus}
                        onChange={(e) => setCiStatus(e.target.value)}
                        className="w-full px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                      >
                        <option>Arrived at Warehouse</option>
                        <option>Inspected</option>
                        <option>Accepted</option>
                        <option>Rejected</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted-foreground mb-1">Condition</label>
                      <select
                        value={ciCond}
                        onChange={(e) => setCiCond(e.target.value as "Good" | "Partial" | "Damaged")}
                        className="w-full px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                      >
                        <option value="Good">Good</option>
                        <option value="Partial">Partial</option>
                        <option value="Damaged">Damaged</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted-foreground mb-1">Qty Received</label>
                      <input
                        type="number"
                        value={ciQty}
                        onChange={(e) => setCiQty(Number(e.target.value))}
                        className="w-full px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-muted-foreground mb-1">Location</label>
                      <input
                        value={ciLoc}
                        onChange={(e) => setCiLoc(e.target.value)}
                        className="w-full px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-muted-foreground mb-1">Notes</label>
                    <textarea
                      value={ciNotes}
                      onChange={(e) => setCiNotes(e.target.value)}
                      rows={2}
                      className="w-full px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
                      placeholder="Inspection notes, discrepancies, etc."
                    />
                  </div>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={ciFinal}
                      onChange={(e) => setCiFinal(e.target.checked)}
                      className="w-4 h-4 accent-primary"
                    />
                    <span className="text-sm font-medium">Final Check-In</span>
                    <span className="text-xs text-muted-foreground">(closes order + auto-executes contract if Good)</span>
                  </label>
                  {ciCond === "Damaged" && ciFinal && (
                    <div className="flex items-start gap-2 p-3 bg-destructive/5 border border-destructive/20 rounded-lg">
                      <AlertTriangle size={14} className="text-destructive mt-0.5 flex-shrink-0" />
                      <p className="text-xs text-destructive">
                        Damaged + Final will reject the smart contract. Stock will NOT be updated.
                      </p>
                    </div>
                  )}
                  <button
                    onClick={handleCheckin}
                    disabled={submitting}
                    className="w-full py-2.5 btn-navy font-semibold flex items-center justify-center gap-2"
                  >
                    {submitting && <Loader2 size={14} className="animate-spin" />}
                    {ciFinal ? "Submit Final Check-In" : "Record Check-In Event"}
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default OrderDetailModal;
