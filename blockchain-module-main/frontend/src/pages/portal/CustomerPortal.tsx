// src/pages/portal/CustomerPortal.tsx
import { useEffect, useRef, useState } from "react";
import {
  Mic, Square, Send, Loader2, LogOut, Volume2, Ticket as TicketIcon,
  Check, RotateCcw, X, Trash2,
} from "lucide-react";
import { LogoMark } from "@/components/Logo";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/hooks/use-toast";
import {
  submitChatComplaint, submitVoiceComplaint, transcribeVoiceComplaint,
  deleteComplaint, getMyComplaints, Complaint,
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

// A complaint the customer has drafted (typed or transcribed) but not yet
// submitted — they review / edit / re-record it first.
interface Draft {
  text: string;
  source: "voice" | "chat";
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

// Statuses the customer can still withdraw a complaint from (matches the backend).
const isDeletable = (status: string) => status === "open" || status === "auto_resolved";

const CustomerPortal = () => {
  const { user, logout } = useAuth();
  const { toast } = useToast();

  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [message, setMessage] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [submittingDraft, setSubmittingDraft] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [tickets, setTickets] = useState<Complaint[]>([]);
  const [micSupported, setMicSupported] = useState(true);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);

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
  }, [turns, draft]);
  useEffect(() => {
    if (draft) draftRef.current?.focus();
  }, [draft]);

  const pushTurn = (turn: ConversationTurn) => setTurns((prev) => [...prev, turn]);

  // ─── Draft (review-before-submit) ──────────────────────────────────────────
  const stageChatDraft = () => {
    const text = message.trim();
    if (!text || draft || submittingDraft) return;
    setMessage("");
    setDraft({ text, source: "chat" });
  };

  const confirmDraft = async () => {
    if (!draft) return;
    const text = draft.text.trim();
    if (!text) {
      toast({ title: "Please enter your complaint before submitting", variant: "destructive" });
      return;
    }
    setSubmittingDraft(true);
    pushTurn({ id: crypto.randomUUID(), role: "customer", text });
    try {
      let replyText: string, ticketCode: string, status: string;
      let classification: Record<string, unknown>;
      let audioBase64: string | null = null;
      if (draft.source === "voice") {
        const res = await submitVoiceComplaint(text);
        ({ reply_text: replyText, ticket_code: ticketCode, status, classification } = res);
        audioBase64 = res.reply_audio_base64;
      } else {
        const res = await submitChatComplaint(text);
        ({ reply_text: replyText, ticket_code: ticketCode, status, classification } = res);
      }
      pushTurn({
        id: crypto.randomUUID(), role: "vema", text: replyText,
        ticketCode,
        severity: (classification as { severity?: string })?.severity,
        status,
        audioBase64,
      });
      setDraft(null);
      loadTickets();
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Failed to submit complaint", variant: "destructive" });
    } finally {
      setSubmittingDraft(false);
    }
  };

  const discardDraft = () => {
    if (submittingDraft) return;
    setDraft(null);
  };

  const reRecord = () => {
    if (submittingDraft) return;
    setDraft(null);
    startRecording();
  };

  // ─── Voice capture ─────────────────────────────────────────────────────────
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
          const { transcript } = await transcribeVoiceComplaint(blob);
          setDraft({ text: transcript, source: "voice" });
        } catch (err: unknown) {
          toast({ title: err instanceof Error ? err.message : "Transcription failed", variant: "destructive" });
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

  // ─── Delete an existing ticket ─────────────────────────────────────────────
  const handleDelete = async (t: Complaint) => {
    if (deletingId) return;
    if (!window.confirm(`Withdraw complaint ${t.ticket_code}? This permanently removes it and its history.`)) return;
    setDeletingId(t.id);
    try {
      const res = await deleteComplaint(t.id);
      toast({ title: res.message });
      setTickets((prev) => prev.filter((x) => x.id !== t.id));
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Could not withdraw complaint", variant: "destructive" });
    } finally {
      setDeletingId(null);
    }
  };

  const inputsDisabled = recording || transcribing || !!draft || submittingDraft;

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
            {turns.length === 0 && !draft && (
              <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground gap-3 py-16">
                <Mic size={32} className="text-primary" />
                <p className="font-medium text-foreground">Tell us what's wrong — by voice or text</p>
                <p className="text-sm max-w-sm">
                  Describe your complaint below. You'll get to review it before it's sent — then
                  VEMA classifies it and either resolves it automatically or routes it to a
                  Customer Representative.
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

          {/* Review-before-submit panel */}
          {draft && (
            <div className="flex-shrink-0 border-t border-border p-4 bg-muted/20">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  {draft.source === "voice" ? "Review your transcribed complaint" : "Review your complaint"}
                </p>
                <span className="text-[11px] text-muted-foreground">Edit anything below before submitting</span>
              </div>
              <textarea
                ref={draftRef}
                value={draft.text}
                onChange={(e) => setDraft({ ...draft, text: e.target.value })}
                rows={3}
                disabled={submittingDraft}
                className="w-full px-3 py-2 rounded-lg bg-background border border-border text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 resize-y disabled:opacity-60"
              />
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <button
                  onClick={confirmDraft}
                  disabled={!draft.text.trim() || submittingDraft}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-full bg-primary text-primary-foreground text-sm font-medium disabled:opacity-40"
                >
                  {submittingDraft ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                  Submit complaint
                </button>
                {draft.source === "voice" && micSupported && (
                  <button
                    onClick={reRecord}
                    disabled={submittingDraft}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-muted text-foreground text-sm hover:bg-muted/70 disabled:opacity-40"
                  >
                    <RotateCcw size={15} /> Re-record
                  </button>
                )}
                <button
                  onClick={discardDraft}
                  disabled={submittingDraft}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-full text-sm text-muted-foreground hover:text-foreground disabled:opacity-40"
                >
                  <X size={15} /> Discard
                </button>
              </div>
            </div>
          )}

          {/* Input bar */}
          {!draft && (
            <div className="flex-shrink-0 border-t border-border p-4 flex items-center gap-2">
              {micSupported && (
                <button
                  onClick={recording ? stopRecording : startRecording}
                  disabled={transcribing || submittingDraft}
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
                onKeyDown={(e) => e.key === "Enter" && stageChatDraft()}
                placeholder={recording ? "Recording… tap the mic to stop" : "Describe your complaint…"}
                disabled={inputsDisabled}
                className="flex-1 px-4 py-2.5 rounded-full bg-muted/50 border border-border text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm disabled:opacity-60"
              />
              <button
                onClick={stageChatDraft}
                disabled={!message.trim() || inputsDisabled}
                className="flex-shrink-0 w-11 h-11 rounded-full bg-primary text-primary-foreground flex items-center justify-center disabled:opacity-40"
                aria-label="Review message"
              >
                <Send size={16} />
              </button>
            </div>
          )}
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
              <div className="flex items-center justify-between gap-2 mt-1.5">
                <p className="text-[11px] text-muted-foreground">{statusLabel[t.status] || t.status}</p>
                {isDeletable(t.status) && (
                  <button
                    onClick={() => handleDelete(t)}
                    disabled={deletingId === t.id}
                    aria-label={`Withdraw complaint ${t.ticket_code}`}
                    className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-destructive disabled:opacity-40 transition-colors"
                  >
                    {deletingId === t.id
                      ? <Loader2 size={12} className="animate-spin" />
                      : <Trash2 size={12} />}
                    Withdraw
                  </button>
                )}
              </div>
            </div>
          ))}
        </aside>
      </div>
    </div>
  );
};

export default CustomerPortal;
