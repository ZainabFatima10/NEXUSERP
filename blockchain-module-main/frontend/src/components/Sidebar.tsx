// src/components/Sidebar.tsx
import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Package, CloudLightning, MessageSquare,
  Bell, ChevronLeft, ChevronRight, ChevronDown, LogOut, TrendingUp, ShoppingCart, BookOpen,
  UserCheck, Store, Truck, Wallet, ClipboardCheck,
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

/** A titled group of nav items. Sections can be collapsed by clicking the
 * header (remembered per-browser); the section holding the current page
 * always stays open so the active item is never hidden. */
export interface NavSection {
  title: string;
  items: NavItem[];
}

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  /** Flat list — rendered as a single untitled section. Ignored when
   * navSections is given. */
  navItems?: NavItem[];
  navSections?: NavSection[];
  brandSubtitle?: string;
  /** Keyed by NavItem.to — a small count badge next to that item (e.g.
   * Order Tracking's action-needed count, Vendor Applications' pending
   * count). Kept separate from NAV_ITEMS since those are static consts. */
  badges?: Record<string, number>;
}

export const ADMIN_NAV_SECTIONS: NavSection[] = [
  {
    title: "Overview",
    items: [{ to: "/admin", label: "Dashboard", icon: LayoutDashboard, end: true }],
  },
  {
    title: "Forecasting",
    items: [
      { to: "/admin/demand-prediction", label: "Demand Prediction", icon: TrendingUp },
      { to: "/admin/outage-prediction", label: "Outage Prediction", icon: CloudLightning },
    ],
  },
  {
    title: "Supply Chain",
    items: [
      { to: "/admin/inventory", label: "Inventory", icon: Package },
      { to: "/admin/procurement", label: "Procurement", icon: ShoppingCart },
      { to: "/admin/approvals", label: "Reorder Approvals", icon: ClipboardCheck },
      { to: "/admin/tracking", label: "Order Tracking", icon: Truck },
    ],
  },
  {
    title: "Vendors",
    items: [
      { to: "/admin/vendor-applications", label: "Vendor Applications", icon: UserCheck },
      { to: "/admin/vendor-catalogue", label: "Vendor Catalogue", icon: Store },
    ],
  },
  {
    title: "Finance",
    items: [{ to: "/admin/payments", label: "Payments", icon: Wallet }],
  },
  {
    title: "Customer Service",
    items: [
      { to: "/admin/complaints", label: "User Complaints", icon: MessageSquare },
      { to: "/admin/categories", label: "Complaint Categories", icon: BookOpen },
    ],
  },
  {
    title: "System",
    items: [{ to: "/admin/notifications", label: "Notifications", icon: Bell }],
  },
];

const COLLAPSED_SECTIONS_KEY = "nexus_sidebar_collapsed_sections";

const readCollapsedSections = (): string[] => {
  try {
    return JSON.parse(localStorage.getItem(COLLAPSED_SECTIONS_KEY) || "[]");
  } catch {
    return [];
  }
};

const isItemActive = (item: NavItem, pathname: string) =>
  item.end ? pathname === item.to : pathname === item.to || pathname.startsWith(item.to + "/");

const Sidebar = ({
  collapsed,
  onToggle,
  mobileOpen,
  onCloseMobile,
  navItems,
  navSections,
  brandSubtitle = "PowerGrid Optimizer",
  badges = {},
}: Props) => {
  const { logout } = useAuth();
  const { pathname } = useLocation();
  const sections: NavSection[] = navSections ?? (navItems ? [{ title: "", items: navItems }] : ADMIN_NAV_SECTIONS);
  const [collapsedSections, setCollapsedSections] = useState<string[]>(readCollapsedSections);

  const toggleSection = (title: string) => {
    setCollapsedSections((prev) => {
      const next = prev.includes(title) ? prev.filter((t) => t !== title) : [...prev, title];
      try {
        localStorage.setItem(COLLAPSED_SECTIONS_KEY, JSON.stringify(next));
      } catch {
        // per-browser convenience only
      }
      return next;
    });
  };

  const renderItem = (item: NavItem) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end}
      onClick={onCloseMobile}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        `relative flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
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
          {!collapsed && <span className="truncate flex-1">{item.label}</span>}
          {!!badges[item.to] && (
            <span className="min-w-[18px] h-[18px] px-1 rounded-full bg-destructive text-destructive-foreground text-[10px] font-bold flex items-center justify-center flex-shrink-0">
              {badges[item.to] > 99 ? "99+" : badges[item.to]}
            </span>
          )}
        </>
      )}
    </NavLink>
  );

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
      <nav className="flex-1 px-3 py-3 overflow-y-auto scroll-thin">
        {sections.map((section, idx) => {
          const hasActive = section.items.some((i) => isItemActive(i, pathname));
          const isOpen = !section.title || collapsed || hasActive || !collapsedSections.includes(section.title);
          const sectionBadge = section.items.reduce((sum, i) => sum + (badges[i.to] || 0), 0);
          return (
            <div key={section.title || idx} className={idx > 0 ? "mt-3" : ""}>
              {section.title && (collapsed ? (
                idx > 0 && <div className="mx-2 mb-3 border-t border-sidebar-border" />
              ) : (
                <button
                  onClick={() => toggleSection(section.title)}
                  disabled={hasActive}
                  className="w-full flex items-center gap-2 px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-sidebar-muted/70 hover:text-sidebar-foreground disabled:hover:text-sidebar-muted/70 transition-colors"
                  aria-expanded={isOpen}
                >
                  <span className="flex-1 text-left">{section.title}</span>
                  {!isOpen && sectionBadge > 0 && (
                    <span className="min-w-[16px] h-4 px-1 rounded-full bg-destructive text-destructive-foreground text-[9px] font-bold flex items-center justify-center">
                      {sectionBadge > 99 ? "99+" : sectionBadge}
                    </span>
                  )}
                  {!hasActive && (
                    <ChevronDown size={12} className={`transition-transform duration-200 ${isOpen ? "" : "-rotate-90"}`} />
                  )}
                </button>
              ))}
              {isOpen && <div className="space-y-0.5">{section.items.map(renderItem)}</div>}
            </div>
          );
        })}
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
