// src/pages/cr/CRDashboard.tsx
import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Clock, CheckCircle2, Bell, Loader2, Mic } from "lucide-react";
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

const StatCard = ({
  label, value, icon: Icon, tone,
}: {
  label: string; value: number; icon: typeof AlertTriangle; tone: string;
}) => (
  <div className="glass-card p-4 flex items-center gap-3">
    <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${tone}`}>
      <Icon size={18} />
    </div>
    <div>
      <p className="text-2xl font-heading font-bold leading-tight">{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  </div>
);

const CRDashboard = () => {
  const [tickets, setTickets] = useState<Complaint[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(() => {
    getComplaints({ limit: 200 })
      .then((res) => setTickets(res.tickets))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const escalated = tickets.filter((t) => t.status === "escalated");
  const critical = escalated.filter((t) => t.severity === "critical");
  const resolvedToday = tickets.filter(
    (t) => (t.status === "resolved" || t.status === "auto_resolved") &&
      t.updated_at && new Date(t.updated_at).toDateString() === new Date().toDateString()
  );

  // Most SLA-urgent open tickets first (soonest reminder due).
  const urgent = [...escalated].sort((a, b) => {
    if (!a.next_reminder_due) return 1;
    if (!b.next_reminder_due) return -1;
    return new Date(a.next_reminder_due).getTime() - new Date(b.next_reminder_due).getTime();
  }).slice(0, 8);

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
        <h1 className="text-2xl font-heading font-bold">Customer Representative Dashboard</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Escalated tickets sorted by SLA pressure — soonest reminder due first.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <StatCard label="Escalated (open)" value={escalated.length} icon={AlertTriangle} tone="bg-warning/10 text-warning" />
        <StatCard label="Critical, unresolved" value={critical.length} icon={Clock} tone="bg-destructive/10 text-destructive" />
        <StatCard label="Resolved today" value={resolvedToday.length} icon={CheckCircle2} tone="bg-success/10 text-success" />
        <StatCard label="Total tickets" value={tickets.length} icon={Bell} tone="bg-primary/10 text-primary" />
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            SLA Pressure — Escalated Tickets
          </p>
          <Link to="/cr/tickets" className="text-xs text-primary font-medium hover:underline">
            View all tickets →
          </Link>
        </div>

        {urgent.length === 0 ? (
          <div className="glass-card p-10 text-center text-muted-foreground text-sm">
            No escalated tickets right now. 🎉
          </div>
        ) : (
          <div className="space-y-2">
            {urgent.map((t) => {
              const due = t.next_reminder_due ? minutesUntil(t.next_reminder_due) : null;
              return (
                <button
                  key={t.id}
                  onClick={() => setSelected(t.id)}
                  className="w-full text-left glass-card p-4 flex items-center justify-between gap-4 flex-wrap glow-cyan-hover"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="text-xs font-mono text-muted-foreground">{t.ticket_code}</span>
                      <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${severityStyle[t.severity]}`}>
                        {t.severity}
                      </span>
                      {t.vema_triggered && (
                        <span className="flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-accent-cyan/10 text-accent-cyan">
                          <Mic size={10} /> VEMA
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-foreground line-clamp-1">{t.description}</p>
                  </div>
                  {due !== null && (
                    <span
                      className={`flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full flex-shrink-0 ${
                        due <= 0 ? "bg-destructive/10 text-destructive" : "bg-warning/10 text-warning"
                      }`}
                    >
                      <Bell size={12} /> {due <= 0 ? "Reminder due now" : `Due in ${due}m`}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {selected && (
        <TicketDetailModal ticketId={selected} onClose={() => setSelected(null)} onUpdated={load} />
      )}
    </div>
  );
};

export default CRDashboard;
