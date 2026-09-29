// src/components/Sidebar.tsx
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, Package, CloudLightning, MessageSquare,
  Bell, ChevronLeft, ChevronRight, LogOut, TrendingUp, ShoppingCart, BookOpen, Database,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { LogoMark } from "@/components/Logo";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  navItems?: NavItem[];
  brandSubtitle?: string;
}

export const ADMIN_NAV_ITEMS: NavItem[] = [
  { to: "/admin", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/admin/inventory", label: "Inventory", icon: Package },
  { to: "/admin/demand-prediction", label: "Demand Prediction", icon: TrendingUp },
  { to: "/admin/procurement", label: "Procurement", icon: ShoppingCart },
  { to: "/admin/outage-prediction", label: "Outage Prediction", icon: CloudLightning },
  { to: "/admin/complaints", label: "User Complaints", icon: MessageSquare },
  { to: "/admin/categories", label: "Complaint Categories", icon: BookOpen },
  { to: "/admin/knowledge-base", label: "Knowledge Base", icon: Database },
  { to: "/admin/notifications", label: "Notifications", icon: Bell },
];

const Sidebar = ({
  collapsed,
  onToggle,
  mobileOpen,
  onCloseMobile,
  navItems = ADMIN_NAV_ITEMS,
  brandSubtitle = "PowerGrid Optimizer",
}: Props) => {
  const { logout } = useAuth();

  const content = (
    <div className="flex flex-col h-full bg-sidebar text-sidebar-foreground">
      {/* Brand */}
      <div className="flex items-center gap-2 px-4 h-16 flex-shrink-0 border-b border-sidebar-border">
        <LogoMark size={30} className="flex-shrink-0" />
        {!collapsed && (
          <div className="min-w-0">
            <p className="text-sm font-heading font-bold leading-tight truncate">NEXUS ERP</p>
            <p className="text-[10px] text-sidebar-muted leading-tight truncate">{brandSubtitle}</p>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto scroll-thin">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onCloseMobile}
            title={collapsed ? item.label : undefined}
            className={({ isActive }) =>
              `relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                isActive
                  ? "bg-primary/15 text-white"
                  : "text-sidebar-muted hover:bg-white/5 hover:text-sidebar-foreground hover:translate-x-0.5"
              }`
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full bg-accent-cyan" />
                )}
                <item.icon size={18} className={`flex-shrink-0 ${isActive ? "text-accent-cyan" : ""}`} />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </>
            )}
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
