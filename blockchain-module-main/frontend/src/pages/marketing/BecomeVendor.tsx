// src/pages/marketing/BecomeVendor.tsx
import { useState, useEffect, ChangeEvent } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle2, ChevronRight, ChevronLeft, Upload, Plus, Trash2,
  Loader2, FileText, AlertCircle, Download, PartyPopper,
} from "lucide-react";
import Navbar from "@/components/marketing/Navbar";
import Footer from "@/components/marketing/Footer";
import {
  getVendorCategories, getVendorTemplateUrl, parseVendorCatalogueFile, applyVendor,
  VendorApplicationPayload, VendorApplicationItemInput, VendorDocumentUpload,
  ParsedCatalogueRow, ParsedCatalogueInvalidRow,
} from "@/services/api";

const BUSINESS_TYPES = ["Manufacturer", "Distributor", "Authorized Dealer", "Service Provider", "Other"];
const PK_PROVINCES = ["Punjab", "Sindh", "Khyber Pakhtunkhwa", "Balochistan", "Gilgit-Baltistan", "Azad Kashmir", "Islamabad Capital Territory"];
const EMPLOYEE_RANGES = ["1-10", "11-50", "51-200", "201-500", "500+"];
const DOC_TYPES: { value: string; label: string }[] = [
  { value: "ntn_certificate", label: "NTN Certificate" },
  { value: "registration_certificate", label: "Company Registration Certificate" },
  { value: "brochure", label: "Brochure (optional)" },
  { value: "authorization_letter", label: "Authorization Letter (optional)" },
];
const STEPS = ["Company", "Contact & Location", "Commercial Terms", "Documents", "Catalogue", "Review"];

const inputCls =
  "w-full px-4 py-2.5 rounded-lg bg-white/5 border border-white/15 text-white placeholder:text-white/30 focus:outline-none focus:ring-2 focus:ring-accent-cyan/50 text-sm";
const labelCls = "block text-sm font-medium text-white/70 mb-1.5";
const cardCls = "bg-navy-900/60 border border-white/10 rounded-2xl p-6 sm:p-8";
const chipCls = (active: boolean) =>
  `text-xs px-3 py-1.5 rounded-full border transition-colors cursor-pointer ${
    active ? "bg-accent-cyan/20 border-accent-cyan/50 text-accent-cyan" : "bg-white/5 border-white/15 text-white/60 hover:border-white/30"
  }`;

type FormState = Omit<VendorApplicationPayload, "items" | "consent" | "website_hp">;

const emptyForm: FormState = {
  legal_company_name: "", trade_name: "", business_type: "", ntn: "", strn: "",
  secp_number: "", year_established: undefined, employee_range: "", website: "",
  categories: [],
  contact_name: "", contact_designation: "", order_email: "", mobile: "",
  alternate_phone: "", address: "", city: "", province: "", postal_code: "",
  coverage_provinces: [], coverage_cities: [],
  lead_time_days: undefined, payment_terms: "", min_order_value: undefined,
  warranty: "", bank_name: "", bank_account_title: "", bank_iban: "",
  certifications: [],
};

