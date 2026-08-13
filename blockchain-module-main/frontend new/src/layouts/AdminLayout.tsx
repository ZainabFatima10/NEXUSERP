// src/layouts/AdminLayout.tsx
import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";

const TITLES: Record<string, string> = {
  "/admin": "Dashboard",
  "/admin/inventory": "Inventory Management",
  "/admin/outage-prediction": "Outage Prediction",
  "/admin/complaints": "User Complaints",
  "/admin/notifications": "Notifications",
};

const AdminLayout = () => {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const title = TITLES[location.pathname] || "NEXUS ERP";

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar onOpenMobileSidebar={() => setMobileOpen(true)} title={title} />
        <main className="flex-1 overflow-y-auto scroll-thin p-4 sm:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default AdminLayout;
