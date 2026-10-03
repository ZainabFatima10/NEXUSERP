// src/pages/Notifications.tsx
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  CheckCheck, RefreshCw, Loader2, Bell, Archive, Search, Settings,
  Info, CheckCircle2, AlertTriangle, AlertOctagon,
} from "lucide-react";
import {
  getNotifications, markNotificationRead, markAllNotificationsRead, archiveNotification,
  Notification,
} from "@/services/api";
import { useToast } from "@/hooks/use-toast";
import { ROLE_HOME } from "@/components/ProtectedRoute";
import { useAuth } from "@/contexts/AuthContext";

type Tab = "all" | "unread" | "action_needed";

const SEVERITY_ICON: Record<string, typeof Info> = {
  info: Info, success: CheckCircle2, warning: AlertTriangle, critical: AlertOctagon,
};
const SEVERITY_COLOR: Record<string, string> = {
  info: "text-primary bg-primary/10", success: "text-success bg-success/10",
  warning: "text-warning bg-warning/10", critical: "text-destructive bg-destructive/10",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins  = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days  = Math.floor(diff / 86400000);
  if (mins < 1)   return "just now";
  if (mins < 60)  return `${mins}m ago`;
  if (hours < 24) return `${hours}h ago`;
  return `${days}d ago`;
}

const Notifications = () => {
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const homeBase = ROLE_HOME[user?.role ?? "admin"] ?? "/admin";

  const [tab, setTab] = useState<Tab>("all");
  const [severity, setSeverity] = useState<string>("");
  const [search, setSearch] = useState("");
  const [items, setItems]   = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [limit, setLimit] = useState(30);

  const load = useCallback(async () => {
    setError(false);
    try {
      const res = await getNotifications({
        unread: tab === "unread" || undefined,
        requires_action: tab === "action_needed" || undefined,
        severity: severity || undefined,
        limit,
      });
      setItems(res.notifications);
      setUnread(res.unread_count);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [tab, severity, limit]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const filtered = search
    ? items.filter((n) => n.title.toLowerCase().includes(search.toLowerCase()) || n.description.toLowerCase().includes(search.toLowerCase()))
    : items;

  const handleMarkRead = async (id: string) => {
    try {
      await markNotificationRead(id);
      setItems((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
      setUnread((p) => Math.max(0, p - 1));
    } catch { /* silent */ }
  };

  const handleArchive = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await archiveNotification(id);
      setItems((prev) => prev.filter((n) => n.id !== id));
      toast({ title: "Archived" });
    } catch {
      toast({ title: "Could not archive", variant: "destructive" });
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnread(0);
      toast({ title: "All notifications marked as read" });
    } catch { /* silent */ }
  };

  const handleItemClick = (n: Notification) => {
    if (!n.is_read) handleMarkRead(n.id);
    if (n.action_url) navigate(n.action_url);
  };

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: "all", label: "All" },
    { key: "unread", label: "Unread", count: unread },
    { key: "action_needed", label: "Action Needed" },
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-heading font-bold">Notifications</h1>
            {unread > 0 && (
              <span className="text-xs bg-destructive text-destructive-foreground px-2 py-0.5 rounded-full font-semibold">
                {unread}
              </span>
            )}
          </div>
          <p className="text-muted-foreground text-sm mt-1">
            Consolidated alerts from orders, shipments, inventory, procurement, and outage AI.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate(`${homeBase}/notifications/preferences`)}
            className="flex items-center gap-2 px-3 py-2 text-sm border border-border rounded-lg hover:bg-muted/30 transition-colors"
          >
            <Settings size={14} /> Preferences
          </button>
          <button
            onClick={load}
            className="flex items-center gap-2 px-3 py-2 text-sm border border-border rounded-lg hover:bg-muted/30 transition-colors"
          >
            <RefreshCw size={14} /> Refresh
          </button>
          <button
            onClick={handleMarkAllRead}
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium btn-navy"
          >
            <CheckCheck size={16} /> Mark all as read
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex gap-1 flex-wrap bg-muted/30 p-1 w-fit" style={{ borderRadius: 20 }}>
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-all ${
                tab === t.key ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
              }`}
              style={{ borderRadius: 20 }}
            >
              {t.label}
              {!!t.count && (
                <span className="w-4 h-4 rounded-full bg-destructive text-destructive-foreground text-[9px] flex items-center justify-center font-bold">
                  {t.count > 9 ? "9+" : t.count}
                </span>
              )}
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            className="text-xs px-3 py-2 rounded-lg border border-border bg-background"
          >
            <option value="">All severities</option>
            <option value="info">Info</option>
            <option value="success">Success</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search..."
              className="pl-8 pr-3 py-2 text-xs rounded-lg border border-border bg-background w-40"
            />
          </div>
        </div>
      </div>

      <div className="space-y-2">
        {error ? (
          <div className="glass-card p-10 text-center text-muted-foreground">
            <p className="text-sm">Failed to load notifications.</p>
            <button onClick={load} className="text-xs text-primary mt-2 hover:underline">Try again</button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="glass-card p-10 text-center text-muted-foreground">
            <Bell size={32} className="mx-auto mb-2 opacity-30" />
            <p className="text-sm">No notifications in this view.</p>
          </div>
        ) : (
          <>
            {filtered.map((n) => {
              const Icon = SEVERITY_ICON[n.severity || "info"] || Info;
              return (
                <div
                  key={n.id}
                  className={`glass-card p-4 transition-all glow-cyan-hover flex items-start gap-3 cursor-pointer ${!n.is_read ? "bg-primary/5" : ""}`}
                  onClick={() => handleItemClick(n)}
                >
                  <div className={`mt-0.5 flex-shrink-0 p-1.5 rounded-lg ${SEVERITY_COLOR[n.severity || "info"]}`}>
                    <Icon size={14} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-medium">{n.title}</h3>
                      {!n.is_read && <span className="w-2 h-2 rounded-full bg-primary flex-shrink-0" />}
                      {n.requires_action && (
                        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-destructive/10 text-destructive">
                          Action needed
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{n.description}</p>
                    {n.action_label && (
                      <span className="text-[11px] text-primary font-medium mt-1 inline-block">{n.action_label} →</span>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-1 flex-shrink-0">
                    <span className="text-[10px] text-muted-foreground whitespace-nowrap">{timeAgo(n.created_at)}</span>
                    <button
                      onClick={(e) => handleArchive(n.id, e)}
                      className="text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100"
                      title="Archive"
                    >
                      <Archive size={13} />
                    </button>
                  </div>
                </div>
              );
            })}
            {items.length >= limit && (
              <button
                onClick={() => setLimit((l) => l + 30)}
                className="w-full py-2.5 text-sm text-primary border border-border rounded-lg hover:bg-muted/30"
              >
                Load more
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default Notifications;
