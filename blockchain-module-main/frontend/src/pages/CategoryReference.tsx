// src/pages/CategoryReference.tsx
// Feature B — the "Complaint Categories" reference view. One source of
// truth (backend taxonomy.py via GET /api/complaints/categories); admin and
// CR both read this page, nothing duplicates the category list here.
import { useEffect, useState } from "react";
import { Loader2, BookOpen, Ticket as TicketIcon } from "lucide-react";
import { getComplaintCategories, ComplaintCategoryRef } from "@/services/api";

const severityStyle: Record<string, string> = {
  critical: "bg-destructive/10 text-destructive",
  medium: "bg-warning/10 text-warning",
  small: "bg-muted text-muted-foreground",
};

const CategoryReference = () => {
  const [categories, setCategories] = useState<ComplaintCategoryRef[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getComplaintCategories()
      .then(setCategories)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-primary" size={40} />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center gap-2">
        <BookOpen size={22} className="text-primary" />
        <div>
          <h1 className="text-2xl font-heading font-bold">Complaint Categories</h1>
          <p className="text-muted-foreground text-sm mt-1">
            The single canonical taxonomy VEMA classifies against — same list the intake
            bot, ticket log, and knowledge base all read from.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {categories.map((c) => (
          <div key={c.code} className="glass-card p-5 space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <span className="text-[11px] font-mono text-primary font-semibold tracking-wide">{c.code}</span>
                <h2 className="font-heading font-bold text-lg leading-tight">{c.category}</h2>
              </div>
              <div className="flex flex-col items-end gap-1 flex-shrink-0">
                <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${severityStyle[c.default_severity]}`}>
                  default: {c.default_severity}
                </span>
                <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                  <TicketIcon size={11} /> {c.ticket_count} ticket{c.ticket_count === 1 ? "" : "s"}
                </span>
              </div>
            </div>

            <p className="text-sm text-foreground">{c.description}</p>
            <p className="text-xs text-muted-foreground">
              <span className="font-semibold">Routing:</span> {c.routing_hint}
            </p>

            <div>
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
                Required info when filing
              </p>
              <div className="flex flex-wrap gap-1">
                {c.required_fields.map((f) => (
                  <span key={f} className="text-[10px] font-mono bg-muted px-1.5 py-0.5 rounded">
                    {f}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
                Example phrases
              </p>
              <ul className="text-xs text-foreground space-y-0.5">
                {c.example_phrases.en.slice(0, 2).map((p) => <li key={p}>“{p}”</li>)}
                {c.example_phrases.roman_ur.slice(0, 1).map((p) => (
                  <li key={p} className="text-muted-foreground italic">“{p}”</li>
                ))}
              </ul>
            </div>

            {c.guidance && (
              <p className="text-[11px] text-muted-foreground border-t border-border pt-2">
                <span className="font-semibold">Guidance sample</span> (proposed — review before treating as policy):{" "}
                {c.guidance}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default CategoryReference;
