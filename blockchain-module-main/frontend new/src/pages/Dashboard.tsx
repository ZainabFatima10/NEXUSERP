// src/pages/Dashboard.tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Package, ClipboardList, AlertTriangle, ShieldAlert, ArrowRight,
  Mic, Radio, Cpu, Loader2, CloudLightning, MessageSquare, Bell,
} from "lucide-react";
import { getInventoryOverview, listOrders, getOutageForecast } from "@/services/api";
import { SEED_COMPLAINTS } from "@/data/mockComplaints";
import { useAuth } from "@/contexts/AuthContext";

interface Kpi {
  label: string;
  value: string;
  icon: React.ElementType;
  color: string;
}

const QUICK_LINKS = [
  {
    to: "/admin/inventory",
    icon: Package,
    title: "Inventory Management",
    desc: "Track stock levels, orders, and blockchain-verified procurement.",
  },
  {
    to: "/admin/outage-prediction",
    icon: CloudLightning,
    title: "Outage Prediction",
    desc: "AI-powered 7-day outage forecasting with grid area analysis.",
  },
  {
    to: "/admin/complaints",
    icon: MessageSquare,
    title: "User Complaints",
    desc: "VEMA-integrated complaint tracking with escalation management.",
  },
  {
    to: "/admin/notifications",
    icon: Bell,
    title: "Notifications",
    desc: "Consolidated alerts for orders, outages, complaints, and resources.",
  },
];

const Dashboard = () => {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [kpis, setKpis] = useState<Kpi[]>([]);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const [inv, orders, forecast] = await Promise.allSettled([
          getInventoryOverview(),
          listOrders({ limit: 200 }),
          getOutageForecast(),
        ]);

        const totalItems = inv.status === "fulfilled" ? inv.value.summary.total_items : 0;
        const activeOrders =
          orders.status === "fulfilled"
            ? orders.value.orders.filter((o) => o.stage !== "Delivered" && o.stage !== "Cancelled").length
            : 0;
        const todayRisk =
          forecast.status === "fulfilled" && forecast.value.forecast.length > 0
            ? Math.round(forecast.value.forecast[0].outage_probability)
            : null;
        const unresolvedComplaints = SEED_COMPLAINTS.filter((c) => !c.resolved).length;

        if (!cancelled) {
          setKpis([
            { label: "Total Inventory Items", value: String(totalItems), icon: Package, color: "text-primary" },
            { label: "Active Orders", value: String(activeOrders), icon: ClipboardList, color: "text-accent-cyan" },
            { label: "Unresolved Complaints", value: String(unresolvedComplaints), icon: AlertTriangle, color: "text-warning" },
            {
              label: "Outage Risk Today",
              value: todayRisk !== null ? `${todayRisk}%` : "—",
              icon: ShieldAlert,
              color: todayRisk !== null && todayRisk >= 70 ? "text-destructive" : todayRisk !== null && todayRisk >= 40 ? "text-warning" : "text-success",
            },
          ]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6 animate-slide-up max-w-6xl">
      <div>
        <h2 className="text-2xl font-heading font-bold">Dashboard</h2>
        <p className="text-muted-foreground text-sm mt-1">
          Welcome back{user?.name ? `, ${user.name.split(" ")[0]}` : ""}. Here's your system overview.
        </p>
      </div>

      {/* KPI cards */}
      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="glass-card p-4 h-24 flex items-center justify-center">
              <Loader2 size={18} className="animate-spin text-muted-foreground" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {kpis.map((k) => (
            <div key={k.label} className="glass-card p-4 glow-cyan-hover">
              <k.icon size={18} className={`${k.color} mb-3`} />
              <p className="text-2xl font-heading font-bold">{k.value}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{k.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Quick access */}
      <div>
        <h3 className="text-sm font-heading font-bold text-muted-foreground uppercase tracking-wider mb-3">
          Quick Access
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {QUICK_LINKS.map((q) => (
            <Link
              key={q.to}
              to={q.to}
              className="glass-card p-5 glow-cyan-hover flex items-start gap-4 group"
            >
              <div className="w-10 h-10 rounded-lg bg-primary/10 text-primary flex items-center justify-center flex-shrink-0">
                <q.icon size={20} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <h4 className="text-sm font-semibold">{q.title}</h4>
                </div>
                <p className="text-xs text-muted-foreground mt-1">{q.desc}</p>
                <span className="inline-flex items-center gap-1 text-xs text-primary mt-2 font-medium">
                  Open <ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" />
                </span>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* System status */}
      <div className="glass-card p-4">
        <h3 className="text-xs font-heading font-bold text-muted-foreground uppercase tracking-wider mb-3">
          System Status
        </h3>
        <div className="flex flex-wrap gap-6">
          <div className="flex items-center gap-2 text-sm">
            <Mic size={15} className="text-muted-foreground" />
            <span className="text-muted-foreground">VEMA</span>
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-warning/10 text-warning">In Development</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Radio size={15} className="text-muted-foreground" />
            <span className="text-muted-foreground">Blockchain</span>
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-success/10 text-success">Active</span>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <Cpu size={15} className="text-muted-foreground" />
            <span className="text-muted-foreground">AI Model</span>
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-success/10 text-success">Running</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
