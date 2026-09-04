// src/pages/procurement/ProcurementDashboard.tsx
import { ShoppingCart } from "lucide-react";

const ProcurementDashboard = () => {
  return (
    <div className="space-y-6 animate-slide-up max-w-5xl">
      <div>
        <h1 className="text-2xl font-heading font-bold">Procurement Manager Dashboard</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Reorder approvals, vendor communication, and order tracking.
        </p>
      </div>
      <div className="glass-card p-10 text-center text-muted-foreground text-sm flex flex-col items-center gap-3">
        <ShoppingCart size={28} className="text-primary" />
        Reorder approval queue and vendor communication panel ship in the next
        delivery pass (Section 3 — Automated Inventory Reordering).
      </div>
    </div>
  );
};

export default ProcurementDashboard;
