// src/pages/Payments.tsx
// Admin-only (/admin/payments). Everything money-related for vendor orders,
// in PKR only: the organisation's payment methods, a ledger of every
// order's escrow hold -> capture -> vendor payout, and a plain explanation
// of when each step happens. Backed by ai-module/payments.py.
import { useCallback, useEffect, useState, Fragment } from "react";
import { useNavigate } from "react-router-dom";
import {
  Loader2, Wallet, Lock, Clock, CheckCircle2, AlertTriangle, Landmark, Smartphone, Zap, Plus, Trash2,
  Star, Search, ChevronDown, ChevronRight, ShieldCheck, Link2, Receipt, Truck, PackageCheck, Send,
  Copy, Download, Banknote, X,
} from "lucide-react";
import {
  getPaymentsConfig, getPaymentsSummary, getPaymentsLedger, listPaymentMethods, createPaymentMethod,
  setDefaultPaymentMethod, removePaymentMethod, getOrderPaymentTransactions, authorizeOrderPayment,
  retryOrderCapture, releaseVendorPayout, subscribeToNotifications,
  getPendingTransfers, confirmManualPayout, downloadPendingTransfersCsv, PendingTransfer,
  PaymentsConfig, PaymentsSummary, PaymentLedgerRow, PaymentMethod, PaymentMethodType, PaymentTransaction,
} from "@/services/api";
import { useToast } from "@/hooks/use-toast";
import { formatPKR } from "@/lib/currency";
import FieldError from "@/components/FieldError";
import { validate, required, minLength, errorInputClass } from "@/lib/validation";

import ModalPortal from "@/components/ModalPortal";
type Tab = "ledger" | "methods" | "flow";

const METHOD_ICON: Record<PaymentMethodType, typeof Landmark> = {
  bank_transfer: Landmark,
  raast: Zap,
  jazzcash: Smartphone,
  easypaisa: Smartphone,
};

const IDENTIFIER_HINT: Record<PaymentMethodType, { label: string; placeholder: string }> = {
  bank_transfer: { label: "IBAN", placeholder: "PK36 SCBL 0000 0011 2345 6702" },
  raast: { label: "Raast ID or IBAN", placeholder: "03001234567 or PK36…" },
  jazzcash: { label: "JazzCash wallet number", placeholder: "03001234567" },
  easypaisa: { label: "Easypaisa wallet number", placeholder: "03451234567" },
};

const PAYMENT_CHIP: Record<string, string> = {
  "Not Required": "bg-muted text-muted-foreground",
  "Payment Required": "bg-warning/10 text-warning",
  Authorized: "bg-primary/10 text-primary",
  Captured: "bg-success/10 text-success",
  Cancelled: "bg-muted text-muted-foreground",
  Failed: "bg-destructive/10 text-destructive",
};
const PAYMENT_LABEL: Record<string, string> = {
  "Payment Required": "Needs payment method",
  Authorized: "Held in escrow",
  Captured: "Captured",
};

const PAYOUT_CHIP: Record<string, string> = {
  "Not Scheduled": "bg-muted text-muted-foreground",
  "Awaiting Transfer": "bg-destructive/10 text-destructive",
  Scheduled: "bg-warning/10 text-warning",
  Paid: "bg-success/10 text-success",
  Failed: "bg-destructive/10 text-destructive",
  "Not Applicable": "bg-muted text-muted-foreground",
};
const PAYOUT_LABEL: Record<string, string> = {
  "Not Scheduled": "After delivery",
  "Awaiting Transfer": "Transfer to make",
  "Not Applicable": "—",
};

const FILTERS: { key: string; label: string; params: { payment_status?: string; payout_status?: string } }[] = [
  { key: "all", label: "All", params: {} },
  { key: "required", label: "Needs payment method", params: { payment_status: "Payment Required" } },
  { key: "held", label: "Held in escrow", params: { payment_status: "Authorized" } },
  { key: "scheduled", label: "Payout scheduled", params: { payout_status: "Scheduled" } },
  { key: "transfer", label: "Transfer to make", params: { payout_status: "Awaiting Transfer" } },
  { key: "paid", label: "Paid", params: { payout_status: "Paid" } },
  { key: "failed", label: "Failed", params: { payment_status: "Failed" } },
];

const Chip = ({ cls, children }: { cls: string; children: React.ReactNode }) => (
  <span className={`inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap ${cls}`}>{children}</span>
);

const fmtDate = (d: string | null) => (d ? new Date(d).toLocaleString("en-PK", { dateStyle: "medium", timeStyle: "short" }) : "—");

// ─────────────────────────────────────────────────────────────────────────────

