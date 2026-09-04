// src/pages/portal/CustomerPortal.tsx
import { useEffect, useRef, useState } from "react";
import { Mic, Square, Send, Loader2, LogOut, Volume2, Ticket as TicketIcon } from "lucide-react";
import { LogoMark } from "@/components/Logo";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/hooks/use-toast";
import {
  submitChatComplaint, submitVoiceComplaint, getMyComplaints, Complaint,
} from "@/services/api";

interface ConversationTurn {
  id: string;
  role: "customer" | "vema";
  text: string;
  ticketCode?: string;
  severity?: string;
  status?: string;
  audioBase64?: string | null;
}

const severityStyle: Record<string, string> = {
  critical: "bg-destructive/10 text-destructive",
  medium: "bg-warning/10 text-warning",
  small: "bg-muted text-muted-foreground",
};

const statusLabel: Record<string, string> = {
  auto_resolved: "Resolved automatically",
  resolved: "Resolved",
  escalated: "With a Customer Representative",
  open: "Open",
};

const CustomerPortal = () => {
  const { user, logout } = useAuth();
  const { toast } = useToast();

  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [tickets, setTickets] = useState<Complaint[]>([]);
  const [micSupported, setMicSupported] = useState(true);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMicSupported(typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia);
  }, []);

  const loadTickets = () => {
    getMyComplaints()
      .then((res) => setTickets(res.tickets))
      .catch(() => {});
  };

  useEffect(() => { loadTickets(); }, []);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  const pushTurn = (turn: ConversationTurn) => setTurns((prev) => [...prev, turn]);

  const handleSendChat = async () => {
    const text = message.trim();
    if (!text || sending) return;
    setMessage("");
    pushTurn({ id: crypto.randomUUID(), role: "customer", text });
    setSending(true);
    try {
      const res = await submitChatComplaint(text);
      pushTurn({
        id: crypto.randomUUID(), role: "vema", text: res.reply_text,
        ticketCode: res.ticket_code, severity: (res.classification as { severity?: string })?.severity, status: res.status,
      });
      loadTickets();
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Failed to send message", variant: "destructive" });
    } finally {
      setSending(false);
    }
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setTranscribing(true);
        try {
          const res = await submitVoiceComplaint(blob);
          pushTurn({ id: crypto.randomUUID(), role: "customer", text: res.transcript });
          pushTurn({
            id: crypto.randomUUID(), role: "vema", text: res.reply_text,
            ticketCode: res.ticket_code, severity: (res.classification as { severity?: string })?.severity,
            status: res.status, audioBase64: res.reply_audio_base64,
          });
          loadTickets();
        } catch (err: unknown) {
          toast({ title: err instanceof Error ? err.message : "Voice submission failed", variant: "destructive" });
        } finally {
          setTranscribing(false);
        }
      };
      recorder.start();
      mediaRecorderRef.current = recorder;
      setRecording(true);
    } catch {
      toast({ title: "Microphone access denied or unavailable", variant: "destructive" });
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="h-16 flex-shrink-0 flex items-center justify-between px-4 sm:px-6 border-b border-border">
        <div className="flex items-center gap-2">
          <LogoMark size={28} />
          <div>
            <p className="font-heading font-bold text-sm leading-tight">NEXUS ERP</p>
            <p className="text-[10px] text-muted-foreground leading-tight">Customer Portal</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground hidden sm:inline">{user?.name}</span>
          <button onClick={logout} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
            <LogOut size={16} /> Logout
          </button>
        </div>
      </header>

      <div className="flex-1 flex flex-col lg:flex-row min-h-0">
        {/* Conversation */}
        <main className="flex-1 flex flex-col min-h-0">
          <div ref={scrollRef} className="flex-1 overflow-y-auto scroll-thin p-4 sm:p-6 space-y-4">
            {turns.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground gap-3 py-16">
                <Mic size={32} className="text-primary" />
                <p className="font-medium text-foreground">Tell us what's wrong — by voice or text</p>
                <p className="text-sm max-w-sm">
                  Describe your complaint below. VEMA will classify it and either resolve it
                  automatically or route it to a Customer Representative.
                </p>
              </div>
            )}
            {turns.map((t) => (
              <div key={t.id} className={`flex ${t.role === "customer" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] sm:max-w-[70%] rounded-2xl px-4 py-2.5 text-sm ${
                    t.role === "customer" ? "bg-primary text-primary-foreground" : "glass-card"
                  }`}
                >
                  <p>{t.text}</p>
                  {t.ticketCode && (
                    <div className="flex items-center gap-2 flex-wrap mt-2 pt-2 border-t border-white/10">
                      <span className="flex items-center gap-1 text-[11px] font-mono opacity-80">
                        <TicketIcon size={11} /> {t.ticketCode}
                      </span>
                      {t.severity && (
                        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${severityStyle[t.severity] || ""}`}>
                          {t.severity}
                        </span>
                      )}
                      {t.status && (
                        <span className="text-[10px] opacity-70">{statusLabel[t.status] || t.status}</span>
                      )}
                    </div>
                  )}
                  {t.audioBase64 && (
                    <button
                      onClick={() => new Audio(`data:audio/wav;base64,${t.audioBase64}`).play()}
                      className="flex items-center gap-1 text-[11px] mt-2 opacity-80 hover:opacity-100"
                    >
                      <Volume2 size={12} /> Play reply
                    </button>
                  )}
                </div>
              </div>
            ))}
            {transcribing && (
              <div className="flex justify-start">
                <div className="glass-card px-4 py-2.5 flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 size={14} className="animate-spin" /> Transcribing…
                </div>
              </div>
            )}
          </div>

          {/* Input bar */}
          <div className="flex-shrink-0 border-t border-border p-4 flex items-center gap-2">
            {micSupported && (
              <button
                onClick={recording ? stopRecording : startRecording}
                disabled={sending || transcribing}
                className={`flex-shrink-0 w-11 h-11 rounded-full flex items-center justify-center transition-colors disabled:opacity-50 ${
                  recording ? "bg-destructive text-destructive-foreground animate-pulse" : "bg-muted text-foreground hover:bg-muted/70"
                }`}
                aria-label={recording ? "Stop recording" : "Record voice complaint"}
              >
                {recording ? <Square size={16} /> : <Mic size={18} />}
              </button>
            )}
            <input
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSendChat()}
              placeholder={recording ? "Recording… tap the mic to stop" : "Describe your complaint…"}
              disabled={recording || sending}
              className="flex-1 px-4 py-2.5 rounded-full bg-muted/50 border border-border text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm disabled:opacity-60"
            />
            <button
              onClick={handleSendChat}
              disabled={!message.trim() || sending || recording}
              className="flex-shrink-0 w-11 h-11 rounded-full bg-primary text-primary-foreground flex items-center justify-center disabled:opacity-40"
              aria-label="Send message"
            >
              {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>
        </main>

        {/* Ticket history sidebar */}
        <aside className="lg:w-80 flex-shrink-0 border-t lg:border-t-0 lg:border-l border-border p-4 space-y-3 overflow-y-auto scroll-thin">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Your Tickets</p>
          {tickets.length === 0 && (
            <p className="text-sm text-muted-foreground">No tickets yet — log a complaint to get started.</p>
          )}
          {tickets.map((t) => (
            <div key={t.id} className="glass-card p-3">
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-xs font-mono text-muted-foreground">{t.ticket_code}</span>
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${severityStyle[t.severity]}`}>
                  {t.severity}
                </span>
              </div>
              <p className="text-xs text-foreground line-clamp-2">{t.description}</p>
              <p className="text-[11px] text-muted-foreground mt-1">{statusLabel[t.status] || t.status}</p>
            </div>
          ))}
        </aside>
      </div>
    </div>
  );
};

export default CustomerPortal;
