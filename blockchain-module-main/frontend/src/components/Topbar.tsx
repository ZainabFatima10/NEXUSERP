// src/components/Topbar.tsx
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bell, Menu, CheckCheck, Info, CheckCircle2, AlertTriangle, AlertOctagon } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/hooks/use-toast";
import {
  getUnreadCount, getNotifications, markNotificationRead, markAllNotificationsRead,
  subscribeToNotifications, Notification,
} from "@/services/api";
import { ROLE_HOME } from "@/components/ProtectedRoute";

interface Props {
  onOpenMobileSidebar: () => void;
  title: string;
}

const SEVERITY_ICON: Record<string, typeof Info> = {
  info: Info, success: CheckCircle2, warning: AlertTriangle, critical: AlertOctagon,
};
const SEVERITY_COLOR: Record<string, string> = {
  info: "text-primary", success: "text-success", warning: "text-warning", critical: "text-destructive",
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

const Topbar = ({ onOpenMobileSidebar, title }: Props) => {
  const { user } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [recent, setRecent] = useState<Notification[]>([]);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const homeBase = ROLE_HOME[user?.role ?? "admin"] ?? "/admin";

  const refreshUnread = () => {
    getUnreadCount().then((res) => setUnread(res.count)).catch(() => {});
  };

  useEffect(() => {
    refreshUnread();
    const id = setInterval(refreshUnread, 30000); // safety-net poll even with SSE connected
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  // Live stream — new notifications bump the badge, fire a toast, and
  // (for requires_action ones) stay on screen with a deep-link action.
  useEffect(() => {
    const unsubscribe = subscribeToNotifications((n) => {
      setUnread((u) => u + (n.is_read ? 0 : 1));
      toast({
        title: n.title,
        description: n.description,
        variant: n.severity === "critical" ? "destructive" : n.severity === "success" ? "success" : "default",
        persist: !!n.requires_action,
        action: n.action_url ? { label: n.action_label || "View", onClick: () => navigate(n.action_url!) } : undefined,
      });
    });
    return unsubscribe;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Unread count in the browser tab title.
  useEffect(() => {
    const base = document.title.replace(/^\(\d+\)\s*/, "");
    document.title = unread > 0 ? `(${unread > 99 ? "99+" : unread}) ${base}` : base;
  }, [unread]);

  useEffect(() => {
    if (!open) return;
    getNotifications({ limit: 10 }).then((res) => setRecent(res.notifications)).catch(() => {});
    const onClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  const handleItemClick = async (n: Notification) => {
    if (!n.is_read) {
      try {
        await markNotificationRead(n.id);
        setRecent((prev) => prev.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)));
        setUnread((u) => Math.max(0, u - 1));
      } catch { /* silent */ }
    }
    setOpen(false);
    if (n.action_url) navigate(n.action_url);
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
      setRecent((prev) => prev.map((n) => ({ ...n, is_read: true })));
      setUnread(0);
    } catch { /* silent */ }
  };

  const today = new Date().toDateString();
  const todayItems = recent.filter((n) => new Date(n.created_at).toDateString() === today);
  const earlierItems = recent.filter((n) => new Date(n.created_at).toDateString() !== today);

  const initials = (user?.name || "Admin")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  const renderItem = (n: Notification) => {
    const Icon = SEVERITY_ICON[n.severity || "info"] || Info;
    return (
      <button
        key={n.id}
        onClick={() => handleItemClick(n)}
        className={`w-full text-left px-3 py-2.5 rounded-lg flex items-start gap-2.5 hover:bg-muted/40 transition-colors ${
          !n.is_read ? "bg-primary/5" : ""
        }`}
      >
        <Icon size={15} className={`mt-0.5 flex-shrink-0 ${SEVERITY_COLOR[n.severity || "info"]}`} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium truncate">{n.title}</p>
          <p className="text-[11px] text-muted-foreground truncate">{n.description}</p>
        </div>
        <span className="text-[10px] text-muted-foreground whitespace-nowrap flex-shrink-0">{timeAgo(n.created_at)}</span>
        {!n.is_read && <span className="w-1.5 h-1.5 rounded-full bg-primary flex-shrink-0 mt-1" />}
      </button>
    );
  };

  return (
    <header className="h-16 flex-shrink-0 border-b border-border bg-background/80 backdrop-blur-sm flex items-center justify-between px-4 sm:px-6 sticky top-0 z-30">
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onOpenMobileSidebar}
          className="lg:hidden p-2 -ml-2 rounded-lg hover:bg-muted/50 text-muted-foreground"
          aria-label="Open menu"
        >
          <Menu size={20} />
        </button>
        <h1 className="text-lg font-heading font-bold truncate">{title}</h1>
      </div>

      <div className="flex items-center gap-3 flex-shrink-0">
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setOpen((o) => !o)}
            className="relative p-2 rounded-lg hover:bg-muted/50 text-muted-foreground transition-colors"
            aria-label="Notifications"
          >
            <Bell size={19} />
            {unread > 0 && (
              <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-destructive text-destructive-foreground text-[9px] font-bold flex items-center justify-center animate-pulse">
                {unread > 99 ? "99+" : unread}
              </span>
            )}
          </button>

          {open && (
            <div className="absolute right-0 mt-2 w-80 glass-card p-2 shadow-xl z-40 max-h-[70vh] overflow-y-auto scroll-thin">
              <div className="flex items-center justify-between px-2 py-1.5">
                <p className="text-xs font-semibold text-muted-foreground uppercase">Notifications</p>
                <button onClick={handleMarkAllRead} className="flex items-center gap-1 text-[11px] text-primary hover:underline">
                  <CheckCheck size={12} /> Mark all read
                </button>
              </div>

              {recent.length === 0 ? (
                <p className="text-center text-xs text-muted-foreground py-6">No notifications yet.</p>
              ) : (
                <>
                  {todayItems.length > 0 && (
                    <div>
                      <p className="px-3 pt-2 pb-1 text-[10px] font-semibold text-muted-foreground uppercase">Today</p>
                      {todayItems.map(renderItem)}
                    </div>
                  )}
                  {earlierItems.length > 0 && (
                    <div>
                      <p className="px-3 pt-2 pb-1 text-[10px] font-semibold text-muted-foreground uppercase">Earlier</p>
                      {earlierItems.map(renderItem)}
                    </div>
                  )}
                </>
              )}

              <Link
                to={`${homeBase}/notifications`}
                onClick={() => setOpen(false)}
                className="block text-center text-xs font-medium text-primary py-2 mt-1 border-t border-border hover:bg-muted/30 rounded-lg"
              >
                View all
              </Link>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 pl-3 border-l border-border">
          <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-bold flex-shrink-0">
            {initials}
          </div>
          <div className="hidden sm:block leading-tight">
            <p className="text-sm font-medium truncate max-w-[140px]">{user?.name || "Admin"}</p>
            <p className="text-[11px] text-muted-foreground truncate max-w-[140px]">{user?.role || "Admin"}</p>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Topbar;
