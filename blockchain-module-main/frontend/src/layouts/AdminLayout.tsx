// src/layouts/AdminLayout.tsx
import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import { useSidebarBadges } from "@/hooks/use-sidebar-badges";

const TITLES: Record<string, string> = {
  "/admin": "Dashboard",
  "/admin/inventory": "Inventory Management",
  "/admin/demand-prediction": "Demand Prediction",
  "/admin/procurement": "Procurement",
  "/admin/vendor-applications": "Vendor Applications",
  "/admin/vendor-catalogue": "Vendor Catalogue",
  "/admin/place-order": "Place Vendor Order",
  "/admin/tracking": "Order Tracking",
  "/admin/payments": "Payments",
  "/admin/outage-prediction": "Outage Prediction",
  "/admin/complaints": "User Complaints",
  "/admin/categories": "Complaint Categories",
  "/admin/knowledge-base": "Knowledge Base",
  "/admin/notifications": "Notifications",
  "/admin/notifications/preferences": "Notification Preferences",
};

const AdminLayout = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const title = TITLES[location.pathname] || "NEXUS ERP";
  const badges = useSidebarBadges("/admin/tracking", "/admin/vendor-applications");

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
        badges={badges}
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

export default AdminLayout;
