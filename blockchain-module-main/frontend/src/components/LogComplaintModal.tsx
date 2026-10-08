// src/components/LogComplaintModal.tsx
// CR / admin — log a complaint on a customer's behalf (walk-in, phone-in).
// Posts to /api/complaints/manual; the ticket then routes through the same
// severity tiers as a VEMA-generated one.
import { useEffect, useMemo, useState } from "react";
import { X, Loader2, ClipboardList } from "lucide-react";
import { createManualComplaint, getComplaintTaxonomy } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

import ModalPortal from "@/components/ModalPortal";
interface Props {
  onClose: () => void;
  onCreated: () => void;
}

const SEVERITIES = ["small", "medium", "critical"] as const;

const LogComplaintModal = ({ onClose, onCreated }: Props) => {
  const { toast } = useToast();
  const [taxonomy, setTaxonomy] = useState<Record<string, string[]>>({});
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [subtype, setSubtype] = useState("");
  const [severity, setSeverity] = useState<(typeof SEVERITIES)[number]>("medium");
  const [customerName, setCustomerName] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [area, setArea] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getComplaintTaxonomy()
      .then((t) => {
        setTaxonomy(t);
        const first = Object.keys(t)[0];
        if (first) { setCategory(first); setSubtype(t[first][0] ?? ""); }
      })
      .catch(() => toast({ title: "Could not load the complaint taxonomy", variant: "destructive" }));
  }, [toast]);

  const subtypes = useMemo(() => taxonomy[category] ?? [], [taxonomy, category]);

  const onCategoryChange = (c: string) => {
    setCategory(c);
    setSubtype((taxonomy[c] ?? [])[0] ?? "");
  };

  const canSubmit = description.trim() && category && subtype && !saving;

  const submit = async () => {
    if (!canSubmit) return;
    setSaving(true);
    try {
      const res = await createManualComplaint({
        description: description.trim(),
        category,
        subtype,
        severity,
        customer_name: customerName.trim() || undefined,
        customer_email: customerEmail.trim() || undefined,
        area: area.trim() || undefined,
      });
      toast({ title: `Ticket ${res.ticket_code} logged` });
      onCreated();
      onClose();
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Failed to log complaint", variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  const field = "w-full px-3 py-2 rounded-lg bg-muted/50 border border-border text-sm focus:outline-none focus:ring-2 focus:ring-primary/50";

  return (
    <ModalPortal><div className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="glass-card w-full max-w-lg max-h-[85vh] flex flex-col animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-5 border-b border-border flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-2">
            <ClipboardList size={18} className="text-primary" />
            <p className="font-heading font-bold">Log a Complaint</p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto scroll-thin p-5 space-y-4">
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">What is the complaint?</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="e.g. Customer phoned in — no power in street 12, F-8 since 2pm."
              className={`${field} mt-1 resize-y`}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Category</label>
              <select value={category} onChange={(e) => onCategoryChange(e.target.value)} className={`${field} mt-1`}>
                {Object.keys(taxonomy).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Subtype</label>
              <select value={subtype} onChange={(e) => setSubtype(e.target.value)} className={`${field} mt-1`}>
                {subtypes.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Severity</label>
            <div className="flex gap-2 mt-1">
              {SEVERITIES.map((s) => (
                <button
                  key={s}
                  onClick={() => setSeverity(s)}
                  className={`flex-1 py-2 text-sm font-medium rounded-lg border capitalize transition-colors ${
                    severity === s ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted/50"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground mt-1">
              Medium and critical tickets are escalated immediately; small tickets attempt auto-resolution first.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Customer name</label>
              <input value={customerName} onChange={(e) => setCustomerName(e.target.value)} placeholder="Optional" className={`${field} mt-1`} />
            </div>
            <div>
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Area</label>
              <input value={area} onChange={(e) => setArea(e.target.value)} placeholder="Optional — e.g. G-9/1" className={`${field} mt-1`} />
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Customer email</label>
            <input value={customerEmail} onChange={(e) => setCustomerEmail(e.target.value)} placeholder="Optional" className={`${field} mt-1`} />
          </div>
        </div>

        <div className="p-5 border-t border-border flex gap-2 flex-shrink-0">
          <button onClick={onClose} className="flex-1 py-2 text-sm font-medium border border-border rounded-lg">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!canSubmit}
            className="flex-1 py-2 text-sm font-medium btn-navy flex items-center justify-center gap-1.5 disabled:opacity-50"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <ClipboardList size={14} />}
            Log Complaint
          </button>
        </div>
      </div>
    </div></ModalPortal>
  );
};

export default LogComplaintModal;
