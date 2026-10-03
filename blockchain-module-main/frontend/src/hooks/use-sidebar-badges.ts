// src/hooks/use-sidebar-badges.ts
// Order Tracking's action-needed count + Vendor Applications' pending
// count, for the sidebar's small red badges. Shared between AdminLayout
// and ProcurementLayout (the only two roles with both nav items).
import { useEffect, useState } from "react";
import { getTrackingSummary, listVendorApplications } from "@/services/api";

export function useSidebarBadges(trackingPath: string, vendorApplicationsPath: string) {
  const [badges, setBadges] = useState<Record<string, number>>({});

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [tracking, applications] = await Promise.all([
          getTrackingSummary("mine"),
          listVendorApplications({ status: "pending", limit: 1 }),
        ]);
        if (cancelled) return;
        setBadges({
          [trackingPath]: tracking.action_needed,
          [vendorApplicationsPath]: applications.counts.pending || 0,
        });
      } catch {
        // silent — badges just stay at their last known value
      }
    };
    load();
    const id = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(id); };
  }, [trackingPath, vendorApplicationsPath]);

  return badges;
}
