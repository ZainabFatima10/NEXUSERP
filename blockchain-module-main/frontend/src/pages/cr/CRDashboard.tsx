// src/pages/cr/CRDashboard.tsx
import { Ticket } from "lucide-react";

const CRDashboard = () => {
  return (
    <div className="space-y-6 animate-slide-up max-w-5xl">
      <div>
        <h1 className="text-2xl font-heading font-bold">Customer Representative Dashboard</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Full ticket log, conversation history, resolve/escalate actions.
        </p>
      </div>
      <div className="glass-card p-10 text-center text-muted-foreground text-sm flex flex-col items-center gap-3">
        <Ticket size={28} className="text-primary" />
        The full ticket log and conversation-history view ship once the VEMA
        backend and Customer Portal are wired (Sections 4–6).
      </div>
    </div>
  );
};

export default CRDashboard;