const Payments = () => {
  const { toast } = useToast();
  const [tab, setTab] = useState<Tab>("ledger");
  const [config, setConfig] = useState<PaymentsConfig | null>(null);
  const [summary, setSummary] = useState<PaymentsSummary | null>(null);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [loading, setLoading] = useState(true);

  const loadTop = useCallback(async () => {
    try {
      const [c, s, m] = await Promise.all([getPaymentsConfig(), getPaymentsSummary(), listPaymentMethods()]);
      setConfig(c);
      setSummary(s);
      setMethods(m.methods);
    } catch {
      toast({ title: "Failed to load payments", variant: "destructive" });
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadTop(); }, [loadTop]);

  if (loading || !config || !summary) {
    return <div className="flex items-center justify-center h-64"><Loader2 className="animate-spin text-primary" size={36} /></div>;
  }

  const defaultMethod = methods.find((m) => m.is_default);

  const cards = [
    { label: "Held in escrow", value: summary.held_in_escrow, sub: `${summary.held_count} order(s) awaiting delivery`, icon: Lock, color: "text-primary" },
    { label: "Payouts scheduled", value: summary.payouts_pending, sub: `${summary.payouts_pending_count} vendor payout(s) due`, icon: Clock, color: "text-warning" },
    { label: "Paid to vendors", value: summary.paid_out, sub: `${summary.paid_out_count} payout(s) completed`, icon: CheckCircle2, color: "text-success" },
    { label: "Platform fees", value: summary.fees_collected, sub: `${(config.platform_fee_rate * 100).toFixed(1)}% blockchain verification fee`, icon: Receipt, color: "text-accent-cyan" },
  ];

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-heading font-bold">Payments</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Escrow, capture and vendor payouts for every vendor order. Payouts go out{" "}
            {config.payout_settlement_hours === 0 ? "immediately" : `${config.payout_settlement_hours}h`} after receipt is approved.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full bg-success/10 text-success">
            <Wallet size={13} /> All amounts in PKR (Pakistani Rupee)
          </span>
          <span className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full ${
            config.provider === "mock" ? "bg-warning/10 text-warning" : "bg-primary/10 text-primary"
          }`}>
            <Banknote size={12} /> {config.provider_label}
          </span>
        </div>
      </div>

      {config.provider === "mock" && (
        <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm">
          <AlertTriangle size={18} className="text-warning flex-shrink-0 mt-0.5" />
          <p className="text-muted-foreground">
            <span className="font-semibold text-foreground">Simulated payments.</span> No real money moves — vendor payouts are marked paid automatically.
            Set <code className="font-mono text-xs">PAYMENT_PROVIDER=manual</code> on the server to use real bank transfers.
          </p>
        </div>
      )}

      {(config.provider === "manual" || summary.awaiting_transfer_count > 0) && (
        <PendingTransfers count={summary.awaiting_transfer_count} onChanged={loadTop} />
      )}

      {!defaultMethod && (
        <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm">
          <AlertTriangle size={18} className="text-warning flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold text-foreground">No default payment method</p>
            <p className="text-muted-foreground">
              Funds can't be held when a vendor accepts an order, and receipts can't be approved, until one is set.
              {summary.awaiting_method_count > 0 && ` ${summary.awaiting_method_count} order(s) (${formatPKR(summary.awaiting_method)}) are waiting.`}
            </p>
          </div>
          <button onClick={() => setTab("methods")} className="text-sm font-semibold px-3 py-1.5 rounded-lg bg-warning text-white flex-shrink-0">
            Add method
          </button>
        </div>
      )}
      {summary.failed_count > 0 && (
        <div className="flex items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm">
          <AlertTriangle size={18} className="text-destructive flex-shrink-0" />
          <p className="flex-1"><span className="font-semibold">{summary.failed_count} payment(s) need attention</span> — see the Failed filter in the ledger.</p>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {cards.map((c) => (
          <div key={c.label} className="glass-card p-4">
            <c.icon size={16} className={c.color} />
            <p className="text-xl font-heading font-bold mt-1 font-mono tracking-tight">{formatPKR(c.value, { decimals: false })}</p>
            <p className="text-xs font-medium text-foreground">{c.label}</p>
            <p className="text-[11px] text-muted-foreground mt-0.5">{c.sub}</p>
          </div>
        ))}
      </div>

      <div className="flex gap-1 border-b border-border">
        {([
          ["ledger", "Ledger"],
          ["methods", `Payment Methods (${methods.length})`],
          ["flow", "How payments work"],
        ] as [Tab, string][]).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`px-4 py-2.5 text-sm font-medium -mb-px border-b-2 transition-colors ${
              tab === k ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "ledger" && <Ledger onChanged={loadTop} />}
      {tab === "methods" && <Methods methods={methods} config={config} onChanged={loadTop} />}
      {tab === "flow" && <Flow config={config} />}
    </div>
  );
};

