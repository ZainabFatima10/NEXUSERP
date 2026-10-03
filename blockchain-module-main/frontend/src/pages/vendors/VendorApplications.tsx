// src/pages/vendors/VendorApplications.tsx
// Shared across /admin/vendor-applications and /procurement/vendor-applications.
import { useEffect, useState, useCallback } from "react";
import {
  Loader2, Search, CheckCircle2, XCircle, Clock, HelpCircle, FileText,
  Download, Mail, ShieldCheck,
} from "lucide-react";
import {
  listVendorApplications, getVendorApplication, approveVendorApplication,
  rejectVendorApplication, requestVendorApplicationInfo, updateVendorApplicationChecklist,
  getVendorApplicationDocumentUrl,
  VendorApplicationSummary, VendorApplicationDetail,
} from "@/services/api";
import { useToast } from "@/hooks/use-toast";

const TABS: { key: string; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "needs_info", label: "Needs Info" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
];

const CHECKLIST_ITEMS: { key: string; label: string }[] = [
  { key: "ntn_verified", label: "NTN verified" },
  { key: "registration_verified", label: "Registration certificate verified" },
  { key: "documents_reviewed", label: "Documents reviewed" },
  { key: "prices_reasonable", label: "Prices reasonable" },
  { key: "order_email_verified", label: "Order email verified" },
];

const statusBadge = (status: string) => {
  const map: Record<string, { cls: string; icon: typeof Clock; label: string }> = {
    pending:    { cls: "bg-warning/10 text-warning", icon: Clock, label: "Pending" },
    needs_info: { cls: "bg-accent-violet/10 text-accent-violet", icon: HelpCircle, label: "Needs Info" },
    approved:   { cls: "bg-success/10 text-success", icon: CheckCircle2, label: "Approved" },
    rejected:   { cls: "bg-destructive/10 text-destructive", icon: XCircle, label: "Rejected" },
  };
  const m = map[status] || { cls: "bg-muted text-muted-foreground", icon: Clock, label: status };
  const Icon = m.icon;
  return (
    <span className={`flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full ${m.cls}`}>
      <Icon size={11} /> {m.label}
    </span>
  );
};

