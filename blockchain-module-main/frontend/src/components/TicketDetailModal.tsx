// src/components/TicketDetailModal.tsx
import { useEffect, useState } from "react";
import {
  X, Loader2, Mic, MessageSquare, Cpu, AlertTriangle, Bell, CheckCircle2, ArrowUpCircle,
} from "lucide-react";
import { Complaint, ComplaintEvent, getComplaint, resolveComplaint, escalateComplaint } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

import ModalPortal from "@/components/ModalPortal";
const severityStyle: Record<string, string> = {
  critical: "bg-destructive/10 text-destructive",
  medium: "bg-warning/10 text-warning",
  small: "bg-muted text-muted-foreground",
};

const eventIcon: Record<string, React.ReactNode> = {
  voice_transcript: <Mic size={14} className="text-primary" />,
  chat_message: <MessageSquare size={14} className="text-primary" />,
  system_action: <Cpu size={14} className="text-muted-foreground" />,
  escalation: <AlertTriangle size={14} className="text-destructive" />,
  reminder: <Bell size={14} className="text-warning" />,
  resolution: <CheckCircle2 size={14} className="text-success" />,
};

function minutesUntil(iso: string): number {
  return Math.round((new Date(iso).getTime() - Date.now()) / 60000);
}

interface Props {
  ticketId: string;
  onClose: () => void;
  onUpdated: () => void;
}

const TicketDetailModal = ({ ticketId, onClose, onUpdated }: Props) => {
  const { toast } = useToast();
  const [ticket, setTicket] = useState<Complaint | null>(null);
  const [events, setEvents] = useState<ComplaintEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [resolution, setResolution] = useState("");
  const [escalateNote, setEscalateNote] = useState("");
  const [showEscalate, setShowEscalate] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    getComplaint(ticketId)
      .then((res) => { setTicket(res.ticket); setEvents(res.events); })
      .catch(() => toast({ title: "Failed to load ticket", variant: "destructive" }))
      .finally(() => setLoading(false));
  };

  useEffect(load, [ticketId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleResolve = async () => {
    if (!resolution.trim()) return;
    setSaving(true);
    try {
      await resolveComplaint(ticketId, resolution.trim());
      toast({ title: "Ticket resolved" });
      onUpdated();
      load();
      setResolution("");
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Failed to resolve", variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  const handleEscalate = async () => {
    setSaving(true);
    try {
      await escalateComplaint(ticketId, escalateNote.trim() || undefined);
      toast({ title: "Escalated to Admin" });
      onUpdated();
      load();
      setShowEscalate(false);
      setEscalateNote("");
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Failed to escalate", variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <ModalPortal><div className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className="glass-card w-full max-w-2xl max-h-[85vh] flex flex-col animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        {loading || !ticket ? (
          <div className="p-10 flex items-center justify-center">
            <Loader2 className="animate-spin text-primary" size={28} />
          </div>
        ) : (
          <>
            <div className="p-5 border-b border-border flex items-start justify-between flex-shrink-0">
              <div>
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span className="font-mono text-sm text-muted-foreground">{ticket.ticket_code}</span>
                  <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${severityStyle[ticket.severity]}`}>
                    {ticket.severity}
                  </span>
                  <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    {ticket.status}
                  </span>
                </div>
                <p className="font-heading font-bold">{ticket.category} — {ticket.subtype}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {ticket.customer_name || "Unknown customer"} · {ticket.area || "Area unknown"} · via {ticket.channel}
                </p>
              </div>
              <button onClick={onClose} className="text-muted-foreground hover:text-foreground flex-shrink-0">
                <X size={20} />
              </button>
            </div>

            {ticket.status === "escalated" && ticket.next_reminder_due && (
              <div className="px-5 py-2.5 bg-warning/5 border-b border-warning/20 flex items-center gap-2 text-xs text-warning flex-shrink-0">
                <Bell size={13} />
                Next CR reminder due {minutesUntil(ticket.next_reminder_due) <= 0
                  ? "now"
                  : `in ${minutesUntil(ticket.next_reminder_due)} min`} · {ticket.reminder_count} sent so far
              </div>
            )}

            <div className="flex-1 overflow-y-auto scroll-thin p-5 space-y-3">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Conversation History</p>
              {events.map((e) => (
                <div key={e.id} className="flex gap-2.5">
                  <div className="mt-0.5 flex-shrink-0">{eventIcon[e.event_type] || <Cpu size={14} />}</div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-foreground">{e.content}</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      {e.actor} · {new Date(e.created_at).toLocaleString()}
                    </p>
                  </div>
                </div>
              ))}
            </div>

            {ticket.status !== "resolved" && ticket.status !== "auto_resolved" && (
              <div className="p-5 border-t border-border flex-shrink-0 space-y-3">
                {showEscalate ? (
                  <div className="space-y-2">
                    <textarea
                      value={escalateNote}
                      onChange={(e) => setEscalateNote(e.target.value)}
                      rows={2}
                      placeholder="Note for Admin (optional)…"
                      className="w-full px-3 py-2 rounded-lg bg-muted/50 border border-border text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                    <div className="flex gap-2">
                      <button onClick={() => setShowEscalate(false)} className="flex-1 py-2 text-sm border border-border rounded-lg">
                        Cancel
                      </button>
                      <button
                        onClick={handleEscalate}
                        disabled={saving}
                        className="flex-1 py-2 text-sm font-medium rounded-lg bg-destructive text-destructive-foreground flex items-center justify-center gap-1.5 disabled:opacity-60"
                      >
                        {saving ? <Loader2 size={14} className="animate-spin" /> : <ArrowUpCircle size={14} />}
                        Confirm Escalation
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <textarea
                      value={resolution}
                      onChange={(e) => setResolution(e.target.value)}
                      rows={2}
                      placeholder="Resolution note…"
                      className="w-full px-3 py-2 rounded-lg bg-muted/50 border border-border text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={() => setShowEscalate(true)}
                        className="flex-1 py-2 text-sm font-medium border border-destructive/30 text-destructive rounded-lg flex items-center justify-center gap-1.5"
                      >
                        <ArrowUpCircle size={14} /> Escalate to Admin
                      </button>
                      <button
                        onClick={handleResolve}
                        disabled={saving || !resolution.trim()}
                        className="flex-1 py-2 text-sm font-medium btn-navy flex items-center justify-center gap-1.5 disabled:opacity-60"
                      >
                        {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                        Resolve
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div></ModalPortal>
  );
};

export default TicketDetailModal;
