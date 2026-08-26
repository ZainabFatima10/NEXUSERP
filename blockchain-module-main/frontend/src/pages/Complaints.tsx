// src/pages/Complaints.tsx
import { useMemo, useState } from "react";
import { CheckCircle2, AlertTriangle, Mic, X, Info } from "lucide-react";
import { Complaint, SEED_COMPLAINTS, SLA_HOURS } from "@/data/mockComplaints";
import { useToast } from "@/hooks/use-toast";

const categoryStyle: Record<string, string> = {
  "Power Outage": "bg-destructive/10 text-destructive",
  Billing: "bg-accent-violet/10 text-accent-violet",
  Fault: "bg-warning/10 text-warning",
  Other: "bg-muted text-muted-foreground",
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
  const [complaints, setComplaints] = useState<Complaint[]>(SEED_COMPLAINTS);
  const [tab, setTab] = useState<"unresolved" | "resolved">("unresolved");
  const [resolving, setResolving] = useState<Complaint | null>(null);
  const [note, setNote] = useState("");

  const unresolved = useMemo(() => complaints.filter((c) => !c.resolved), [complaints]);
  const resolved = useMemo(() => complaints.filter((c) => c.resolved), [complaints]);

  const handleResolve = () => {
    if (!resolving) return;
    setComplaints((prev) =>
      prev.map((c) =>
        c.id === resolving.id
          ? {
              ...c,
              resolved: true,
              resolution: note || "Marked resolved by Admin.",
              resolvedBy: "Admin User",
              resolvedAt: new Date().toISOString(),
            }
          : c
      )
    );
    toast({ title: `✅ ${resolving.ticket} marked resolved` });
    setResolving(null);
    setNote("");
  };

  return (
    <div className="space-y-6 animate-slide-up max-w-5xl">
      <div>
        <h1 className="text-2xl font-heading font-bold">User Complaints</h1>
        <p className="text-muted-foreground text-sm mt-1">VEMA-integrated complaint tracking and resolution.</p>
      </div>

      <div className="flex items-start gap-2 glass-card p-3 border-accent-cyan">
        <Mic size={16} className="text-primary mt-0.5 flex-shrink-0" />
        <p className="text-xs text-muted-foreground">
          Complaints are submitted by users through <strong className="text-foreground">VEMA</strong> (Voice &amp; Email
          Management Agent) and auto-logged here. Unresolved tickets are auto-escalated after a {SLA_HOURS}-hour SLA.
        </p>
      </div>

      <div className="flex items-start gap-2 glass-card p-3 bg-warning/5 border-warning/30">
        <Info size={16} className="text-warning mt-0.5 flex-shrink-0" />
        <p className="text-xs text-muted-foreground">
          The VEMA voice pipeline is still in development, so this screen is running on representative demo data — the
          Resolve action below works locally in your browser. It will switch to live tickets once the VEMA backend ships.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-muted/30 p-1 w-fit" style={{ borderRadius: 20 }}>
        {[
          { key: "unresolved" as const, label: `Unresolved (${unresolved.length})` },
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

      {/* Unresolved list */}
      {tab === "unresolved" && (
        <div className="space-y-3">
          {unresolved.length === 0 && (
            <div className="glass-card p-10 text-center text-muted-foreground text-sm">
              No unresolved complaints. 🎉
            </div>
          )}
          {unresolved.map((c) => (
            <div key={c.id} className="glass-card p-4 flex items-start justify-between gap-4 flex-wrap glow-cyan-hover">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap mb-1.5">
                  <span className="text-xs font-mono text-muted-foreground">{c.ticket}</span>
                  <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${categoryStyle[c.category]}`}>
                    {c.category}
                  </span>
                  {c.escalated && (
                    <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-destructive/10 text-destructive">
                      <AlertTriangle size={11} /> Escalated
                    </span>
                  )}
                </div>
                <p className="text-sm text-foreground">{c.description}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Area: {c.area} · {timeAgo(c.createdAt)}
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
                <span className="text-xs font-mono text-muted-foreground">{c.ticket}</span>
                <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${categoryStyle[c.category]}`}>
                  {c.category}
                </span>
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-success/10 text-success">
                  Resolved
                </span>
              </div>
              <p className="text-sm text-foreground">{c.description}</p>
              {c.resolution && (
                <div className="mt-2 bg-muted/40 rounded-lg px-3 py-2">
                  <p className="text-xs text-foreground">
                    <strong>Resolution:</strong> {c.resolution}
                  </p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">
                    Resolved by {c.resolvedBy} {c.resolvedAt && `on ${new Date(c.resolvedAt).toLocaleString()}`}
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Resolve modal */}
      {resolving && (
        <div
          className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={() => setResolving(null)}
        >
          <div className="glass-card p-6 w-full max-w-md glow-cyan animate-slide-up" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-heading font-bold text-lg">Resolve {resolving.ticket}</h3>
              <button onClick={() => setResolving(null)} className="text-muted-foreground hover:text-foreground">
                <X size={20} />
              </button>
            </div>
            <p className="text-sm text-muted-foreground mb-4">{resolving.description}</p>
            <label className="block text-sm font-medium text-muted-foreground mb-1.5">Resolution note (optional)</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="Describe how this was resolved…"
              className="w-full px-4 py-2.5 rounded-lg bg-muted/50 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm"
            />
            <button
              onClick={handleResolve}
              className="w-full mt-4 py-2.5 font-semibold btn-navy flex items-center justify-center gap-2"
            >
              <CheckCircle2 size={16} /> Confirm Resolution
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default Complaints;
