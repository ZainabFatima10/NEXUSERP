// src/App.tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "@/contexts/AuthContext";
import { ToastProvider } from "@/hooks/use-toast";
import ProtectedRoute from "@/components/ProtectedRoute";
import AdminLayout from "@/layouts/AdminLayout";

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
import NotFound from "@/pages/NotFound";

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

            {/* Protected admin app */}
            <Route element={<ProtectedRoute />}>
              <Route path="/admin" element={<AdminLayout />}>
                <Route index element={<Dashboard />} />
                <Route path="inventory" element={<Inventory />} />
                <Route path="demand-prediction" element={<DemandPrediction />} />
                <Route path="procurement" element={<Procurement />} />
                <Route path="outage-prediction" element={<OutagePrediction />} />
                <Route path="complaints" element={<Complaints />} />
                <Route path="notifications" element={<Notifications />} />
              </Route>
            </Route>

            <Route path="*" element={<NotFound />} />
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
