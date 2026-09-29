// src/pages/cr/TicketLog.tsx
import { useEffect, useRef, useState, useCallback } from "react";
import { Loader2, Mic, Bell, Ticket as TicketIcon, RefreshCw, Plus, Search } from "lucide-react";
import { Complaint, getComplaints, getComplaintTaxonomy } from "@/services/api";
import TicketDetailModal from "@/components/TicketDetailModal";
import LogComplaintModal from "@/components/LogComplaintModal";

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
const ORDER_OPTIONS: { value: "recent" | "priority"; label: string }[] = [
  { value: "recent", label: "Newest first" },
  { value: "priority", label: "Priority (critical first)" },
];

const TicketLog = () => {
  const [tickets, setTickets] = useState<Complaint[]>([]);
  const [loading, setLoading] = useState(true);   // initial load only
  const [refreshing, setRefreshing] = useState(false);
  const [status, setStatus] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [category, setCategory] = useState("all");
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [order, setOrder] = useState<"recent" | "priority">("recent");
  const [selected, setSelected] = useState<string | null>(null);
  const [logging, setLogging] = useState(false);
  const [categories, setCategories] = useState<string[]>([]);
  const firstLoad = useRef(true);

  useEffect(() => {
    getComplaintTaxonomy().then((t) => setCategories(Object.keys(t))).catch(() => {});
  }, []);

  // Debounce the free-text search (reference ID / ticket code / description)
  // so we're not re-querying on every keystroke.
  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(id);
  }, [searchInput]);

  const load = useCallback(() => {
    if (firstLoad.current) setLoading(true);
    else setRefreshing(true);
    getComplaints({
      status: status === "all" ? undefined : status,
      severity: severity === "all" ? undefined : severity,
      category: category === "all" ? undefined : category,
      search: search || undefined,
      order,
      limit: 200,
    })
      .then((res) => setTickets(res.tickets))
      .catch(() => {})
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
        firstLoad.current = false;
      });
  }, [status, severity, category, search, order]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-heading font-bold">All Tickets</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Every ticket — VEMA-generated and manual — filterable by status and severity.
          </p>
        </div>
        <button
          onClick={() => setLogging(true)}
          className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium btn-navy rounded-lg flex-shrink-0"
        >
          <Plus size={15} /> Log Complaint
        </button>
      </div>

      <div className="relative flex-1 min-w-[220px]">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search by reference ID, ticket code, or description…"
          className="w-full pl-8 pr-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
      </div>

      <div className="flex gap-3 flex-wrap items-center">
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
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option value="all">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select
          value={order}
          onChange={(e) => setOrder(e.target.value as "recent" | "priority")}
          className="px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          {ORDER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <button
          onClick={load}
          disabled={refreshing || loading}
          className="flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} /> Refresh
        </button>
        {!loading && (
          <span className="text-xs text-muted-foreground ml-auto">
            {tickets.length} ticket{tickets.length === 1 ? "" : "s"}
          </span>
        )}
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
                  {t.reference_id && (
                    <span className="text-[11px] font-mono text-primary/80">{t.reference_id}</span>
                  )}
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
      {logging && (
        <LogComplaintModal onClose={() => setLogging(false)} onCreated={load} />
      )}
    </div>
  );
};

export default TicketLog;
