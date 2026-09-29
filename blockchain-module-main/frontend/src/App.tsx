// src/App.tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "@/contexts/AuthContext";
import { ToastProvider } from "@/hooks/use-toast";
import ProtectedRoute from "@/components/ProtectedRoute";
import AdminLayout from "@/layouts/AdminLayout";
import ProcurementLayout from "@/layouts/ProcurementLayout";
import CRLayout from "@/layouts/CRLayout";

import Landing from "@/pages/marketing/Landing";
import Login from "@/pages/auth/Login";
import Signup from "@/pages/auth/Signup";
import Dashboard from "@/pages/Dashboard";
import Inventory from "@/pages/Inventory";
import DemandPrediction from "@/pages/DemandPrediction";
import Procurement from "@/pages/Procurement";
import OutagePrediction from "@/pages/OutagePrediction";
import Complaints from "@/pages/Complaints";
import Notifications from "@/pages/Notifications";
import CategoryReference from "@/pages/CategoryReference";
import NotFound from "@/pages/NotFound";

import ProcurementDashboard from "@/pages/procurement/ProcurementDashboard";
import ApprovalsQueue from "@/pages/procurement/ApprovalsQueue";
import VendorCommunication from "@/pages/procurement/VendorCommunication";
import CRDashboard from "@/pages/cr/CRDashboard";
import TicketLog from "@/pages/cr/TicketLog";
import CustomerPortal from "@/pages/portal/CustomerPortal";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
            {/* Public marketing site */}
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />

            {/* Admin — full access to every module */}
            <Route element={<ProtectedRoute allow={["admin"]} />}>
              <Route path="/admin" element={<AdminLayout />}>
                <Route index element={<Dashboard />} />
                <Route path="inventory" element={<Inventory />} />
                <Route path="demand-prediction" element={<DemandPrediction />} />
                <Route path="procurement" element={<Procurement />} />
                <Route path="outage-prediction" element={<OutagePrediction />} />
                <Route path="complaints" element={<Complaints />} />
                <Route path="categories" element={<CategoryReference />} />
                <Route path="notifications" element={<Notifications />} />
              </Route>
            </Route>

            {/* Procurement Manager */}
            <Route element={<ProtectedRoute allow={["procurement_manager"]} />}>
              <Route path="/procurement" element={<ProcurementLayout />}>
                <Route index element={<ProcurementDashboard />} />
                <Route path="approvals" element={<ApprovalsQueue />} />
                <Route path="vendors" element={<VendorCommunication />} />
                <Route path="notifications" element={<Notifications />} />
              </Route>
            </Route>

            {/* Customer Representative */}
            <Route element={<ProtectedRoute allow={["customer_rep"]} />}>
              <Route path="/cr" element={<CRLayout />}>
                <Route index element={<CRDashboard />} />
                <Route path="tickets" element={<TicketLog />} />
                <Route path="categories" element={<CategoryReference />} />
                <Route path="notifications" element={<Notifications />} />
              </Route>
            </Route>

            {/* Customer Portal */}
            <Route element={<ProtectedRoute allow={["customer"]} />}>
              <Route path="/portal" element={<CustomerPortal />} />
            </Route>

            <Route path="*" element={<NotFound />} />
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
