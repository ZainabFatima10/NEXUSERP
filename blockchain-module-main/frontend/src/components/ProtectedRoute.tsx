// src/components/ProtectedRoute.tsx
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { Loader2 } from "lucide-react";

// Where each role lands when it hits a route it isn't allowed on
// (used both for the initial post-login redirect and for bounce-back here).
export const ROLE_HOME: Record<string, string> = {
  admin: "/admin",
  procurement_manager: "/procurement",
  customer_rep: "/cr",
  customer: "/portal",
};

interface Props {
  allow?: string[]; // omit to just require "logged in, any role"
}

const ProtectedRoute = ({ allow }: Props) => {
  const { user, initializing } = useAuth();
  const location = useLocation();

  if (initializing) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <Loader2 className="animate-spin text-primary" size={32} />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  // Role guard: redirect (don't just hide) unauthorized roles to their own home.
  if (allow && !allow.includes(user.role)) {
    return <Navigate to={ROLE_HOME[user.role] || "/login"} replace />;
  }

  return <Outlet />;
};

export default ProtectedRoute;