const BecomeVendor = () => {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [items, setItems] = useState<VendorApplicationItemInput[]>([]);
  const [documents, setDocuments] = useState<VendorDocumentUpload[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [citiesText, setCitiesText] = useState("");
  const [certsText, setCertsText] = useState("");
  const [consent, setConsent] = useState(false);
  const [honeypot, setHoneypot] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ reference_code: string } | null>(null);

  const [parsing, setParsing] = useState(false);
  const [parsePreview, setParsePreview] = useState<{
    valid: ParsedCatalogueRow[];
    invalid: ParsedCatalogueInvalidRow[];
  } | null>(null);

  useEffect(() => {
    getVendorCategories().then((r) => setCategories(r.categories)).catch(() => {});
  }, []);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const toggleArrayValue = (key: "categories" | "coverage_provinces", value: string) => {
    setForm((f) => {
      const arr = f[key];
      return { ...f, [key]: arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value] };
    });
  };

  // ── Step validation ──────────────────────────────────────────────
  const validateStep = (s: number): string[] => {
    const e: string[] = [];
    if (s === 0) {
      if (!form.legal_company_name.trim()) e.push("Legal company name is required");
      if (!form.business_type) e.push("Business type is required");
      if (!form.ntn.trim()) e.push("NTN is required");
    }
    if (s === 1) {
      if (!form.contact_name.trim()) e.push("Contact name is required");
      if (!/^\S+@\S+\.\S+$/.test(form.order_email)) e.push("A valid order email is required");
      if (!/^(\+92|0)[0-9]{10}$/.test(form.mobile.replace(/[\s-]/g, ""))) {
        e.push("A valid Pakistani mobile number is required (e.g. 03XXXXXXXXX)");
      }
      if (!form.address.trim()) e.push("Address is required");
      if (!form.city.trim()) e.push("City is required");
      if (!form.province) e.push("Province is required");
    }
    if (s === 2 && form.bank_iban) {
      const iban = form.bank_iban.replace(/\s/g, "").toUpperCase();
      if (iban.length !== 24 || !iban.startsWith("PK")) {
        e.push("IBAN must be 24 characters and start with 'PK'");
      }
    }
    if (s === 4 && items.length === 0) {
      e.push("Add at least one catalogue item (manually or via upload) before continuing");
    }
    return e;
  };

  const goNext = () => {
    const e = validateStep(step);
    if (e.length) { setErrors(e); return; }
    setErrors([]);
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };
  const goBack = () => { setErrors([]); setStep((s) => Math.max(s - 1, 0)); };

  // ── Catalogue: manual rows ───────────────────────────────────────
  const addManualRow = () => setItems((rows) => [...rows, { name: "", unit: "units", unit_price: 0 }]);
  const updateRow = (idx: number, patch: Partial<VendorApplicationItemInput>) =>
    setItems((rows) => rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  const removeRow = (idx: number) => setItems((rows) => rows.filter((_, i) => i !== idx));

  // ── Catalogue: file upload/preview ───────────────────────────────
  const handleFileUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setParsing(true);
    setParsePreview(null);
    try {
      const res = await parseVendorCatalogueFile(file);
      setParsePreview({ valid: res.valid_rows, invalid: res.invalid_rows });
    } catch (err: unknown) {
      setErrors([err instanceof Error ? err.message : "Could not parse file"]);
    } finally {
      setParsing(false);
      e.target.value = "";
    }
  };

  const mergeParsedRows = () => {
    if (!parsePreview) return;
    const toAdd: VendorApplicationItemInput[] = parsePreview.valid
      .filter((r) => r.name && r.unit && r.unit_price != null)
      .map((r) => ({
        name: r.name as string,
        sku: r.sku || undefined,
        category: r.category || undefined,
        description: r.description || undefined,
        unit: r.unit as string,
        unit_price: r.unit_price as number,
        moq: r.moq ?? undefined,
        lead_time_days: r.lead_time_days ?? undefined,
      }));
    setItems((rows) => [...rows, ...toAdd]);
    setParsePreview(null);
  };

  // ── Documents ─────────────────────────────────────────────────────
  const handleDocUpload = (docType: string) => (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { setErrors([`${file.name} exceeds the 5 MB limit`]); return; }
    setDocuments((docs) => [...docs.filter((d) => d.doc_type !== docType), { file, doc_type: docType }]);
    e.target.value = "";
  };
  const removeDoc = (docType: string) => setDocuments((docs) => docs.filter((d) => d.doc_type !== docType));

  // ── Submit ────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    const e: string[] = [];
    if (!consent) e.push("You must accept the terms to submit");
    if (items.length === 0) e.push("Add at least one catalogue item");
    if (e.length) { setErrors(e); return; }

    setSubmitting(true);
    setErrors([]);
    try {
      const payload: VendorApplicationPayload = {
        ...form,
        coverage_cities: citiesText.split(",").map((c) => c.trim()).filter(Boolean),
        certifications: certsText.split(",").map((c) => c.trim()).filter(Boolean),
        items,
        consent,
        website_hp: honeypot,
      };
      const res = await applyVendor(payload, documents);
      setResult({ reference_code: res.reference_code });
    } catch (err: unknown) {
      setErrors([err instanceof Error ? err.message : "Submission failed — please try again"]);
    } finally {
      setSubmitting(false);
    }
  };

  // ── Success screen ───────────────────────────────────────────────
  if (result) {
    return (
      <div className="marketing min-h-screen">
        <Navbar />
        <div className="max-w-xl mx-auto px-5 pt-40 pb-28 text-center">
          <PartyPopper className="mx-auto mb-4 text-accent-cyan" size={40} />
          <h1 className="text-2xl font-heading font-bold text-white mb-2">Application Received</h1>
          <p className="text-white/60 mb-6">
            Your reference number is below. We'll email you the moment a decision is made.
          </p>
          <div className="font-mono text-xl font-bold text-accent-cyan bg-white/5 border border-white/15 rounded-xl py-4 mb-8">
            {result.reference_code}
          </div>
          <Link to="/" className="inline-block px-6 py-2.5 rounded-lg bg-primary text-white text-sm font-medium hover:opacity-90">
            Back to Home
          </Link>
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="marketing min-h-screen">
      <Navbar />
      <div className="max-w-3xl mx-auto px-5 pt-32 pb-28">
        <div className="text-center mb-10">
          <h1 className="text-3xl sm:text-4xl font-heading font-bold text-white mb-3">Become a Vendor</h1>
          <p className="text-white/60 max-w-xl mx-auto">
            Apply to supply NEXUS ERP's procurement network. No account needed — once approved,
            order requests come straight to your inbox with a one-click Accept/Reject.
          </p>
        </div>

        {/* Stepper */}
        <div className="flex items-center justify-between mb-10 overflow-x-auto scroll-thin pb-2">
          {STEPS.map((label, i) => (
            <div key={label} className="flex items-center flex-shrink-0">
              <div className="flex flex-col items-center gap-1.5">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold transition-colors ${
                    i < step ? "bg-accent-cyan text-navy-950" : i === step ? "bg-primary text-white" : "bg-white/10 text-white/40"
                  }`}
                >
                  {i < step ? <CheckCircle2 size={16} /> : i + 1}
                </div>
                <span className={`text-[11px] whitespace-nowrap ${i === step ? "text-white" : "text-white/40"}`}>{label}</span>
              </div>
              {i < STEPS.length - 1 && (
                <div className={`h-px w-6 sm:w-10 mx-1 ${i < step ? "bg-accent-cyan" : "bg-white/10"}`} />
              )}
            </div>
          ))}
        </div>

        {errors.length > 0 && (
          <div className="mb-6 bg-destructive/10 border border-destructive/30 rounded-xl p-4 flex items-start gap-3">
            <AlertCircle size={18} className="text-destructive flex-shrink-0 mt-0.5" />
            <ul className="text-sm text-destructive space-y-1">
              {errors.map((er) => <li key={er}>{er}</li>)}
            </ul>
          </div>
        )}

        <div className={cardCls}>
          {/* STEP 0 — Company */}
          {step === 0 && (
            <div className="space-y-4">
              <h2 className="text-lg font-heading font-bold text-white mb-1">Company Details</h2>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>Legal Company Name *</label>
                  <input className={inputCls} value={form.legal_company_name} onChange={(e) => update("legal_company_name", e.target.value)} />
                </div>
                <div>
                  <label className={labelCls}>Trade / Brand Name</label>
                  <input className={inputCls} value={form.trade_name} onChange={(e) => update("trade_name", e.target.value)} />
                </div>
              </div>
              <div>
                <label className={labelCls}>Business Type *</label>
                <div className="flex flex-wrap gap-2">
                  {BUSINESS_TYPES.map((t) => (
                    <button key={t} type="button" className={chipCls(form.business_type === t)} onClick={() => update("business_type", t)}>
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="grid sm:grid-cols-3 gap-4">
                <div>
                  <label className={labelCls}>NTN *</label>
                  <input className={inputCls} value={form.ntn} onChange={(e) => update("ntn", e.target.value)} />
                </div>
                <div>
                  <label className={labelCls}>STRN / Sales Tax Reg.</label>
                  <input className={inputCls} value={form.strn} onChange={(e) => update("strn", e.target.value)} />
                </div>
                <div>
                  <label className={labelCls}>SECP Registration No.</label>
                  <input className={inputCls} value={form.secp_number} onChange={(e) => update("secp_number", e.target.value)} />
                </div>
              </div>
              <div className="grid sm:grid-cols-3 gap-4">
                <div>
                  <label className={labelCls}>Year Established</label>
                  <input type="number" className={inputCls} value={form.year_established ?? ""} onChange={(e) => update("year_established", e.target.value ? Number(e.target.value) : undefined)} />
                </div>
                <div>
                  <label className={labelCls}>Employees</label>
                  <select className={inputCls} value={form.employee_range} onChange={(e) => update("employee_range", e.target.value)}>
                    <option value="" className="bg-navy-900">Select range</option>
                    {EMPLOYEE_RANGES.map((r) => <option key={r} value={r} className="bg-navy-900">{r}</option>)}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Website</label>
                  <input className={inputCls} placeholder="https://" value={form.website} onChange={(e) => update("website", e.target.value)} />
                </div>
              </div>
              <div>
                <label className={labelCls}>Product Categories Supplied</label>
                <div className="flex flex-wrap gap-2">
                  {categories.map((c) => (
                    <button key={c} type="button" className={chipCls(form.categories.includes(c))} onClick={() => toggleArrayValue("categories", c)}>
                      {c}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* STEP 1 — Contact & Location */}
          {step === 1 && (
            <div className="space-y-4">
              <h2 className="text-lg font-heading font-bold text-white mb-1">Contact &amp; Location</h2>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>Primary Contact Name *</label>
                  <input className={inputCls} value={form.contact_name} onChange={(e) => update("contact_name", e.target.value)} />
                </div>
                <div>
                  <label className={labelCls}>Designation</label>
                  <input className={inputCls} value={form.contact_designation} onChange={(e) => update("contact_designation", e.target.value)} />
                </div>
              </div>
              <div>
                <label className={labelCls}>Order Email *</label>
                <input type="email" className={inputCls} placeholder="orders@yourcompany.com" value={form.order_email} onChange={(e) => update("order_email", e.target.value)} />
                <p className="text-xs text-white/40 mt-1">Purchase order requests will be sent here — we'll email a verification link too.</p>
              </div>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className={labelCls}>Mobile *</label>
                  <input className={inputCls} placeholder="03XXXXXXXXX" value={form.mobile} onChange={(e) => update("mobile", e.target.value)} />
                </div>
                <div>
                  <label className={labelCls}>Alternate Phone</label>
                  <input className={inputCls} value={form.alternate_phone} onChange={(e) => update("alternate_phone", e.target.value)} />
                </div>
              </div>
              <div>
                <label className={labelCls}>Registered Address *</label>
                <textarea className={inputCls} rows={2} value={form.address} onChange={(e) => update("address", e.target.value)} />
              </div>
              <div className="grid sm:grid-cols-3 gap-4">
                <div>
                  <label className={labelCls}>City *</label>
                  <input className={inputCls} value={form.city} onChange={(e) => update("city", e.target.value)} />
                </div>
                <div>
                  <label className={labelCls}>Province *</label>
                  <select className={inputCls} value={form.province} onChange={(e) => update("province", e.target.value)}>
                    <option value="" className="bg-navy-900">Select province</option>
                    {PK_PROVINCES.map((p) => <option key={p} value={p} className="bg-navy-900">{p}</option>)}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Postal Code</label>
                  <input className={inputCls} value={form.postal_code} onChange={(e) => update("postal_code", e.target.value)} />
                </div>
              </div>
              <div>
                <label className={labelCls}>Delivery Coverage — Provinces</label>
                <div className="flex flex-wrap gap-2">
                  {PK_PROVINCES.map((p) => (
                    <button key={p} type="button" className={chipCls(form.coverage_provinces.includes(p))} onClick={() => toggleArrayValue("coverage_provinces", p)}>
                      {p}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className={labelCls}>Delivery Coverage — Cities (comma-separated)</label>
                <input className={inputCls} placeholder="Lahore, Karachi, Islamabad" value={citiesText} onChange={(e) => setCitiesText(e.target.value)} />
              </div>
            </div>
          )}

          {/* STEP 2 — Commercial Terms */}
          {step === 2 && (
            <div className="space-y-4">
              <h2 className="text-lg font-heading font-bold text-white mb-1">Commercial Terms</h2>
              <div className="grid sm:grid-cols-3 gap-4">
                <div>
                  <label className={labelCls}>Standard Lead Time (days)</label>
                  <input type="number" className={inputCls} value={form.lead_time_days ?? ""} onChange={(e) => update("lead_time_days", e.target.value ? Number(e.target.value) : undefined)} />
                </div>
                <div>
                  <label className={labelCls}>Payment Terms</label>
                  <input className={inputCls} placeholder="e.g. Net 30" value={form.payment_terms} onChange={(e) => update("payment_terms", e.target.value)} />
                </div>
                <div>
                  <label className={labelCls}>Minimum Order Value (PKR)</label>
                  <input type="number" className={inputCls} value={form.min_order_value ?? ""} onChange={(e) => update("min_order_value", e.target.value ? Number(e.target.value) : undefined)} />
                </div>
              </div>
              <div>
                <label className={labelCls}>Warranty</label>
                <input className={inputCls} value={form.warranty} onChange={(e) => update("warranty", e.target.value)} />
              </div>
              <div>
                <label className={labelCls}>Certifications (comma-separated — ISO, PEC, NEPRA, etc.)</label>
                <input className={inputCls} placeholder="ISO 9001, PEC Licensed" value={certsText} onChange={(e) => setCertsText(e.target.value)} />
              </div>
              <div className="pt-2 border-t border-white/10">
                <p className="text-xs text-white/40 mb-3">
                  Bank details — for verification only, never shown in any public listing.
                </p>
                <div className="grid sm:grid-cols-3 gap-4">
                  <div>
                    <label className={labelCls}>Bank Name</label>
                    <input className={inputCls} value={form.bank_name} onChange={(e) => update("bank_name", e.target.value)} />
                  </div>
                  <div>
                    <label className={labelCls}>Account Title</label>
                    <input className={inputCls} value={form.bank_account_title} onChange={(e) => update("bank_account_title", e.target.value)} />
                  </div>
                  <div>
                    <label className={labelCls}>IBAN</label>
                    <input className={inputCls} placeholder="PK36SCBL0000001123456702" value={form.bank_iban} onChange={(e) => update("bank_iban", e.target.value)} />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 3 — Documents */}
          {step === 3 && (
            <div className="space-y-4">
              <h2 className="text-lg font-heading font-bold text-white mb-1">Documents</h2>
              <p className="text-sm text-white/50 mb-2">PDF, JPG or PNG — max 5 MB each.</p>
              {DOC_TYPES.map((dt) => {
                const existing = documents.find((d) => d.doc_type === dt.value);
                return (
                  <div key={dt.value} className="flex items-center justify-between gap-3 bg-white/5 border border-white/10 rounded-lg px-4 py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <FileText size={18} className="text-white/40 flex-shrink-0" />
                      <div className="min-w-0">
                        <p className="text-sm text-white">{dt.label}</p>
                        {existing && <p className="text-xs text-accent-cyan truncate">{existing.file.name}</p>}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {existing && (
                        <button type="button" onClick={() => removeDoc(dt.value)} className="text-white/40 hover:text-destructive">
                          <Trash2 size={16} />
                        </button>
                      )}
                      <label className="text-xs font-medium px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/15 cursor-pointer text-white">
                        {existing ? "Replace" : "Upload"}
                        <input type="file" accept=".pdf,.jpg,.jpeg,.png" className="hidden" onChange={handleDocUpload(dt.value)} />
                      </label>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* STEP 4 — Catalogue */}
          {step === 4 && (
            <div className="space-y-5">
              <div className="flex items-center justify-between flex-wrap gap-3">
                <h2 className="text-lg font-heading font-bold text-white mb-1">Items &amp; Unit Prices</h2>
                <a href={getVendorTemplateUrl()} className="inline-flex items-center gap-1.5 text-xs text-accent-cyan hover:underline">
                  <Download size={14} /> Download template
                </a>
              </div>

              <div className="border border-dashed border-white/20 rounded-xl p-5 text-center">
                <Upload size={22} className="mx-auto text-white/40 mb-2" />
                <p className="text-sm text-white/60 mb-2">Drop or choose a .xlsx / .csv catalogue file</p>
                <label className="inline-block text-xs font-medium px-4 py-2 rounded-lg bg-white/10 hover:bg-white/15 cursor-pointer text-white">
                  {parsing ? <Loader2 size={14} className="inline animate-spin mr-1" /> : null}
                  Choose File
                  <input type="file" accept=".xlsx,.csv" className="hidden" onChange={handleFileUpload} disabled={parsing} />
                </label>
              </div>

              {parsePreview && (
                <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
                  <p className="text-sm text-white">
                    {parsePreview.valid.length} valid row{parsePreview.valid.length === 1 ? "" : "s"}
                    {parsePreview.invalid.length > 0 && (
                      <span className="text-warning"> · {parsePreview.invalid.length} row(s) need fixing</span>
                    )}
                  </p>
                  {parsePreview.invalid.length > 0 && (
                    <div className="max-h-40 overflow-y-auto scroll-thin space-y-1">
                      {parsePreview.invalid.map((r) => (
                        <div key={r.row_number} className="text-xs text-white/60">
                          Row {r.row_number} ({r.name || "unnamed"}): {r.errors.join(", ")}
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <button type="button" onClick={mergeParsedRows} disabled={parsePreview.valid.length === 0} className="text-xs font-medium px-3 py-1.5 rounded-lg bg-accent-cyan/20 text-accent-cyan disabled:opacity-40">
                      Add {parsePreview.valid.length} valid row(s) to grid
                    </button>
                    <button type="button" onClick={() => setParsePreview(null)} className="text-xs font-medium px-3 py-1.5 rounded-lg bg-white/10 text-white/70">
                      Dismiss
                    </button>
                  </div>
                </div>
              )}

              <div className="overflow-x-auto scroll-thin">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-white/40 uppercase">
                      <th className="py-2 pr-2">Name *</th>
                      <th className="py-2 pr-2">SKU</th>
                      <th className="py-2 pr-2">Category</th>
                      <th className="py-2 pr-2">Unit *</th>
                      <th className="py-2 pr-2">Price (PKR) *</th>
                      <th className="py-2 pr-2">MOQ</th>
                      <th className="py-2 pr-2">Lead (days)</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item, idx) => (
                      <tr key={idx} className="border-t border-white/10">
                        <td className="py-1.5 pr-2"><input className={inputCls} value={item.name} onChange={(e) => updateRow(idx, { name: e.target.value })} /></td>
                        <td className="py-1.5 pr-2"><input className={inputCls} value={item.sku || ""} onChange={(e) => updateRow(idx, { sku: e.target.value })} /></td>
                        <td className="py-1.5 pr-2">
                          <select className={inputCls} value={item.category || ""} onChange={(e) => updateRow(idx, { category: e.target.value })}>
                            <option value="" className="bg-navy-900">—</option>
                            {categories.map((c) => <option key={c} value={c} className="bg-navy-900">{c}</option>)}
                          </select>
                        </td>
                        <td className="py-1.5 pr-2"><input className={inputCls} value={item.unit} onChange={(e) => updateRow(idx, { unit: e.target.value })} /></td>
                        <td className="py-1.5 pr-2"><input type="number" className={inputCls} value={item.unit_price} onChange={(e) => updateRow(idx, { unit_price: Number(e.target.value) })} /></td>
                        <td className="py-1.5 pr-2"><input type="number" className={inputCls} value={item.moq ?? ""} onChange={(e) => updateRow(idx, { moq: e.target.value ? Number(e.target.value) : undefined })} /></td>
                        <td className="py-1.5 pr-2"><input type="number" className={inputCls} value={item.lead_time_days ?? ""} onChange={(e) => updateRow(idx, { lead_time_days: e.target.value ? Number(e.target.value) : undefined })} /></td>
                        <td className="py-1.5"><button type="button" onClick={() => removeRow(idx)} className="text-white/40 hover:text-destructive"><Trash2 size={15} /></button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button type="button" onClick={addManualRow} className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/15 text-white">
                <Plus size={14} /> Add Row
              </button>
            </div>
          )}

          {/* STEP 5 — Review & Submit */}
          {step === 5 && (
            <div className="space-y-5">
              <h2 className="text-lg font-heading font-bold text-white mb-1">Review &amp; Submit</h2>
              <div className="grid sm:grid-cols-2 gap-4 text-sm">
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-white/40 text-xs uppercase mb-1">Company</p>
                  <p className="text-white">{form.legal_company_name} ({form.business_type})</p>
                  <p className="text-white/60">{form.city}, {form.province}</p>
                </div>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-white/40 text-xs uppercase mb-1">Contact</p>
                  <p className="text-white">{form.contact_name}</p>
                  <p className="text-white/60">{form.order_email} · {form.mobile}</p>
                </div>
                <div className="bg-white/5 rounded-lg p-4 sm:col-span-2">
                  <p className="text-white/40 text-xs uppercase mb-1">Catalogue</p>
                  <p className="text-white">{items.length} item(s) · {documents.length} document(s) attached</p>
                </div>
              </div>

              {/* Honeypot — hidden from real users via CSS, bots fill every field */}
              <input
                type="text" tabIndex={-1} autoComplete="off" value={honeypot}
                onChange={(e) => setHoneypot(e.target.value)}
                className="absolute opacity-0 pointer-events-none -z-10 w-0 h-0"
                aria-hidden="true"
              />

              <label className="flex items-start gap-3 cursor-pointer">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1" />
                <span className="text-sm text-white/70">
                  I confirm the information provided is accurate and agree to NEXUS ERP's vendor terms.
                  I understand this submission does not guarantee approval.
                </span>
              </label>

              <button
                type="button" onClick={handleSubmit} disabled={submitting}
                className="w-full py-3 font-semibold rounded-lg bg-primary text-white hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {submitting ? <Loader2 size={16} className="animate-spin" /> : null}
                Submit Application
              </button>
            </div>
          )}

          {/* Nav buttons */}
          <div className="flex items-center justify-between mt-8 pt-6 border-t border-white/10">
            <button
              type="button" onClick={goBack} disabled={step === 0}
              className="inline-flex items-center gap-1 text-sm text-white/60 hover:text-white disabled:opacity-30"
            >
              <ChevronLeft size={16} /> Back
            </button>
            {step < STEPS.length - 1 && (
              <button
                type="button" onClick={goNext}
                className="inline-flex items-center gap-1 text-sm font-medium px-5 py-2.5 rounded-lg bg-primary text-white hover:opacity-90"
              >
                Next <ChevronRight size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
};

export default BecomeVendor;
