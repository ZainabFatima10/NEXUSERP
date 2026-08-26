// src/pages/DemandPrediction.tsx
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CalendarDays, Loader2, Cpu, ArrowUpDown, Package,
  AlertTriangle, ShoppingCart, TrendingUp,
} from "lucide-react";
import { getDemandForecast, DemandForecastResponse, DemandPredictionItem } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

const StatusBadge = ({ status }: { status: string }) => {
  const colors: Record<string, string> = {
    OK: "bg-success/10 text-success",
    Low: "bg-warning/10 text-warning",
    Critical: "bg-destructive/10 text-destructive",
    "Out of Stock": "bg-destructive text-destructive-foreground",
    Unknown: "bg-muted text-muted-foreground",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${colors[status] || "bg-muted text-muted-foreground"}`}>
      {status}
    </span>
  );
};

const todayStr = () => new Date().toISOString().slice(0, 10);

const DemandPrediction = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [date, setDate] = useState(todayStr());
  const [data, setData] = useState<DemandForecastResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const load = async (d: string) => {
    setLoading(true);
    try {
      const res = await getDemandForecast(d);
      setData(res);
    } catch (e: unknown) {
      toast({ title: "Prediction failed", description: String(e), variant: "destructive" });
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(date);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handlePredict = () => load(date);

  const items = [...(data?.items || [])].sort((a, b) =>
    sortDir === "asc"
      ? a.predicted_demand - b.predicted_demand
      : b.predicted_demand - a.predicted_demand
  );

  const needingReorder = items.filter((i) => i.reorder_needed);

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-heading font-bold">Demand Prediction</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Select a date to forecast per-item demand using the trained XGBoost model.
          </p>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Cpu size={13} className={data?.model_loaded ? "text-success" : "text-warning"} />
          <span>
            AI Model:{" "}
            <span className={data?.model_loaded ? "text-success font-medium" : "text-warning font-medium"}>
              {data ? (data.model_loaded ? "Active" : "Fallback heuristic") : "—"}
            </span>
          </span>
        </div>
      </div>

      {/* Date picker */}
      <div className="glass-card p-5 flex flex-col sm:flex-row sm:items-end gap-4">
        <div className="flex-1">
          <label className="block text-sm font-medium text-muted-foreground mb-1.5">
            Forecast date
          </label>
          <div className="relative">
            <CalendarDays size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full pl-9 pr-4 py-2.5 rounded-lg bg-muted/50 border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
        </div>
        <button
          onClick={handlePredict}
          disabled={loading}
          className="flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-semibold btn-navy disabled:opacity-50"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <TrendingUp size={16} />}
          Get Prediction
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="animate-spin text-primary" size={40} />
        </div>
      ) : data ? (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { label: "Items Forecast", value: data.items.length, icon: Package, color: "text-primary" },
              { label: "Total Predicted Demand", value: data.total_predicted_demand, icon: TrendingUp, color: "text-accent-cyan" },
              { label: "Season", value: data.season, icon: CalendarDays, color: "text-accent-violet" },
              { label: "Needs Reorder", value: needingReorder.length, icon: AlertTriangle, color: "text-warning" },
            ].map((kpi) => (
              <div key={kpi.label} className="glass-card p-4">
                <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1.5">
                  <kpi.icon size={14} className={kpi.color} />
                  {kpi.label}
                </div>
                <p className="text-xl font-heading font-bold">{kpi.value}</p>
              </div>
            ))}
          </div>

          {/* Table */}
          <div className="glass-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">Item</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">Category</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">Current Stock</th>
                    <th
                      className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider cursor-pointer hover:text-foreground"
                      onClick={() => setSortDir(sortDir === "asc" ? "desc" : "asc")}
                    >
                      <div className="flex items-center gap-1">Predicted Demand <ArrowUpDown size={12} /></div>
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">Status</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase tracking-wider">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((i: DemandPredictionItem) => (
                    <tr key={i.item_id} className="border-b border-border last:border-0 hover:bg-muted/20">
                      <td className="px-4 py-3 font-medium">{i.name}</td>
                      <td className="px-4 py-3 text-muted-foreground">{i.category}</td>
                      <td className="px-4 py-3">{i.current_stock.toLocaleString()} {i.unit}</td>
                      <td className="px-4 py-3 font-mono font-semibold text-primary">
                        {i.predicted_demand.toLocaleString()} {i.unit}
                      </td>
                      <td className="px-4 py-3"><StatusBadge status={i.status} /></td>
                      <td className="px-4 py-3">
                        {i.reorder_needed ? (
                          <button
                            onClick={() =>
                              navigate("/admin/procurement", {
                                state: { prefillItemId: i.item_id, prefillQty: i.reorder_quantity },
                              })
                            }
                            className="flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
                          >
                            <ShoppingCart size={13} /> Reorder
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {items.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-10 text-center text-muted-foreground">
                        No items to forecast.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : (
        <div className="glass-card p-10 text-center text-muted-foreground">
          Select a date and click "Get Prediction" to forecast demand.
        </div>
      )}
    </div>
  );
};

export default DemandPrediction;
