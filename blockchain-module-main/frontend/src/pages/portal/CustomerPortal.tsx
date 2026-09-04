// src/pages/portal/CustomerPortal.tsx
import { Mic } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

const CustomerPortal = () => {
  const { user, logout } = useAuth();
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="h-16 flex items-center justify-between px-6 border-b border-border">
        <p className="font-heading font-bold">NEXUS ERP — Customer Portal</p>
        <button onClick={logout} className="text-sm text-muted-foreground hover:text-foreground">
          Logout
        </button>
      </header>
      <main className="flex-1 flex items-center justify-center p-6">
        <div className="glass-card p-10 text-center max-w-md flex flex-col items-center gap-3">
          <Mic size={28} className="text-primary" />
          <p className="font-medium">Welcome, {user?.name}.</p>
          <p className="text-sm text-muted-foreground">
            The voice + chat complaint agent ships in the next delivery pass
            (Section 5 — Customer Portal).
          </p>
        </div>
      </main>
    </div>
  );
};

export default CustomerPortal;
