// src/components/Topbar.tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, Menu } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { getNotifications } from "@/services/api";

interface Props {
  onOpenMobileSidebar: () => void;
  title: string;
}

const Topbar = ({ onOpenMobileSidebar, title }: Props) => {
  const { user } = useAuth();
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      getNotifications({ unread: true })
        .then((res) => {
          if (!cancelled) setUnread(res.unread_count);
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 20000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const initials = (user?.name || "Admin")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

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
        <Link
          to="/admin/notifications"
          className="relative p-2 rounded-lg hover:bg-muted/50 text-muted-foreground transition-colors"
          aria-label="Notifications"
        >
          <Bell size={19} />
          {unread > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-destructive text-destructive-foreground text-[9px] font-bold flex items-center justify-center">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Link>
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
