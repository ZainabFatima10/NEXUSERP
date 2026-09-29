// src/layouts/CRLayout.tsx
import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { LayoutDashboard, Ticket, Bell, BookOpen } from "lucide-react";
import Sidebar, { NavItem } from "@/components/Sidebar";
import Topbar from "@/components/Topbar";

const CR_NAV_ITEMS: NavItem[] = [
  { to: "/cr", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/cr/tickets", label: "All Tickets", icon: Ticket },
  { to: "/cr/categories", label: "Complaint Categories", icon: BookOpen },
  { to: "/cr/notifications", label: "Notifications", icon: Bell },
];

const TITLES: Record<string, string> = {
  "/cr": "Customer Representative Dashboard",
  "/cr/tickets": "All Tickets",
  "/cr/categories": "Complaint Categories",
  "/cr/notifications": "Notifications",
};

const CRLayout = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const title = TITLES[location.pathname] || "NEXUS ERP — CR Portal";

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
        navItems={CR_NAV_ITEMS}
        brandSubtitle="Customer Representative"
      />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar onOpenMobileSidebar={() => setMobileOpen(true)} title={title} />
        <main className="flex-1 overflow-y-auto scroll-thin p-4 sm:p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
};

export default CRLayout;
