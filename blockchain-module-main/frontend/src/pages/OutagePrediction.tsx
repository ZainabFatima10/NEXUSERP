// src/pages/OutagePrediction.tsx
import { useEffect, useState } from "react";
import { Loader2, Cpu, Clock, MapPin, CloudRain, ListChecks, RefreshCw } from "lucide-react";
import { getOutageForecast, ForecastDay } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

const riskStyles: Record<string, { bar: string; badge: string }> = {
  Low: { bar: "bg-success", badge: "bg-success/10 text-success" },
  Medium: { bar: "bg-warning", badge: "bg-warning/10 text-warning" },
  High: { bar: "bg-destructive", badge: "bg-destructive/10 text-destructive" },
};

function formatDayLabel(dateStr: string, day: string) {
  const d = new Date(dateStr);
  const month = d.toLocaleString("en-US", { month: "short" });
  return { day: day.slice(0, 3), date: `${month} ${d.getDate()}` };
}

const OutagePrediction = () => {
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [forecast, setForecast] = useState<ForecastDay[]>([]);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState(0);

  const load = async () => {
    try {
      const res = await getOutageForecast();
      setForecast(res.forecast);
      setGeneratedAt(res.generated_at);
    } catch (e: unknown) {
      toast({ title: "Failed to load forecast", description: String(e), variant: "destructive" });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    load();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  const selected = forecast[selectedIdx];

  return (
    <div className="space-y-6 animate-slide-up max-w-6xl">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-heading font-bold">Outage Prediction</h1>
          <p className="text-muted-foreground text-sm mt-1">
            AI-powered 7-day outage probability forecast, refreshed as new weather data arrives.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-1.5 text-xs text-muted-foreground">
            <Cpu size={13} className="text-success" />
            <span>AI Model: <span className="text-success font-medium">Active</span></span>
            {generatedAt && (
              <span className="ml-2">
                Last updated {new Date(generatedAt).toLocaleString()}
              </span>
            )}
          </div>
          <button
            onClick={handleRefresh}
            className="flex items-center gap-2 px-3 py-2 text-sm border border-border rounded-lg hover:bg-muted/30 transition-colors"
          >
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* 7-day cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        {forecast.map((f, idx) => {
          const { day, date } = formatDayLabel(f.date, f.day);
          const style = riskStyles[f.risk_level] || riskStyles.Low;
          const active = idx === selectedIdx;
          return (
            <button
              key={f.date}
              onClick={() => setSelectedIdx(idx)}
              className={`glass-card p-3 text-center transition-all ${
                active ? "ring-2 ring-primary" : "glow-cyan-hover"
              }`}
            >
              <p className="text-xs font-medium text-muted-foreground">{day}</p>
              <p className="text-[11px] text-muted-foreground/70 mb-2">{date}</p>
              <p className="text-2xl font-heading font-bold">{Math.round(f.outage_probability)}%</p>
              <span className={`inline-block text-[10px] font-semibold px-2 py-0.5 rounded-full mt-2 ${style.badge}`}>
                {f.risk_level}
              </span>
              <div className="h-1.5 bg-muted rounded-full mt-2 overflow-hidden">
                <div
                  className={`h-full rounded-full ${style.bar}`}
                  style={{ width: `${Math.min(f.outage_probability, 100)}%` }}
                />
              </div>
            </button>
          );
        })}
      </div>

      {/* Drill-down detail */}
      {selected && (
        <div className="glass-card p-6">
          <div className="flex items-center justify-between flex-wrap gap-2 mb-5">
            <h2 className="font-heading font-bold text-lg">
              {new Date(selected.date).toLocaleDateString("en-US", {
                weekday: "long",
                month: "long",
                day: "numeric",
              })}{" "}
              — Detail Report
            </h2>
            <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${riskStyles[selected.risk_level]?.badge}`}>
              {selected.risk_level} risk · {Math.round(selected.outage_probability)}% probability
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div>
              <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                <MapPin size={13} /> Affected Grid Areas
              </div>
              {selected.affected_zones.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {selected.affected_zones.map((z) => (
                    <span key={z} className="text-xs font-mono px-2 py-1 rounded-md bg-muted text-foreground">
                      {z}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">No zones currently flagged.</p>
              )}
            </div>

            <div>
              <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                <CloudRain size={13} /> Weather Factors
              </div>
              <ul className="space-y-1.5">
                {selected.weather_factors.map((w) => (
                  <li key={w} className="text-sm text-foreground flex items-start gap-1.5">
                    <span className="w-1 h-1 rounded-full bg-warning mt-2 flex-shrink-0" />
                    {w}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                <ListChecks size={13} /> Recommended Actions
              </div>
              <ul className="space-y-1.5">
                {selected.recommended_actions.map((a) => (
                  <li key={a} className="text-sm text-foreground flex items-start gap-1.5">
                    <span className="w-1 h-1 rounded-full bg-primary mt-2 flex-shrink-0" />
                    {a}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-5 pt-4 border-t border-border">
            <Clock size={12} />
            Projected demand: {selected.demand_kwh.toLocaleString()} kWh
          </div>
        </div>
      )}
    </div>
  );
};

export default OutagePrediction;
