// src/pages/Notifications.tsx
import { useState, useEffect, useCallback } from "react";
import {
  CheckCheck, ShieldCheck, RefreshCw, Cpu,
  Cloud, MessageSquare, Loader2, Bell,
} from "lucide-react";
import {
  getNotifications, markNotificationRead,
  markAllNotificationsRead, Notification,
} from "@/services/api";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/hooks/use-toast";

type Category =
  | "All"
  | "Confirmations"
  | "Updates"
  | "Resource Allocation"
  | "Outage Updates"
  | "User Complaints";

const categoryIcons: Record<string, React.ReactNode> = {
  Confirmations:       <ShieldCheck size={16} className="text-primary" />,
  Updates:             <RefreshCw size={16} className="text-muted-foreground" />,
  "Resource Allocation": <Cpu size={16} className="text-success" />,
  "Outage Updates":    <Cloud size={16} className="text-secondary" />,
  "User Complaints":   <MessageSquare size={16} className="text-warning" />,
};

const categoryBorders: Record<string, string> = {
  Confirmations:         "border-accent-cyan",
  Updates:               "",
  "Resource Allocation": "border-accent-green",
  "Outage Updates":      "border-accent-violet",
  "User Complaints":     "border-accent-amber",
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
  const [filter, setFilter] = useState<Category>("All");
  const [items, setItems]   = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);

  const categories: Category[] = [
    "All", "Confirmations", "Updates",
    "Resource Allocation", "Outage Updates", "User Complaints",
  ];

  const load = useCallback(async () => {
    try {
      const res = await getNotifications({ user_id: user?.id });
      setItems(res.notifications);
      setUnread(res.unread_count);
    } catch {
      // fallback — keep existing items
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const filtered =
    filter === "All" ? items : items.filter((n) => n.category === filter);

  const handleMarkRead = async (id: string) => {
    try {
      await markNotificationRead(id);
      setItems((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      );
      setUnread((p) => Math.max(0, p - 1));
    } catch { /* silent */ }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead(user?.id);
      setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnread(0);
      toast({ title: "All notifications marked as read" });
    } catch { /* silent */ }
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
            Consolidated alerts from inventory, procurement, and outage AI.
          </p>
        </div>
        <div className="flex gap-2">
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

      {/* Filter tabs */}
      <div className="flex gap-1 flex-wrap bg-muted/30 p-1 w-fit" style={{ borderRadius: 20 }}>
        {categories.map((cat) => {
          const catCount =
            cat === "All"
              ? unread
              : items.filter((n) => n.category === cat && !n.is_read).length;
          return (
            <button
              key={cat}
              onClick={() => setFilter(cat)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-all ${
                filter === cat
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              style={{ borderRadius: 20 }}
            >
              {cat}
              {catCount > 0 && (
                <span className="w-4 h-4 rounded-full bg-destructive text-destructive-foreground text-[9px] flex items-center justify-center font-bold">
                  {catCount > 9 ? "9+" : catCount}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Notification feed */}
      <div className="space-y-2">
        {filtered.length === 0 && (
          <div className="glass-card p-10 text-center text-muted-foreground">
            <Bell size={32} className="mx-auto mb-2 opacity-30" />
            <p className="text-sm">No notifications in this category.</p>
          </div>
        )}
        {filtered.map((n) => (
          <div
            key={n.id}
            className={`glass-card p-4 transition-all glow-cyan-hover flex items-start gap-3 cursor-pointer ${
              categoryBorders[n.category] || ""
            } ${!n.is_read ? "bg-primary/5" : ""}`}
            onClick={() => !n.is_read && handleMarkRead(n.id)}
          >
            <div className="mt-0.5 flex-shrink-0">
              {categoryIcons[n.category] || <RefreshCw size={16} className="text-muted-foreground" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-medium">{n.title}</h3>
                {!n.is_read && (
                  <span className="w-2 h-2 rounded-full bg-primary flex-shrink-0" />
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">{n.description}</p>
              {n.metadata && Object.keys(n.metadata).length > 0 && (
                <div className="flex gap-2 mt-1 flex-wrap">
                  {Object.entries(n.metadata).map(([k, v]) => (
                    <span key={k} className="text-[10px] bg-muted/50 px-1.5 py-0.5 rounded font-mono">
                      {k}: {String(v)}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex flex-col items-end gap-1 flex-shrink-0">
              <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                {timeAgo(n.created_at)}
              </span>
              {!n.is_read && (
                <span className="text-[9px] text-primary">click to mark read</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default Notifications;