// ─── Ledger ──────────────────────────────────────────────────────────────────

const Ledger = ({ onChanged }: { onChanged: () => void }) => {
  const { toast } = useToast();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<PaymentLedgerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [txns, setTxns] = useState<Record<string, PaymentTransaction[]>>({});
  const [acting, setActing] = useState<string | null>(null);
  const [recordFor, setRecordFor] = useState<PaymentLedgerRow | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const f = FILTERS.find((x) => x.key === filter)!;
      const res = await getPaymentsLedger({ ...f.params, search: search || undefined });
      setRows(res.orders);
    } catch {
      if (!silent) toast({ title: "Failed to load ledger", variant: "destructive" });
    } finally {
      if (!silent) setLoading(false);
    }
  }, [filter, search, toast]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const unsubscribe = subscribeToNotifications((n) => {
      if (n.entity_type === "vendor_order") load(true);
    });
    return unsubscribe;
  }, [load]);

  const toggle = async (id: string) => {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    try {
      const res = await getOrderPaymentTransactions(id);
      setTxns((t) => ({ ...t, [id]: res.transactions }));
    } catch {
      toast({ title: "Failed to load transactions", variant: "destructive" });
    }
  };

  const act = async (id: string, fn: () => Promise<{ message: string }>) => {
    setActing(id);
    try {
      const res = await fn();
      toast({ title: res.message });
      await load(true);
      onChanged();
      if (expanded === id) {
        const t = await getOrderPaymentTransactions(id);
        setTxns((x) => ({ ...x, [id]: t.transactions }));
      }
    } catch (e: unknown) {
      toast({ title: e instanceof Error ? e.message : "Action failed", variant: "destructive" });
    } finally {
      setActing(null);
    }
  };

  const actionFor = (r: PaymentLedgerRow): { label: string; fn?: () => Promise<{ message: string }> } | null => {
    if (r.payout_status === "Awaiting Transfer") return { label: "Record transfer" };
    if (r.contract_status === "Executed" && (r.payment_status === "Failed" || r.payment_status === "Payment Required"))
      return { label: "Retry capture", fn: () => retryOrderCapture(r.id) };
    if (r.payment_status === "Payment Required" || r.payment_status === "Failed")
      return { label: "Authorize", fn: () => authorizeOrderPayment(r.id) };
    if (r.payment_status === "Captured" && (r.payout_status === "Scheduled" || r.payout_status === "Failed"))
      return { label: r.payout_status === "Failed" ? "Retry payout" : "Pay now", fn: () => releaseVendorPayout(r.id) };
    return null;
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex gap-1.5 flex-wrap">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`text-xs font-medium px-3 py-1.5 rounded-full transition-colors ${
                filter === f.key ? "bg-primary text-white" : "bg-muted/40 text-muted-foreground hover:bg-muted/60"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="relative ml-auto w-full sm:w-64">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Order code or vendor…"
            className="pl-9 pr-3 py-2 text-sm rounded-lg border border-border bg-background w-full"
          />
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-40"><Loader2 className="animate-spin text-primary" size={28} /></div>
      ) : rows.length === 0 ? (
        <div className="glass-card p-10 text-center text-sm text-muted-foreground">No orders match this filter.</div>
      ) : (
        <div className="glass-card overflow-x-auto scroll-thin">
          <table className="w-full text-sm min-w-[880px]">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                <th className="px-4 py-3 w-6" />
                <th className="px-2 py-3">Order</th>
                <th className="px-3 py-3 text-right">Order total</th>
                <th className="px-3 py-3 text-right">Vendor payout</th>
                <th className="px-3 py-3">Payment</th>
                <th className="px-3 py-3">Payout</th>
                <th className="px-3 py-3">Contract</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const action = actionFor(r);
                const open = expanded === r.id;
                return (
                  <Fragment key={r.id}>
                    <tr className="border-b border-border/60 hover:bg-muted/20">
                      <td className="px-4 py-3">
                        <button onClick={() => toggle(r.id)} className="text-muted-foreground hover:text-foreground" aria-label="Show transactions">
                          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                        </button>
                      </td>
                      <td className="px-2 py-3">
                        <button onClick={() => navigate(`/admin/tracking/${r.id}`)} className="font-mono font-semibold hover:text-primary">{r.order_code}</button>
                        <p className="text-xs text-muted-foreground truncate max-w-[200px]">{r.vendor_name}</p>
                      </td>
                      <td className="px-3 py-3 text-right font-mono whitespace-nowrap">
                        {formatPKR(r.total_amount)}
                        {r.platform_fee > 0 && <p className="text-[11px] text-muted-foreground">incl. fee {formatPKR(r.platform_fee)}</p>}
                      </td>
                      <td className="px-3 py-3 text-right font-mono whitespace-nowrap">
                        {formatPKR(r.vendor_payout_amount)}
                        <p className="text-[11px] text-muted-foreground">{r.vendor_bank_iban ? `IBAN ${r.vendor_bank_iban.slice(-8)}` : "No IBAN on file"}</p>
                      </td>
                      <td className="px-3 py-3">
                        <Chip cls={PAYMENT_CHIP[r.payment_status] || "bg-muted"}>{PAYMENT_LABEL[r.payment_status] || r.payment_status}</Chip>
                        {r.payment_method_label && <p className="text-[11px] text-muted-foreground mt-1">{r.payment_method_label}</p>}
                      </td>
                      <td className="px-3 py-3">
                        <Chip cls={PAYOUT_CHIP[r.payout_status] || "bg-muted"}>{PAYOUT_LABEL[r.payout_status] ?? r.payout_status}</Chip>
                        <p className="text-[11px] text-muted-foreground mt-1">
                          {r.payout_status === "Scheduled" && `Due ${fmtDate(r.payout_due_at)}`}
                          {r.payout_status === "Paid" && fmtDate(r.payout_paid_at)}
                          {r.payout_status === "Paid" && r.payout_ref && <span className="block font-mono">{r.payout_ref}</span>}
                        </p>
                      </td>
                      <td className="px-3 py-3">
                        <span className="text-xs font-medium">{r.contract_status}</span>
                        <p className="text-[11px] mt-0.5 flex items-center gap-1">
                          {r.chain_pending > 0 ? (
                            <span className="text-warning flex items-center gap-1"><Clock size={10} /> {r.chain_pending} tx pending</span>
                          ) : r.chain_confirmed > 0 ? (
                            <span className="text-success flex items-center gap-1"><ShieldCheck size={10} /> {r.chain_confirmed} on-chain</span>
                          ) : (
                            <span className="text-muted-foreground flex items-center gap-1"><Link2 size={10} /> {r.chain_network || "—"}</span>
                          )}
                        </p>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {action && (
                          <button
                            onClick={() => (action.fn ? act(r.id, action.fn) : setRecordFor(r))}
                            disabled={acting === r.id}
                            className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-primary text-white hover:opacity-90 disabled:opacity-50"
                          >
                            {acting === r.id && <Loader2 size={12} className="animate-spin" />} {action.label}
                          </button>
                        )}
                      </td>
                    </tr>
                    {open && (
                      <tr className="bg-muted/10 border-b border-border/60">
                        <td />
                        <td colSpan={7} className="px-2 py-3">
                          <TxnList txns={txns[r.id]} />
                          {r.vendor_payment_terms && (
                            <p className="text-[11px] text-muted-foreground mt-2">Vendor's stated payment terms: {r.vendor_payment_terms}</p>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {recordFor && (
        <RecordTransferModal
          orderId={recordFor.id}
          orderCode={recordFor.order_code}
          amount={recordFor.vendor_payout_amount ?? recordFor.subtotal}
          vendorName={recordFor.vendor_name}
          onClose={() => setRecordFor(null)}
          onDone={() => { setRecordFor(null); load(true); onChanged(); }}
        />
      )}
    </div>
  );
};

// ─── Manual bank transfers ───────────────────────────────────────────────────

const CopyValue = ({ value, mono = true }: { value: string; mono?: boolean }) => {
  const { toast } = useToast();
  return (
    <button
      onClick={() => navigator.clipboard?.writeText(value).then(() => toast({ title: "Copied" })).catch(() => {})}
      className={`group inline-flex items-center gap-1.5 text-left hover:text-primary ${mono ? "font-mono" : ""}`}
      title="Copy"
    >
      <span className="break-all">{value}</span>
      <Copy size={11} className="opacity-40 group-hover:opacity-100 flex-shrink-0" />
    </button>
  );
};

const PendingTransfers = ({ count, onChanged }: { count: number; onChanged: () => void }) => {
  const { toast } = useToast();
  const [items, setItems] = useState<PendingTransfer[] | null>(null);
  const [total, setTotal] = useState(0);
  const [recordFor, setRecordFor] = useState<PendingTransfer | null>(null);

  const load = useCallback(() => {
    getPendingTransfers()
      .then((r) => { setItems(r.transfers); setTotal(r.total); })
      .catch(() => toast({ title: "Failed to load pending transfers", variant: "destructive" }));
  }, [toast]);

  useEffect(() => { load(); }, [load, count]);

  if (!items) return null;
  if (items.length === 0) {
    return (
      <div className="glass-card px-4 py-3 text-sm text-muted-foreground flex items-center gap-2">
        <CheckCircle2 size={16} className="text-success" /> No vendor transfers waiting to be made.
      </div>
    );
  }

  return (
    <div className="glass-card p-5 space-y-4 ring-2 ring-destructive/20">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="font-heading font-semibold flex items-center gap-2"><Banknote size={17} className="text-destructive" /> Transfers to make ({items.length})</p>
          <p className="text-xs text-muted-foreground mt-1 max-w-xl">
            Send each amount from your bank's corporate portal by Raast or IBFT, using the reference shown, then record the bank's
            transaction ID here. The vendor is only notified once it's recorded. Total: <span className="font-semibold text-foreground">{formatPKR(total)}</span>
          </p>
        </div>
        <button
          onClick={() => downloadPendingTransfersCsv().catch((e) => toast({ title: e.message, variant: "destructive" }))}
          className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border border-border hover:bg-muted/30"
        >
          <Download size={13} /> Bulk-transfer CSV
        </button>
      </div>
      <div className="grid lg:grid-cols-2 gap-3">
        {items.map((t) => (
          <div key={t.id} className="rounded-lg border border-border p-4 text-xs space-y-1.5">
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="font-mono font-semibold text-sm">{t.order_code}</span>
              <span className="font-mono font-bold text-sm text-primary">{formatPKR(t.amount)}</span>
            </div>
            <p className="flex gap-2"><span className="text-muted-foreground w-24 flex-shrink-0">Pay to</span><CopyValue value={t.bank_account_title || t.vendor_name} mono={false} /></p>
            <p className="flex gap-2"><span className="text-muted-foreground w-24 flex-shrink-0">Bank</span><span>{t.bank_name || "—"}</span></p>
            <p className="flex gap-2"><span className="text-muted-foreground w-24 flex-shrink-0">IBAN</span>{t.bank_iban ? <CopyValue value={t.bank_iban} /> : <span className="text-destructive">Missing</span>}</p>
            <p className="flex gap-2"><span className="text-muted-foreground w-24 flex-shrink-0">Amount</span><CopyValue value={t.amount.toFixed(2)} /></p>
            <p className="flex gap-2"><span className="text-muted-foreground w-24 flex-shrink-0">Reference</span><CopyValue value={t.transfer_reference} /></p>
            <button onClick={() => setRecordFor(t)} className="mt-2 w-full text-xs font-semibold px-3 py-2 rounded-lg bg-primary text-white hover:opacity-90">
              I've sent it — record bank transaction ID
            </button>
          </div>
        ))}
      </div>
      {recordFor && (
        <RecordTransferModal
          orderId={recordFor.id}
          orderCode={recordFor.order_code}
          amount={recordFor.amount}
          vendorName={recordFor.vendor_name}
          onClose={() => setRecordFor(null)}
          onDone={() => { setRecordFor(null); load(); onChanged(); }}
        />
      )}
    </div>
  );
};

const RecordTransferModal = ({ orderId, orderCode, amount, vendorName, onClose, onDone }: {
  orderId: string; orderCode: string; amount: number | null; vendorName: string; onClose: () => void; onDone: () => void;
}) => {
  const { toast } = useToast();
  const [ref, setRef] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [refError, setRefError] = useState<string | null>(null);
  const vRef = () => validate(ref, required("Bank transaction ID is required"), minLength(4, "Must be at least 4 characters"));
  const submit = async () => {
    const err = vRef();
    setRefError(err);
    if (err) return;
    setSaving(true);
    try {
      const res = await confirmManualPayout(orderId, ref.trim(), note.trim() || undefined);
      toast({ title: res.message });
      onDone();
    } catch (e: unknown) {
      toast({ title: e instanceof Error ? e.message : "Could not record transfer", variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };
  return (
    <ModalPortal><div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-background rounded-xl p-6 max-w-md w-full space-y-4">
        <div className="flex items-start justify-between">
          <h3 className="font-heading font-bold text-lg">Record bank transfer</h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X size={18} /></button>
        </div>
        <p className="text-sm text-muted-foreground">
          {formatPKR(amount)} to {vendorName} for <span className="font-mono">{orderCode}</span>. Only record this after the bank shows the transfer as successful.
        </p>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">Bank transaction ID / reference</label>
          <input
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            onBlur={() => setRefError(vRef())}
            placeholder="e.g. Raast TxID or IBFT reference"
            className={`w-full px-3 py-2 text-sm rounded-lg border bg-background font-mono ${refError ? errorInputClass : "border-border"}`}
            autoFocus
          />
          <FieldError message={refError} />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">Note (optional)</label>
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Sent from HBL corporate portal" className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background" />
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm rounded-lg border border-border">Cancel</button>
          <button onClick={submit} disabled={saving || ref.trim().length < 4} className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg bg-success text-white disabled:opacity-50">
            {saving && <Loader2 size={14} className="animate-spin" />} Mark as paid
          </button>
        </div>
      </div>
    </div></ModalPortal>
  );
};

export const TxnList = ({ txns }: { txns?: PaymentTransaction[] }) => {
  if (!txns) return <Loader2 size={16} className="animate-spin text-primary" />;
  if (txns.length === 0) return <p className="text-xs text-muted-foreground">No payment transactions yet.</p>;
  const KIND: Record<string, string> = { authorize: "Authorize (hold)", capture: "Capture", cancel: "Release hold", payout: "Vendor payout" };
  return (
    <div className="space-y-1.5">
      {txns.map((t) => (
        <div key={t.id} className="flex items-center gap-3 text-xs flex-wrap">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${t.status === "Succeeded" ? "bg-success" : t.status === "Failed" ? "bg-destructive" : "bg-muted-foreground"}`} />
          <span className="font-medium w-28">{KIND[t.kind] || t.kind}</span>
          <span className="font-mono w-36">{formatPKR(t.amount)}</span>
          <span className="text-muted-foreground w-36">{fmtDate(t.created_at)}</span>
          <span className="font-mono text-muted-foreground truncate max-w-[220px]">{t.provider_ref || t.note || t.status}</span>
          {t.status !== "Succeeded" && t.note && <span className="text-muted-foreground">({t.note})</span>}
        </div>
      ))}
    </div>
  );
};

// ─── Payment methods ─────────────────────────────────────────────────────────

const Methods = ({ methods, config, onChanged }: { methods: PaymentMethod[]; config: PaymentsConfig; onChanged: () => void }) => {
  const { toast } = useToast();
  const [showForm, setShowForm] = useState(methods.length === 0);
  const [type, setType] = useState<PaymentMethodType>("bank_transfer");
  const [label, setLabel] = useState("");
  const [title, setTitle] = useState("");
  const [bank, setBank] = useState("");
  const [ident, setIdent] = useState("");
  const [makeDefault, setMakeDefault] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ label?: string | null; title?: string | null; bank?: string | null; ident?: string | null }>({});

  const vLabel = () => validate(label, required("Label is required"));
  const vTitle = () => validate(title, required("Account title is required"));
  const vBank = () => validate(bank, required("Bank is required"));
  const vIdent = () => validate(ident, required(`${IDENTIFIER_HINT[type].label} is required`));

  const submit = async () => {
    const errs = {
      label: vLabel(), title: vTitle(),
      bank: type === "bank_transfer" ? vBank() : null,
      ident: vIdent(),
    };
    setFieldErrors(errs);
    if (errs.label || errs.title || errs.bank || errs.ident) return;
    setSaving(true);
    try {
      const res = await createPaymentMethod({
        method_type: type, label, account_title: title, bank_name: type === "bank_transfer" ? bank : undefined,
        account_identifier: ident, is_default: makeDefault,
      });
      toast({ title: res.message });
      setLabel(""); setTitle(""); setBank(""); setIdent(""); setMakeDefault(false); setShowForm(false); setFieldErrors({});
      onChanged();
    } catch (e: unknown) {
      toast({ title: e instanceof Error ? e.message : "Could not add payment method", variant: "destructive" });
    } finally {
      setSaving(false);
    }
  };

  const run = async (id: string, fn: () => Promise<{ message: string }>) => {
    setBusyId(id);
    try {
      const res = await fn();
      toast({ title: res.message });
      onChanged();
    } catch (e: unknown) {
      toast({ title: e instanceof Error ? e.message : "Action failed", variant: "destructive" });
    } finally {
      setBusyId(null);
    }
  };

  const inputCls = "w-full px-3 py-2 text-sm rounded-lg border border-border bg-background";

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground max-w-2xl">
        The <span className="font-medium text-foreground">default</span> method is where funds are held from when a vendor accepts an order,
        and captured from once the orderer approves receipt. Only PKR accounts are supported.
      </p>

      {methods.length > 0 && (
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {methods.map((m) => {
            const Icon = METHOD_ICON[m.method_type] || Landmark;
            return (
              <div key={m.id} className={`glass-card p-4 space-y-3 ${m.is_default ? "ring-2 ring-primary/40" : ""}`}>
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center flex-shrink-0"><Icon size={18} /></div>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold truncate">{m.label}</p>
                    <p className="text-xs text-muted-foreground">{m.method_type_label}{m.bank_name ? ` · ${m.bank_name}` : ""}</p>
                  </div>
                  {m.is_default && <Chip cls="bg-primary/10 text-primary"><Star size={10} className="mr-1" /> Default</Chip>}
                </div>
                <div className="text-xs space-y-0.5">
                  <p className="text-muted-foreground">{m.account_title}</p>
                  <p className="font-mono tracking-wider">{m.account_identifier}</p>
                </div>
                <div className="flex gap-2 pt-1">
                  {!m.is_default && (
                    <button
                      onClick={() => run(m.id, () => setDefaultPaymentMethod(m.id))}
                      disabled={busyId === m.id}
                      className="text-xs font-medium px-3 py-1.5 rounded-lg border border-border hover:bg-muted/30 disabled:opacity-50"
                    >
                      Make default
                    </button>
                  )}
                  <button
                    onClick={() => run(m.id, () => removePaymentMethod(m.id))}
                    disabled={busyId === m.id}
                    className="text-xs font-medium px-3 py-1.5 rounded-lg text-destructive hover:bg-destructive/10 disabled:opacity-50 inline-flex items-center gap-1 ml-auto"
                  >
                    <Trash2 size={12} /> Remove
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!showForm ? (
        <button onClick={() => setShowForm(true)} className="inline-flex items-center gap-1.5 text-sm font-semibold px-4 py-2 rounded-lg btn-navy">
          <Plus size={15} /> Add payment method
        </button>
      ) : (
        <div className="glass-card p-5 space-y-4 max-w-2xl">
          <p className="font-heading font-semibold">New payment method</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {config.method_types.map((t) => {
              const Icon = METHOD_ICON[t.value];
              return (
                <button
                  key={t.value}
                  onClick={() => setType(t.value)}
                  className={`flex flex-col items-center gap-1 py-3 rounded-lg border text-xs font-medium transition-colors ${
                    type === t.value ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted/30"
                  }`}
                >
                  <Icon size={18} /> {t.label}
                </button>
              );
            })}
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Label</label>
              <input
                className={`${inputCls} ${fieldErrors.label ? errorInputClass : ""}`}
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                onBlur={() => setFieldErrors((f) => ({ ...f, label: vLabel() }))}
                placeholder="e.g. HBL Procurement Account"
              />
              <FieldError message={fieldErrors.label} />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Account title</label>
              <input
                className={`${inputCls} ${fieldErrors.title ? errorInputClass : ""}`}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                onBlur={() => setFieldErrors((f) => ({ ...f, title: vTitle() }))}
                placeholder="e.g. IESCO Procurement Dept"
              />
              <FieldError message={fieldErrors.title} />
            </div>
            {type === "bank_transfer" && (
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">Bank</label>
                <input
                  className={`${inputCls} ${fieldErrors.bank ? errorInputClass : ""}`}
                  value={bank}
                  onChange={(e) => setBank(e.target.value)}
                  onBlur={() => setFieldErrors((f) => ({ ...f, bank: vBank() }))}
                  placeholder="e.g. Habib Bank Limited"
                />
                <FieldError message={fieldErrors.bank} />
              </div>
            )}
            <div className={type === "bank_transfer" ? "" : "sm:col-span-2"}>
              <label className="block text-xs font-medium text-muted-foreground mb-1">{IDENTIFIER_HINT[type].label}</label>
              <input
                className={`${inputCls} font-mono ${fieldErrors.ident ? errorInputClass : ""}`}
                value={ident}
                onChange={(e) => setIdent(e.target.value)}
                onBlur={() => setFieldErrors((f) => ({ ...f, ident: vIdent() }))}
                placeholder={IDENTIFIER_HINT[type].placeholder}
              />
              <FieldError message={fieldErrors.ident} />
            </div>
          </div>
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={makeDefault || methods.length === 0} disabled={methods.length === 0} onChange={(e) => setMakeDefault(e.target.checked)} />
              Use as default {methods.length === 0 && <span className="text-xs text-muted-foreground">(first method is always default)</span>}
            </label>
            <div className="flex gap-2">
              {methods.length > 0 && (
                <button onClick={() => setShowForm(false)} className="text-sm px-4 py-2 rounded-lg border border-border">Cancel</button>
              )}
              <button
                onClick={submit}
                disabled={saving || !label.trim() || !title.trim() || !ident.trim() || (type === "bank_transfer" && !bank.trim())}
                className="inline-flex items-center gap-1.5 text-sm font-semibold px-4 py-2 rounded-lg btn-navy disabled:opacity-50"
              >
                {saving && <Loader2 size={14} className="animate-spin" />} Save method
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ─── How payments work ───────────────────────────────────────────────────────

const Flow = ({ config }: { config: PaymentsConfig }) => {
  const fee = `${(config.platform_fee_rate * 100).toFixed(1)}%`;
  const settle = config.payout_settlement_hours === 0 ? "immediately" : `${config.payout_settlement_hours} hours`;
  const steps = [
    { icon: Receipt, title: "Order placed", who: "Admin / Procurement Manager",
      body: `Order total = vendor's catalogue price (subtotal) + ${fee} blockchain verification fee, in PKR. Nothing is charged yet.` },
    { icon: Lock, title: "Vendor accepts → funds held in escrow", who: "Vendor (email link)",
      body: "The full total is authorized and held on the default payment method. The ShipmentEscrow smart contract is created on-chain with the amount (in paisa) and a hash of the payment reference, binding the contract to those exact funds." },
    { icon: Truck, title: "Shipment checkpoints", who: "Vendor or staff",
      body: "Dispatched → In Transit → Out for Delivery. Each checkpoint is recorded on-chain. Money stays held — the vendor is not paid for shipping progress." },
    { icon: PackageCheck, title: "Delivery confirmed & approved", who: "Orderer only (enforced on-chain)",
      body: "The orderer confirms arrival, inspects the goods, then approves receipt. Approval executes the contract on-chain and captures the held funds. Receipt cannot be approved before arrival, and without held funds." },
    config.automatic_payouts
      ? { icon: Send, title: `Vendor paid ${settle} later`, who: "Automatic",
          body: `After a ${settle} settlement window (time to catch a mistaken approval), the subtotal is transferred to the vendor's registered IBAN and the vendor is emailed a payment confirmation. The platform fee is retained. An admin can pay early with "Pay now".` }
      : { icon: Send, title: `Vendor paid by bank transfer, ${settle} later`, who: "Admin",
          body: `After a ${settle} settlement window, the payout appears under "Transfers to make" with the vendor's account title, bank, IBAN, amount and a reference. An admin sends it from the bank's corporate portal by Raast (instant) or IBFT — one at a time or via the bulk CSV — then records the bank's transaction ID. Only then is it marked paid and the vendor emailed. The platform fee is retained.` },
  ];
  return (
    <div className="grid lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 glass-card p-6">
        <ol className="relative space-y-6">
          {steps.map((s, i) => (
            <li key={s.title} className="flex gap-4">
              <div className="flex flex-col items-center">
                <div className="w-9 h-9 rounded-full bg-primary/10 text-primary flex items-center justify-center flex-shrink-0"><s.icon size={17} /></div>
                {i < steps.length - 1 && <div className="w-px flex-1 bg-border mt-2" />}
              </div>
              <div className="pb-1">
                <p className="font-semibold">{i + 1}. {s.title}</p>
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground mt-0.5">{s.who}</p>
                <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
      <div className="space-y-3">
        <div className="glass-card p-5 space-y-2">
          <p className="font-semibold flex items-center gap-2"><AlertTriangle size={15} className="text-warning" /> If something goes wrong</p>
          <ul className="text-sm text-muted-foreground space-y-2 list-disc pl-4">
            <li><b className="text-foreground">Vendor rejects / never responds:</b> nothing was held, nothing to refund.</li>
            <li><b className="text-foreground">Dispute after arrival:</b> the contract freezes, funds stay held. An admin resolves it — cancel (hold released) or execute (captured, vendor paid on the normal schedule).</li>
            <li><b className="text-foreground">Cancelled before arrival:</b> an admin cancels the contract on-chain and the hold is released.</li>
            <li><b className="text-foreground">Vendor has no IBAN:</b> the payout fails and shows here for retry once the IBAN is added.</li>
          </ul>
        </div>
        <div className="glass-card p-5 text-sm text-muted-foreground space-y-1">
          <p className="font-semibold text-foreground flex items-center gap-2"><Wallet size={15} /> Currency & limits</p>
          <p>Every amount — orders, holds, captures, payouts, invoices — is Pakistani Rupees. Other currencies are rejected by the database.</p>
          {config.max_order_total && <p>Each order is capped at {formatPKR(config.max_order_total, { decimals: false })} so it clears as a single bank transfer.</p>}
          <p className="text-xs pt-1">
            {config.provider === "mock"
              ? "Payments are currently simulated — holds and transfers are recorded but no real money moves."
              : "Holds are earmarked in this ledger; real money moves only when an admin makes the bank transfer and records its reference."}
          </p>
        </div>
      </div>
    </div>
  );
};

export default Payments;
