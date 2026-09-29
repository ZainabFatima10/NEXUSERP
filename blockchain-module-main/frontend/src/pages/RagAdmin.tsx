// src/pages/RagAdmin.tsx
// Feature C/D admin surface: knowledge-base stats, a test-query box, dataset
// upload, and a reindex button for the taxonomy/resolved-ticket sources.
import { useEffect, useRef, useState } from "react";
import { Database, Loader2, RefreshCw, Send, Upload, BookOpen } from "lucide-react";
import { getRagStats, ragQuery, ragIngest, ragReindex, RagStats, RagQueryResponse } from "@/services/api";
import { useToast } from "@/hooks/use-toast";

const DOC_TYPE_LABELS: Record<string, string> = {
  qa: "Q&A dataset",
  category_kb: "Category knowledge base",
  resolved_ticket: "Resolved tickets (anonymized)",
};

const RagAdmin = () => {
  const { toast } = useToast();
  const [stats, setStats] = useState<RagStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(true);
  const [reindexing, setReindexing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [testQuestion, setTestQuestion] = useState("");
  const [testResult, setTestResult] = useState<RagQueryResponse | null>(null);
  const [testing, setTesting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadStats = () => {
    setLoadingStats(true);
    getRagStats().then(setStats).catch(() => {}).finally(() => setLoadingStats(false));
  };

  useEffect(() => { loadStats(); }, []);

  const handleReindex = async () => {
    setReindexing(true);
    try {
      const res = await ragReindex();
      toast({ title: `Reindexed ${res.category_kb_documents} categories, ${res.resolved_ticket_documents} resolved tickets` });
      loadStats();
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Reindex failed", variant: "destructive" });
    } finally {
      setReindexing(false);
    }
  };

  const handleUpload = async (file: File) => {
    setUploading(true);
    try {
      const res = await ragIngest(file);
      toast({ title: `Ingested ${res.ingested}`, description: `${res.skipped} skipped, ${res.duplicates} duplicates` });
      loadStats();
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Ingestion failed", variant: "destructive" });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleTestQuery = async () => {
    const q = testQuestion.trim();
    if (!q) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await ragQuery(q);
      setTestResult(res);
    } catch (err: unknown) {
      toast({ title: err instanceof Error ? err.message : "Query failed", variant: "destructive" });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center gap-2">
        <Database size={22} className="text-primary" />
        <div>
          <h1 className="text-2xl font-heading font-bold">Knowledge Base</h1>
          <p className="text-muted-foreground text-sm mt-1">
            VEMA's retrieval-grounded Q&A + complaint-handling knowledge base. See{" "}
            <code className="text-xs bg-muted px-1 py-0.5 rounded">VEMA_RAG.md</code> for the full architecture.
          </p>
        </div>
      </div>

      {/* Stats */}
      <div className="glass-card p-5">
        <div className="flex items-center justify-between mb-4">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Document counts</p>
          <button
            onClick={handleReindex}
            disabled={reindexing}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-border rounded-lg hover:bg-muted/30 disabled:opacity-50"
          >
            {reindexing ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Reindex categories + resolved tickets
          </button>
        </div>
        {loadingStats ? (
          <Loader2 className="animate-spin text-primary" size={24} />
        ) : stats ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {Object.entries(DOC_TYPE_LABELS).map(([key, label]) => (
              <div key={key} className="bg-muted/30 rounded-lg p-3">
                <p className="text-2xl font-heading font-bold">{stats.by_doc_type[key]?.count ?? 0}</p>
                <p className="text-xs text-muted-foreground">{label}</p>
              </div>
            ))}
            <div className="sm:col-span-3 text-[11px] text-muted-foreground pt-1">
              Total: {stats.total} documents · Embedding backend: <span className="font-mono">{stats.embedding_backend}</span>
              {stats.embedding_backend === "hashing" && (
                <span> (Mistral API key not set — using the local term-hashing fallback; see VEMA_RAG.md)</span>
              )}
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Failed to load stats.</p>
        )}
      </div>

      {/* Upload */}
      <div className="glass-card p-5">
        <div className="flex items-center gap-2 mb-2">
          <Upload size={16} className="text-primary" />
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Add a Q&A dataset</p>
        </div>
        <p className="text-xs text-muted-foreground mb-3">
          CSV, JSON, JSONL, or XLSX with question/answer columns (optionally category, language, source).
        </p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.json,.jsonl,.xlsx"
          disabled={uploading}
          onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
          className="text-sm file:mr-3 file:px-3 file:py-2 file:rounded-lg file:border file:border-border file:bg-muted/50 file:text-sm file:font-medium disabled:opacity-50"
        />
        {uploading && <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" /> Ingesting…</p>}
      </div>

      {/* Test query */}
      <div className="glass-card p-5">
        <div className="flex items-center gap-2 mb-3">
          <BookOpen size={16} className="text-primary" />
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Test a question</p>
        </div>
        <div className="flex gap-2">
          <input
            value={testQuestion}
            onChange={(e) => setTestQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleTestQuery()}
            placeholder="e.g. How do I report a wrong bill?"
            className="flex-1 px-3 py-2 text-sm rounded-lg bg-muted/50 border border-border focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <button
            onClick={handleTestQuery}
            disabled={testing || !testQuestion.trim()}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium btn-navy rounded-lg disabled:opacity-50"
          >
            {testing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            Ask
          </button>
        </div>
        {testResult && (
          <div className="mt-4 bg-muted/30 rounded-lg p-4 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                intent: {testResult.intent}
              </span>
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${testResult.grounded ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>
                {testResult.grounded ? "grounded" : "not grounded"}
              </span>
            </div>
            <p className="text-sm text-foreground">{testResult.reply}</p>
            {testResult.sources.length > 0 && (
              <p className="text-[11px] text-muted-foreground">
                Sources: {testResult.sources.length} · scores: {testResult.retrieval_scores.map((s) => s.toFixed(3)).join(", ")}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default RagAdmin;