const VendorApplications = () => {
  const { toast } = useToast();
  const [tab, setTab] = useState("pending");
  const [search, setSearch] = useState("");
  const [applications, setApplications] = useState<VendorApplicationSummary[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<VendorApplicationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [acting, setActing] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [infoNote, setInfoNote] = useState("");
  const [showInfoModal, setShowInfoModal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listVendorApplications({ status: tab, search: search || undefined, limit: 100 });
      setApplications(res.applications);
      setCounts(res.counts);
      setSelectedId((prev) => prev && res.applications.some((a) => a.id === prev) ? prev : res.applications[0]?.id ?? null);
    } catch {
      toast({ title: "Failed to load vendor applications", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [tab, search, toast]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    setDetailLoading(true);
    getVendorApplication(selectedId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selectedId]);

  const refreshDetail = () => { if (selectedId) getVendorApplication(selectedId).then(setDetail); };

  const handleApprove = async () => {
    if (!detail) return;
    setActing(true);
    try {
      const res = await approveVendorApplication(detail.id);
      toast({ title: res.message });
      await load();
    } catch (e: unknown) {
      toast({ title: e instanceof Error ? e.message : "Approval failed", variant: "destructive" });
    } finally {
      setActing(false);
    }
  };

  const handleReject = async () => {
    if (!detail || !rejectReason.trim()) return;
    setActing(true);
    try {
      const res = await rejectVendorApplication(detail.id, rejectReason);
      toast({ title: res.message });
      setShowRejectModal(false);
      setRejectReason("");
      await load();
    } catch (e: unknown) {
      toast({ title: e instanceof Error ? e.message : "Rejection failed", variant: "destructive" });
    } finally {
      setActing(false);
    }
  };

  const handleRequestInfo = async () => {
    if (!detail || !infoNote.trim()) return;
    setActing(true);
    try {
      const res = await requestVendorApplicationInfo(detail.id, infoNote);
      toast({ title: res.message });
      setShowInfoModal(false);
      setInfoNote("");
      await load();
    } catch (e: unknown) {
      toast({ title: e instanceof Error ? e.message : "Request failed", variant: "destructive" });
    } finally {
      setActing(false);
    }
  };

  const toggleChecklist = async (key: string) => {
    if (!detail) return;
    const next = { ...detail.vetting_checklist, [key]: !detail.vetting_checklist?.[key] };
    setDetail({ ...detail, vetting_checklist: next });
    try {
      await updateVendorApplicationChecklist(detail.id, next);
    } catch {
      refreshDetail();
    }
  };

  return (
    <div className="space-y-6 animate-slide-up">
      <div>
        <h1 className="text-2xl font-heading font-bold">Vendor Applications</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Review "Become a Vendor" submissions — approve to add them to the catalogue, or reject with a reason.
        </p>
      </div>

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex gap-2">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`text-sm font-medium px-4 py-2 rounded-lg transition-colors ${
                tab === t.key ? "bg-primary text-white" : "bg-muted/40 text-muted-foreground hover:bg-muted/60"
              }`}
            >
              {t.label} {counts[t.key] != null && <span className="ml-1 opacity-70">({counts[t.key]})</span>}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search company, reference, email..."
            className="pl-9 pr-3 py-2 text-sm rounded-lg border border-border bg-background w-64"
          />
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-primary" size={36} /></div>
      ) : applications.length === 0 ? (
        <div className="glass-card p-10 text-center text-muted-foreground text-sm">No applications in this tab.</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-1 space-y-2 max-h-[70vh] overflow-y-auto scroll-thin">
            {applications.map((a) => (
              <button
                key={a.id}
                onClick={() => setSelectedId(a.id)}
                className={`w-full text-left glass-card p-3 transition-all ${selectedId === a.id ? "ring-2 ring-primary/50" : "glow-cyan-hover"}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-mono text-muted-foreground">{a.reference_code}</span>
                  {statusBadge(a.status)}
                </div>
                <p className="text-sm font-medium mt-1 truncate">{a.legal_company_name}</p>
                <p className="text-xs text-muted-foreground truncate">{a.city}, {a.province} · {a.business_type}</p>
              </button>
            ))}
          </div>

          <div className="lg:col-span-2">
            {detailLoading ? (
              <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-primary" size={28} /></div>
            ) : detail ? (
              <div className="glass-card p-5 space-y-5">
                <div className="flex items-start justify-between flex-wrap gap-3">
                  <div>
                    <p className="font-heading font-bold text-lg">{detail.legal_company_name}</p>
                    <p className="text-sm text-muted-foreground font-mono">{detail.reference_code}</p>
                  </div>
                  {statusBadge(detail.status)}
                </div>

                <div className="grid sm:grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">Company</p>
                    <p>{detail.business_type} · NTN {detail.ntn}</p>
                    <p className="text-muted-foreground">{detail.address}, {detail.city}, {detail.province}</p>
                    {detail.categories?.length > 0 && <p className="text-muted-foreground mt-1">Categories: {detail.categories.join(", ")}</p>}
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">Contact</p>
                    <p>{detail.contact_name} {detail.contact_designation ? `(${detail.contact_designation})` : ""}</p>
                    <p className="text-muted-foreground flex items-center gap-1">
                      <Mail size={12} /> {detail.order_email}
                      {detail.email_verified
                        ? <span className="text-success text-[11px] font-semibold ml-1">Verified</span>
                        : <span className="text-warning text-[11px] font-semibold ml-1">Unverified</span>}
                    </p>
                    <p className="text-muted-foreground">{detail.mobile}</p>
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">Commercial Terms</p>
                    <p className="text-muted-foreground">
                      Lead time: {detail.lead_time_days ?? "—"} days · Payment: {detail.payment_terms || "—"} ·
                      Min order: {detail.min_order_value != null ? `PKR ${detail.min_order_value.toLocaleString()}` : "—"}
                    </p>
                    {detail.certifications?.length > 0 && <p className="text-muted-foreground">Certifications: {detail.certifications.join(", ")}</p>}
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">Bank (verification only)</p>
                    <p className="text-muted-foreground">{detail.bank_name || "—"} · {detail.bank_account_title || "—"}</p>
                    <p className="text-muted-foreground font-mono text-xs">{detail.bank_iban || "—"}</p>
                  </div>
                </div>

                {detail.documents.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground uppercase mb-2">Documents</p>
                    <div className="flex flex-wrap gap-2">
                      {detail.documents.map((d) => (
                        <a
                          key={d.id}
                          href={getVendorApplicationDocumentUrl(detail.id, d.id)}
                          target="_blank" rel="noreferrer"
                          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-muted/40 hover:bg-muted/60"
                        >
                          <FileText size={13} /> {d.doc_type.replace(/_/g, " ")} <Download size={12} />
                        </a>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase mb-2">
                    Catalogue ({detail.items.length} item{detail.items.length === 1 ? "" : "s"})
                  </p>
                  <div className="overflow-x-auto scroll-thin max-h-48">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-muted-foreground uppercase">
                          <th className="py-1 pr-2">Name</th><th className="py-1 pr-2">Category</th>
                          <th className="py-1 pr-2">Unit</th><th className="py-1 pr-2">Price</th><th className="py-1 pr-2">MOQ</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.items.map((it) => (
                          <tr key={it.id} className="border-t border-border">
                            <td className="py-1 pr-2">{it.name}</td>
                            <td className="py-1 pr-2">{it.category || "—"}</td>
                            <td className="py-1 pr-2">{it.unit}</td>
                            <td className="py-1 pr-2">PKR {it.unit_price.toLocaleString()}</td>
                            <td className="py-1 pr-2">{it.moq ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div>
                  <p className="text-xs font-semibold text-muted-foreground uppercase mb-2 flex items-center gap-1">
                    <ShieldCheck size={13} /> Vetting Checklist
                  </p>
                  <div className="grid sm:grid-cols-2 gap-1.5">
                    {CHECKLIST_ITEMS.map((c) => (
                      <label key={c.key} className="flex items-center gap-2 text-sm cursor-pointer">
                        <input type="checkbox" checked={!!detail.vetting_checklist?.[c.key]} onChange={() => toggleChecklist(c.key)} />
                        {c.label}
                      </label>
                    ))}
                  </div>
                </div>

                {detail.rejection_reason && (
                  <div className="bg-destructive/10 text-destructive text-sm rounded-lg p-3">Rejected: {detail.rejection_reason}</div>
                )}
                {detail.admin_notes && detail.status === "needs_info" && (
                  <div className="bg-accent-violet/10 text-accent-violet text-sm rounded-lg p-3">Requested info: {detail.admin_notes}</div>
                )}

                {(detail.status === "pending" || detail.status === "needs_info") && (
                  <div className="flex gap-2 pt-2 border-t border-border">
                    <button onClick={handleApprove} disabled={acting} className="flex-1 py-2.5 rounded-lg bg-success text-white text-sm font-medium hover:opacity-90 disabled:opacity-50">
                      Approve
                    </button>
                    <button onClick={() => setShowRejectModal(true)} disabled={acting} className="flex-1 py-2.5 rounded-lg bg-destructive text-white text-sm font-medium hover:opacity-90 disabled:opacity-50">
                      Reject
                    </button>
                    {detail.status === "pending" && (
                      <button onClick={() => setShowInfoModal(true)} disabled={acting} className="flex-1 py-2.5 rounded-lg border border-border text-sm font-medium hover:bg-muted/30 disabled:opacity-50">
                        Request Info
                      </button>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="glass-card p-10 text-center text-muted-foreground text-sm">Select an application</div>
            )}
          </div>
        </div>
      )}

      {showRejectModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-background rounded-xl p-6 max-w-md w-full space-y-4">
            <h3 className="font-heading font-bold text-lg">Reject Application</h3>
            <textarea
              value={rejectReason} onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Reason (required — the vendor will see this)"
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-muted/30" rows={3}
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowRejectModal(false)} className="px-4 py-2 text-sm rounded-lg border border-border">Cancel</button>
              <button onClick={handleReject} disabled={!rejectReason.trim() || acting} className="px-4 py-2 text-sm rounded-lg bg-destructive text-white disabled:opacity-50">
                Reject
              </button>
            </div>
          </div>
        </div>
      )}

      {showInfoModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-background rounded-xl p-6 max-w-md w-full space-y-4">
            <h3 className="font-heading font-bold text-lg">Request More Information</h3>
            <textarea
              value={infoNote} onChange={(e) => setInfoNote(e.target.value)}
              placeholder="What's missing or needs clarifying? (emailed to the vendor)"
              className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-muted/30" rows={3}
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowInfoModal(false)} className="px-4 py-2 text-sm rounded-lg border border-border">Cancel</button>
              <button onClick={handleRequestInfo} disabled={!infoNote.trim() || acting} className="px-4 py-2 text-sm rounded-lg bg-primary text-white disabled:opacity-50">
                Send
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default VendorApplications;
