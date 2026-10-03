// src/pages/NotificationPreferences.tsx
// Shared across every layout's /notifications/preferences route.
import { useEffect, useState } from "react";
import { Loader2, Lock, ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getNotificationPreferences, updateNotificationPreference, NotificationPreference } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

const NotificationPreferences = () => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [prefs, setPrefs] = useState<NotificationPreference[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    getNotificationPreferences()
      .then((res) => setPrefs(res.preferences))
      .catch(() => toast({ title: "Failed to load preferences", variant: "destructive" }))
      .finally(() => setLoading(false));
  }, [toast]);

  const toggle = async (p: NotificationPreference, field: "in_app" | "email") => {
    if (field === "in_app" && p.locked) return;
    const next = { ...p, [field]: !p[field] };
    setPrefs((prev) => prev.map((x) => (x.type === p.type ? next : x)));
    setSaving(p.type);
    try {
      await updateNotificationPreference(p.type, next.in_app, next.email);
    } catch {
      setPrefs((prev) => prev.map((x) => (x.type === p.type ? p : x))); // revert
      toast({ title: "Could not save preference", variant: "destructive" });
    } finally {
      setSaving(null);
    }
  };

  const grouped = prefs.reduce<Record<string, NotificationPreference[]>>((acc, p) => {
    (acc[p.category] = acc[p.category] || []).push(p);
    return acc;
  }, {});

  if (loading) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-primary" size={40} /></div>;
  }

  return (
    <div className="space-y-6 animate-slide-up max-w-2xl">
      <div>
        <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-2">
          <ArrowLeft size={13} /> Back
        </button>
        <h1 className="text-2xl font-heading font-bold">Notification Preferences</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Choose which events notify you in-app and by email. Critical and action-needed events are always
          delivered in-app so nothing urgent gets missed.
        </p>
      </div>

      {Object.entries(grouped).map(([category, items]) => (
        <div key={category} className="glass-card p-5">
          <p className="text-xs font-semibold text-muted-foreground uppercase mb-3">{category}</p>
          <div className="space-y-1">
            <div className="grid grid-cols-[1fr_72px_72px] text-[11px] text-muted-foreground font-medium px-2 pb-1">
              <span>Event</span><span className="text-center">In-app</span><span className="text-center">Email</span>
            </div>
            {items.map((p) => (
              <div key={p.type} className="grid grid-cols-[1fr_72px_72px] items-center px-2 py-2 rounded-lg hover:bg-muted/30 text-sm">
                <span className="flex items-center gap-1.5 truncate">
                  {p.type.replace(/[._]/g, " ")}
                  {p.locked && (
                    <span title="Always on for critical/action-needed events">
                      <Lock size={11} className="text-muted-foreground flex-shrink-0" />
                    </span>
                  )}
                </span>
                <span className="flex justify-center">
                  <input
                    type="checkbox" checked={p.in_app} disabled={p.locked || saving === p.type}
                    onChange={() => toggle(p, "in_app")} className="accent-primary"
                  />
                </span>
                <span className="flex justify-center">
                  {p.has_email ? (
                    <input
                      type="checkbox" checked={p.email} disabled={saving === p.type}
                      onChange={() => toggle(p, "email")} className="accent-primary"
                    />
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

export default NotificationPreferences;
