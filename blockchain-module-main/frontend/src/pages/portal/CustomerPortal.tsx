// src/pages/portal/CustomerPortal.tsx
//
// VEMA as a real voice agent: tapping the mic starts a guided, spoken
// call — VEMA greets the customer, listens, reads the transcript back for
// confirmation, files the ticket, speaks the result, and asks whether to
// log anything else. Typing remains as a silent fallback (same review
// panel, no speech). See VEMA_PIPELINE.md for the underlying pipeline.
import { useEffect, useRef, useState } from "react";
import {
  Mic, Square, Send, Loader2, LogOut, Volume2, Ticket as TicketIcon,
  Check, RotateCcw, X, Trash2, PhoneOff,
} from "lucide-react";
import { LogoMark } from "@/components/Logo";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/hooks/use-toast";
import {
  submitChatComplaint, submitVoiceComplaint, transcribeVoiceComplaint,
  deleteComplaint, getMyComplaints, Complaint, ragQuery,
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

// A complaint the customer has drafted (spoken or typed) but not yet
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

// ─── Voice-agent helpers (module scope — no component state needed) ─────────

// Short affirmations/negations VEMA listens for during a spoken confirm.
// Word-boundary matched (padded with spaces) so "no" doesn't match "know".
const AFFIRM_WORDS = ["yes", "yeah", "yep", "yup", "sure", "correct", "submit", "confirm", "ok", "okay", "right"];
const AFFIRM_PHRASES = ["go ahead", "send it", "that's right", "sounds good", "file it"];
const NEGATE_WORDS = ["no", "nope", "wrong", "cancel", "stop", "incorrect", "nah"];
const NEGATE_PHRASES = ["try again", "not right", "redo it", "start over", "that's wrong"];

function detectIntent(raw: string): "yes" | "no" | "unclear" {
  const padded = ` ${raw.toLowerCase().replace(/[^a-z0-9\s']/g, " ")} `;
  const hasWord = (list: string[]) => list.some((w) => padded.includes(` ${w} `));
  const hasPhrase = (list: string[]) => list.some((p) => padded.includes(p));
  const yes = hasWord(AFFIRM_WORDS) || hasPhrase(AFFIRM_PHRASES);
  const no = hasWord(NEGATE_WORDS) || hasPhrase(NEGATE_PHRASES);
  if (yes && !no) return "yes";
  if (no && !yes) return "no";
  return "unclear";
}

// A short tone marking "you can talk now" — cheap Web Audio beep, no assets.
function playBeep() {
  try {
    const Ctx = window.AudioContext
      || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.2);
    osc.onended = () => ctx.close();
  } catch {
    // best-effort only — a missing beep never blocks the call
  }
}

const GREETING = "Hi, I'm VEMA, your electricity complaint assistant. Tell me what's wrong after the tone.";
const RETRY_GREETING = "Sure, go ahead — tell me again after the tone.";

