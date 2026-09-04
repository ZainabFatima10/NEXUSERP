// src/pages/cr/TicketLog.tsx
import { useEffect, useState, useCallback } from "react";
import { Loader2, Mic, Bell, Ticket as TicketIcon } from "lucide-react";
import { Complaint, getComplaints } from "@/services/api";
import TicketDetailModal from "@/components/TicketDetailModal";

const severityStyle: Record<string, string> = {
  critical: "bg-destructive/10 text-destructive",
  medium: "bg-warning/10 text-warning",
  small: "bg-muted text-muted-foreground",
};

function minutesUntil(iso: string): number {
  return Math.round((new Date(iso).getTime() - Date.now()) / 60000);
}

const STATUS_OPTIONS = ["all", "open", "escalated", "auto_resolved", "resolved"];
const SEVERITY_OPTIONS = ["all", "critical", "medium", "small"];

const TicketLog = () => {
  const [tickets, setTickets] = useState<Complaint[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    getComplaints({
      status: status === "all" ? undefined : status,
      severity: severity === "all" ? undefined : severity,
      limit: 200,
    })
      .then((res) => setTickets(res.tickets))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [status, severity]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="space-y-6 animate-slide-up">
      <div>
        <h1 className="text-2xl font-heading font-bold">All Tickets</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Every ticket — VEMA-generated and manual — filterable by status and severity.
        </p>
      </div>

      <div className="flex gap-3 flex-wrap">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s === "all" ? "All statuses" : s}</option>
          ))}
        </select>
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
          className="px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          {SEVERITY_OPTIONS.map((s) => (
            <option key={s} value={s}>{s === "all" ? "All severities" : s}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-40">
          <Loader2 className="animate-spin text-primary" size={32} />
        </div>
      ) : tickets.length === 0 ? (
        <div className="glass-card p-10 text-center text-muted-foreground text-sm">No tickets match this filter.</div>
      ) : (
        <div className="space-y-2">
          {tickets.map((t) => (
            <button
              key={t.id}
              onClick={() => setSelected(t.id)}
              className="w-full text-left glass-card p-4 flex items-start justify-between gap-4 flex-wrap glow-cyan-hover"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="text-xs font-mono text-muted-foreground">{t.ticket_code}</span>
                  <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${severityStyle[t.severity]}`}>
                    {t.severity}
                  </span>
                  <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    {t.status}
                  </span>
                  {t.vema_triggered && (
                    <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-accent-cyan/10 text-accent-cyan">
                      <Mic size={10} /> VEMA
                    </span>
                  )}
                  {t.status === "escalated" && t.next_reminder_due && (
                    <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-warning/10 text-warning">
                      <Bell size={10} /> due {minutesUntil(t.next_reminder_due) <= 0 ? "now" : `${minutesUntil(t.next_reminder_due)}m`}
                    </span>
                  )}
                </div>
                <p className="text-sm text-foreground line-clamp-1">{t.description}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {t.category} · {t.subtype} · {t.customer_name || "Unknown"}
                </p>
              </div>
              <TicketIcon size={16} className="text-muted-foreground flex-shrink-0 mt-1" />
            </button>
          ))}
        </div>
      )}

      {selected && (
        <TicketDetailModal ticketId={selected} onClose={() => setSelected(null)} onUpdated={load} />
      )}
    </div>
  );
};

export default TicketLog;
