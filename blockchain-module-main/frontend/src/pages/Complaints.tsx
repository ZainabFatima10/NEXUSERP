// src/pages/Complaints.tsx
import { useEffect, useMemo, useState, useCallback } from "react";
import { CheckCircle2, AlertTriangle, Mic, X, Loader2 } from "lucide-react";
import { Complaint, getComplaints, resolveComplaint } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

import ModalPortal from "@/components/ModalPortal";
const severityStyle: Record<string, string> = {
  critical: "bg-destructive/10 text-destructive",
  medium: "bg-warning/10 text-warning",
  small: "bg-muted text-muted-foreground",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (hours < 24) return `${hours}h ago`;
  return `${days}d ago`;
}

const Complaints = () => {
  const { toast } = useToast();
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"open" | "resolved">("open");
  const [resolving, setResolving] = useState<Complaint | null>(null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await getComplaints({ limit: 200 });
      setComplaints(res.tickets);
    } catch {
      toast({ title: "Failed to load complaints", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const open = useMemo(
    () => complaints.filter((c) => c.status === "open" || c.status === "escalated"),
    [complaints]
  );
  const resolved = useMemo(
    () => complaints.filter((c) => c.status === "resolved" || c.status === "auto_resolved"),
    [complaints]
  );

  const handleResolve = async () => {
    if (!resolving) return;
    setSaving(true);
    try {
      await resolveComplaint(resolving.id, note || "Marked resolved by Admin.");
      toast({ title: `✅ ${resolving.ticket_code} marked resolved` });
      setResolving(null);
      setNote("");
      load();
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Failed to resolve", variant: "destructive" });
    } finally {
      setSaving(false);
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
    <div className="space-y-6 animate-slide-up max-w-5xl">
      <div>
        <h1 className="text-2xl font-heading font-bold">User Complaints</h1>
        <p className="text-muted-foreground text-sm mt-1">VEMA-integrated complaint tracking and resolution.</p>
      </div>

      <div className="flex items-start gap-2 glass-card p-3 border-accent-cyan">
        <Mic size={16} className="text-primary mt-0.5 flex-shrink-0" />
        <p className="text-xs text-muted-foreground">
          Complaints are submitted by customers through <strong className="text-foreground">VEMA</strong> (voice or
          chat, Customer Portal) or logged manually by a Customer Representative. Medium/critical tickets are
          auto-escalated and reminded every 30/15 minutes until resolved.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-muted/30 p-1 w-fit" style={{ borderRadius: 20 }}>
        {[
          { key: "open" as const, label: `Open (${open.length})` },
          { key: "resolved" as const, label: `Resolved (${resolved.length})` },
        ].map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{ borderRadius: 20 }}
            className={`px-4 py-2 text-sm font-medium transition-all ${
              tab === t.key ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Open list */}
      {tab === "open" && (
        <div className="space-y-3">
          {open.length === 0 && (
            <div className="glass-card p-10 text-center text-muted-foreground text-sm">
              No open complaints. 🎉
            </div>
          )}
          {open.map((c) => (
            <div key={c.id} className="glass-card p-4 flex items-start justify-between gap-4 flex-wrap glow-cyan-hover">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap mb-1.5">
                  <span className="text-xs font-mono text-muted-foreground">{c.ticket_code}</span>
                  <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${severityStyle[c.severity]}`}>
                    {c.severity}
                  </span>
                  <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    {c.category}
                  </span>
                  {c.vema_triggered && (
                    <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-accent-cyan/10 text-accent-cyan">
                      <Mic size={10} /> VEMA-Triggered
                    </span>
                  )}
                  {c.status === "escalated" && (
                    <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-destructive/10 text-destructive">
                      <AlertTriangle size={11} /> Escalated
                    </span>
                  )}
                </div>
                <p className="text-sm text-foreground">{c.description}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {c.subtype} · {c.area || "Area unknown"} · {timeAgo(c.created_at)}
                  {c.customer_name ? ` · ${c.customer_name}` : ""}
                </p>
              </div>
              <button
                onClick={() => setResolving(c)}
                className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium btn-navy flex-shrink-0"
              >
                <CheckCircle2 size={14} /> Resolve
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Resolved list */}
      {tab === "resolved" && (
        <div className="space-y-3">
          {resolved.length === 0 && (
            <div className="glass-card p-10 text-center text-muted-foreground text-sm">No resolved complaints yet.</div>
          )}
          {resolved.map((c) => (
            <div key={c.id} className="glass-card p-4">
              <div className="flex items-center gap-2 flex-wrap mb-1.5">
                <span className="text-xs font-mono text-muted-foreground">{c.ticket_code}</span>
                <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${severityStyle[c.severity]}`}>
                  {c.severity}
                </span>
                {c.vema_triggered && (
                  <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-accent-cyan/10 text-accent-cyan">
                    <Mic size={10} /> VEMA-Triggered
                  </span>
                )}
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-success/10 text-success">
                  {c.status === "auto_resolved" ? "Auto-Resolved" : "Resolved"}
                </span>
              </div>
              <p className="text-sm text-foreground">{c.description}</p>
              {c.resolution && (
                <div className="mt-2 bg-muted/40 rounded-lg px-3 py-2">
                  <p className="text-xs text-foreground">
                    <strong>Resolution:</strong> {c.resolution}
                  </p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">
                    {c.resolved_at && `Resolved ${new Date(c.resolved_at).toLocaleString()}`}
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Resolve modal */}
      {resolving && (
        <ModalPortal><div
          className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={() => setResolving(null)}
        >
          <div className="glass-card p-6 w-full max-w-md glow-cyan animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-heading font-bold text-lg">Resolve {resolving.ticket_code}</h3>
              <button onClick={() => setResolving(null)} className="text-muted-foreground hover:text-foreground">
                <X size={20} />
              </button>
            </div>
            <p className="text-sm text-muted-foreground mb-4">{resolving.description}</p>
            <label className="block text-sm font-medium text-muted-foreground mb-1.5">Resolution note</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="Describe how this was resolved…"
              className="w-full px-4 py-2.5 rounded-lg bg-muted/50 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm"
            />
            <button
              onClick={handleResolve}
              disabled={saving}
              className="w-full mt-4 py-2.5 font-semibold btn-navy flex items-center justify-center gap-2 disabled:opacity-60"
            >
              {saving ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
              Confirm Resolution
            </button>
          </div>
        </div></ModalPortal>
      )}
    </div>
  );
};

export default Complaints;