const CustomerPortal = () => {
  const { user, logout } = useAuth();
  const { toast } = useToast();

  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [message, setMessage] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [callActive, setCallActive] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [submittingDraft, setSubmittingDraft] = useState(false);
  const [routing, setRouting] = useState(false); // classifying a message before deciding Q&A vs. complaint
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [tickets, setTickets] = useState<Complaint[]>([]);
  const [micSupported, setMicSupported] = useState(true);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const autoStopTimerRef = useRef<number | null>(null);
  const callTokenRef = useRef(0); // bumped to invalidate any in-flight call loop
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
  // Never leave the mic or a spoken sentence running if the customer navigates away.
  useEffect(() => () => cancelActiveCallLoop(), []); // eslint-disable-line react-hooks/exhaustive-deps

  const pushTurn = (turn: ConversationTurn) => setTurns((prev) => [...prev, turn]);

  // ─── Speech I/O ─────────────────────────────────────────────────────────────
  const speak = (text: string): Promise<void> =>
    new Promise((resolve) => {
      if (typeof window === "undefined" || !("speechSynthesis" in window) || !text) {
        resolve();
        return;
      }
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.rate = 1;
      utter.pitch = 1;
      utter.lang = "en-US";
      const finish = () => { setSpeaking(false); resolve(); };
      utter.onstart = () => setSpeaking(true);
      utter.onend = finish;
      utter.onerror = finish;
      window.speechSynthesis.speak(utter);
    });

  // Records one clip (up to maxMs, or until stopRecordingManually()/cancel).
  const recordOnce = (maxMs: number): Promise<Blob> =>
    new Promise((resolve, reject) => {
      navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
        const recorder = new MediaRecorder(stream);
        const chunks: Blob[] = [];
        recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
        recorder.onstop = () => {
          stream.getTracks().forEach((t) => t.stop());
          setRecording(false);
          if (autoStopTimerRef.current) { window.clearTimeout(autoStopTimerRef.current); autoStopTimerRef.current = null; }
          resolve(new Blob(chunks, { type: "audio/webm" }));
        };
        mediaRecorderRef.current = recorder;
        recorder.start();
        setRecording(true);
        autoStopTimerRef.current = window.setTimeout(() => {
          if (recorder.state === "recording") recorder.stop();
        }, maxMs);
      }).catch((err) => {
        setRecording(false);
        reject(err);
      });
    });

  const stopRecordingManually = () => {
    if (mediaRecorderRef.current?.state === "recording") mediaRecorderRef.current.stop();
  };

  // Stops whatever the call loop is mid-way through, without narrating it.
  function cancelActiveCallLoop() {
    callTokenRef.current += 1;
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    if (mediaRecorderRef.current?.state === "recording") {
      try { mediaRecorderRef.current.stop(); } catch { /* already stopped */ }
    }
    if (autoStopTimerRef.current) { window.clearTimeout(autoStopTimerRef.current); autoStopTimerRef.current = null; }
    setSpeaking(false);
    setRecording(false);
    setTranscribing(false);
    setCallActive(false);
  }

  // ─── RAG intent routing — Q&A/smalltalk answered directly, no ticket filed ──
  // Returns the RAG reply if this turn was answered directly (no complaint
  // should be filed), or null if it should proceed into the complaint flow
  // (either genuinely a complaint, or routing failed — fails open so a
  // customer's message is never silently dropped).
  const routeMessage = async (text: string): Promise<string | null> => {
    setRouting(true);
    try {
      const res = await ragQuery(text);
      return res.intent === "complaint_intake" ? null : res.reply;
    } catch {
      return null;
    } finally {
      setRouting(false);
    }
  };

  // ─── Ticket submission (shared by the voice call and the typed/manual path) ─
  const doSubmit = async (text: string, source: "voice" | "chat") => {
    if (source === "voice") {
      const res = await submitVoiceComplaint(text);
      return {
        replyText: res.reply_text, ticketCode: res.ticket_code, status: res.status,
        classification: res.classification as { severity?: string },
        audioBase64: res.reply_audio_base64,
      };
    }
    const res = await submitChatComplaint(text);
    return {
      replyText: res.reply_text, ticketCode: res.ticket_code, status: res.status,
      classification: res.classification as { severity?: string },
      audioBase64: null as string | null,
    };
  };

  // ─── Guided voice call ──────────────────────────────────────────────────────
  const runCall = async (skipGreeting = false) => {
    const myToken = ++callTokenRef.current;
    const isCurrent = () => callTokenRef.current === myToken;
    setCallActive(true);

    const opener = skipGreeting ? RETRY_GREETING : GREETING;
    pushTurn({ id: crypto.randomUUID(), role: "vema", text: opener });
    await speak(opener);
    if (!isCurrent()) return;

    while (isCurrent()) {
      // --- capture the complaint ---
      playBeep();
      let transcript = "";
      try {
        const blob = await recordOnce(20000);
        if (!isCurrent()) return;
        setTranscribing(true);
        const res = await transcribeVoiceComplaint(blob);
        transcript = res.transcript.trim();
      } catch {
        if (isCurrent()) toast({ title: "Microphone access denied or unavailable", variant: "destructive" });
        setTranscribing(false);
        if (isCurrent()) setCallActive(false);
        return;
      } finally {
        setTranscribing(false);
      }
      if (!isCurrent()) return;

      if (!transcript) {
        const msg = "I didn't catch anything. Please try again.";
        pushTurn({ id: crypto.randomUUID(), role: "vema", text: msg });
        await speak(msg);
        if (!isCurrent()) return;
        continue;
      }

      pushTurn({ id: crypto.randomUUID(), role: "customer", text: transcript });

      const directReply = await routeMessage(transcript);
      if (!isCurrent()) return;
      if (directReply !== null) {
        // A question or smalltalk, not a complaint — answer directly and
        // keep listening, no draft/confirm/ticket for this turn.
        pushTurn({ id: crypto.randomUUID(), role: "vema", text: directReply });
        await speak(directReply);
        if (!isCurrent()) return;
        continue;
      }

      setDraft({ text: transcript, source: "voice" });

      // --- confirm loop: read it back, listen for yes / try again ---
      let decision: "yes" | "no" | "unclear" = "unclear";
      for (let attempt = 0; attempt < 2 && decision === "unclear"; attempt++) {
        const confirmMsg = `You said: "${transcript}". Say submit to file this complaint, or try again to redo it.`;
        pushTurn({ id: crypto.randomUUID(), role: "vema", text: confirmMsg });
        await speak(confirmMsg);
        if (!isCurrent()) return;

        playBeep();
        let reply = "";
        try {
          const blob2 = await recordOnce(6000);
          if (!isCurrent()) return;
          setTranscribing(true);
          const res2 = await transcribeVoiceComplaint(blob2);
          reply = res2.transcript.trim();
        } catch {
          reply = "";
        } finally {
          setTranscribing(false);
        }
        if (!isCurrent()) return;

        pushTurn({ id: crypto.randomUUID(), role: "customer", text: reply || "(no response)" });
        decision = detectIntent(reply);
      }

      if (decision === "yes") {
        setSubmittingDraft(true);
        try {
          const result = await doSubmit(transcript, "voice");
          pushTurn({
            id: crypto.randomUUID(), role: "vema", text: result.replyText,
            ticketCode: result.ticketCode, severity: result.classification?.severity,
            status: result.status, audioBase64: result.audioBase64,
          });
          setDraft(null);
          loadTickets();
          setSubmittingDraft(false);
          if (!isCurrent()) return;
          await speak(result.replyText);
        } catch {
          setSubmittingDraft(false);
          const msg = "Sorry, something went wrong filing that complaint. Let's try again.";
          pushTurn({ id: crypto.randomUUID(), role: "vema", text: msg });
          await speak(msg);
          if (!isCurrent()) return;
          continue;
        }
      } else {
        setDraft(null);
        const msg = "No problem — let's try again.";
        pushTurn({ id: crypto.randomUUID(), role: "vema", text: msg });
        await speak(msg);
      }
      if (!isCurrent()) return;

      // --- ask whether to log another complaint ---
      const followMsg = "Would you like to report anything else? Say yes or no.";
      pushTurn({ id: crypto.randomUUID(), role: "vema", text: followMsg });
      await speak(followMsg);
      if (!isCurrent()) return;

      playBeep();
      let more = "";
      try {
        const blob3 = await recordOnce(5000);
        if (!isCurrent()) return;
        setTranscribing(true);
        const res3 = await transcribeVoiceComplaint(blob3);
        more = res3.transcript.trim();
      } catch {
        more = "";
      } finally {
        setTranscribing(false);
      }
      if (!isCurrent()) return;

      pushTurn({ id: crypto.randomUUID(), role: "customer", text: more || "(no response)" });
      if (detectIntent(more) !== "yes") {
        const bye = "Thanks for calling NEXUS. Have a good day.";
        pushTurn({ id: crypto.randomUUID(), role: "vema", text: bye });
        await speak(bye);
        break;
      }
    }

    if (isCurrent()) setCallActive(false);
  };

  const startCall = () => {
    if (callActive) return;
    if (!micSupported) {
      toast({ title: "Microphone access is required to talk to VEMA", variant: "destructive" });
      return;
    }
    runCall();
  };

  const endCall = () => {
    if (!callActive) return;
    cancelActiveCallLoop();
    setDraft(null);
    pushTurn({ id: crypto.randomUUID(), role: "vema", text: "Call ended." });
  };

  // ─── Draft (review-before-submit) — shared by voice call and typed chat ────
  const stageChatDraft = async () => {
    const text = message.trim();
    if (!text || draft || submittingDraft || routing) return;
    setMessage("");

    const directReply = await routeMessage(text);
    if (directReply !== null) {
      // A question or smalltalk, not a complaint — answer directly, skip
      // the review-before-submit panel entirely (nothing was ever staged,
      // so there's no draft to discard).
      pushTurn({ id: crypto.randomUUID(), role: "customer", text });
      pushTurn({ id: crypto.randomUUID(), role: "vema", text: directReply });
      return;
    }
    setDraft({ text, source: "chat" });
  };

  const confirmDraft = async () => {
    if (!draft) return;
    const text = draft.text.trim();
    if (!text) {
      toast({ title: "Please enter your complaint before submitting", variant: "destructive" });
      return;
    }
    const wasOnCall = callActive;
    if (wasOnCall) cancelActiveCallLoop();
    setSubmittingDraft(true);
    pushTurn({ id: crypto.randomUUID(), role: "customer", text });
    try {
      const result = await doSubmit(text, draft.source);
      pushTurn({
        id: crypto.randomUUID(), role: "vema", text: result.replyText,
        ticketCode: result.ticketCode, severity: result.classification?.severity,
        status: result.status, audioBase64: result.audioBase64,
      });
      setDraft(null);
      loadTickets();
      if (wasOnCall) await speak(result.replyText);
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Failed to submit complaint", variant: "destructive" });
    } finally {
      setSubmittingDraft(false);
    }
  };

  const discardDraft = () => {
    if (submittingDraft) return;
    if (callActive) cancelActiveCallLoop();
    setDraft(null);
  };

  const reRecord = () => {
    if (submittingDraft) return;
    if (callActive) cancelActiveCallLoop();
    setDraft(null);
    if (micSupported) runCall(true);
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

  const inputsDisabled = recording || transcribing || !!draft || submittingDraft || routing || callActive;

  const callStatusText = speaking
    ? "VEMA is speaking…"
    : recording
    ? "Listening — tap Done when you're finished"
    : transcribing
    ? "Transcribing…"
    : routing
    ? "Thinking…"
    : submittingDraft
    ? "Filing your complaint…"
    : "One moment…";

  return (
    <div className="h-screen overflow-hidden bg-background flex flex-col">
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
            {turns.length === 0 && !draft && !callActive && (
              <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground gap-3 py-16">
                <Mic size={32} className="text-primary" />
                <p className="font-medium text-foreground">Talk to VEMA, or type your complaint</p>
                <p className="text-sm max-w-sm">
                  Tap the microphone for a guided voice call — VEMA will ask what's wrong,
                  read back what it heard, and file the ticket once you confirm. You can also
                  just type below.
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
            {routing && !callActive && (
              <div className="flex justify-start">
                <div className="glass-card px-4 py-2.5 flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 size={14} className="animate-spin" /> Thinking…
                </div>
              </div>
            )}
          </div>

          {/* Live call status bar — visible for the whole call, alongside the review panel too */}
          {callActive && (
            <div className="flex-shrink-0 border-t border-border p-3 bg-primary/5 flex items-center gap-3">
              <span
                className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                  speaking ? "bg-primary animate-pulse" : recording ? "bg-destructive animate-pulse" : "bg-muted-foreground/40"
                }`}
              />
              <span className="text-sm text-muted-foreground flex-1">{callStatusText}</span>
              {recording && (
                <button
                  onClick={stopRecordingManually}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-muted text-foreground text-xs font-medium hover:bg-muted/70"
                >
                  <Square size={13} /> Done
                </button>
              )}
              <button
                onClick={endCall}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-destructive text-destructive-foreground text-xs font-medium"
              >
                <PhoneOff size={13} /> End Call
              </button>
            </div>
          )}

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

          {/* Input bar — typed complaints, or start the voice call */}
          {!draft && !callActive && (
            <div className="flex-shrink-0 border-t border-border p-4 flex items-center gap-2">
              {micSupported && (
                <button
                  onClick={startCall}
                  disabled={submittingDraft}
                  className="flex-shrink-0 w-11 h-11 rounded-full flex items-center justify-center transition-colors disabled:opacity-50 bg-primary text-primary-foreground hover:opacity-90"
                  aria-label="Talk to VEMA — start a voice call"
                  title="Talk to VEMA"
                >
                  <Mic size={18} />
                </button>
              )}
              <input
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && stageChatDraft()}
                placeholder="Describe your complaint…"
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
