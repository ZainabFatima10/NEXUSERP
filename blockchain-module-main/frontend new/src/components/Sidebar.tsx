// src/components/Sidebar.tsx
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, Package, CloudLightning, MessageSquare,
  Bell, ChevronLeft, ChevronRight, LogOut, Zap,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

const NAV_ITEMS = [
  { to: "/admin", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/admin/inventory", label: "Inventory", icon: Package },
  { to: "/admin/outage-prediction", label: "Outage Prediction", icon: CloudLightning },
  { to: "/admin/complaints", label: "User Complaints", icon: MessageSquare },
  { to: "/admin/notifications", label: "Notifications", icon: Bell },
];

const Sidebar = ({ collapsed, onToggle, mobileOpen, onCloseMobile }: Props) => {
  const { logout } = useAuth();

  const content = (
    <div className="flex flex-col h-full bg-sidebar text-sidebar-foreground">
      {/* Brand */}
      <div className="flex items-center gap-2 px-4 h-16 flex-shrink-0 border-b border-sidebar-border">
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center flex-shrink-0">
          <Zap size={16} className="text-white" fill="white" />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="text-sm font-heading font-bold leading-tight truncate">NEXUS ERP</p>
            <p className="text-[10px] text-sidebar-muted leading-tight truncate">PowerGrid Optimizer</p>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto scroll-thin">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onCloseMobile}
            title={collapsed ? item.label : undefined}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                isActive
                  ? "bg-primary/15 text-white"
                  : "text-sidebar-muted hover:bg-white/5 hover:text-sidebar-foreground"
              }`
            }
          >
            <item.icon size={18} className="flex-shrink-0" />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Footer actions */}
      <div className="px-3 py-4 border-t border-sidebar-border space-y-1 flex-shrink-0">
        <button
          onClick={onToggle}
          className="hidden lg:flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-sidebar-muted hover:bg-white/5 hover:text-sidebar-foreground w-full transition-colors"
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          {!collapsed && <span>Collapse</span>}
        </button>
        <button
          onClick={logout}
          className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-red-300 hover:bg-red-500/10 w-full transition-colors"
        >
          <LogOut size={18} />
          {!collapsed && <span>Logout</span>}
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside
        className={`hidden lg:block flex-shrink-0 transition-all duration-200 ${
          collapsed ? "w-[76px]" : "w-64"
        }`}
      >
        {content}
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="w-64">{content}</div>
          <div
            className="flex-1 bg-black/40 backdrop-blur-sm"
            onClick={onCloseMobile}
          />
        </div>
      )}
    </>
  );
};

export default Sidebar;
