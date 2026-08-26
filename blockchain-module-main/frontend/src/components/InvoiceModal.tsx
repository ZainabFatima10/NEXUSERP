// src/components/InvoiceModal.tsx
import { useEffect, useState } from "react";
import {
  X, Loader2, Download, ShieldCheck, CheckCircle2, Clock,
} from "lucide-react";
import { getInvoice, downloadInvoicePdf, Invoice } from "@/services/api";
import { useToast } from "@/hooks/use-toast";
import { LogoMark } from "@/components/Logo";

interface Props {
  orderId: string;
  onClose: () => void;
  /** Optional heads-up banner shown at the top, e.g. right after placing an order */
  successNote?: string;
}

const money = (v: number | null | undefined) =>
  v == null ? "Pending" : `USD ${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const InvoiceModal = ({ orderId, onClose, successNote }: Props) => {
  const { toast } = useToast();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const inv = await getInvoice(orderId);
        if (!cancelled) setInvoice(inv);
      } catch (e: unknown) {
        if (!cancelled) toast({ title: "Couldn't load invoice", description: String(e), variant: "destructive" });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [orderId, toast]);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await downloadInvoicePdf(orderId, invoice?.invoice_number || `invoice-${orderId}`);
    } catch (e: unknown) {
      toast({ title: "Download failed", description: String(e), variant: "destructive" });
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="glass-card w-full max-w-xl max-h-[92vh] overflow-hidden flex flex-col glow-cyan animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header — mirrors the PDF's navy band */}
        <div className="relative bg-navy-900 px-6 py-5 flex items-start justify-between flex-shrink-0">
          <div>
            <div className="flex items-center gap-2">
              <LogoMark size={28} className="flex-shrink-0" />
              <div>
                <p className="font-heading font-bold text-white leading-tight">NEXUS ERP</p>
                <p className="text-[10px] text-white/50 leading-tight">PowerGrid Optimizer</p>
              </div>
            </div>
          </div>
          <div className="text-right">
            <p className="font-heading font-bold text-white text-sm">INVOICE</p>
            <p className="text-[11px] text-white/50 font-mono mt-0.5">
              {invoice?.invoice_number || "…"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="absolute top-4 right-4 text-white/60 hover:text-white"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto scroll-thin p-6 space-y-5">
          {successNote && (
            <div className="flex items-start gap-2 bg-success/10 border border-success/20 rounded-lg p-3">
              <CheckCircle2 size={16} className="text-success mt-0.5 flex-shrink-0" />
              <p className="text-xs text-success font-medium">{successNote}</p>
            </div>
          )}

          {loading && (
            <div className="flex justify-center py-14">
              <Loader2 className="animate-spin text-primary" size={28} />
            </div>
          )}

          {!loading && invoice && (
            <>
              {/* Vendor / order meta */}
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Vendor</p>
                  <p className="font-medium">{invoice.vendor.name}</p>
                  <p className="text-xs text-muted-foreground">{invoice.vendor.email}</p>
                </div>
                <div className="text-right">
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Order</p>
                  <p className="font-mono text-primary text-sm">{invoice.order_code}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {new Date(invoice.issued_at).toLocaleDateString()}
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-xs px-2.5 py-1 rounded-full font-medium bg-primary/10 text-primary">
                  {invoice.status}
                </span>
                {invoice.expected_delivery && (
                  <span className="text-xs text-muted-foreground">
                    Expected delivery: {invoice.expected_delivery}
                  </span>
                )}
              </div>

              {/* Line items */}
              <div className="rounded-xl border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/30">
                    <tr>
                      <th className="text-left px-3 py-2 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Item</th>
                      <th className="text-right px-3 py-2 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Qty</th>
                      <th className="text-right px-3 py-2 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Unit Price</th>
                      <th className="text-right px-3 py-2 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Line Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50">
                    {invoice.line_items.map((li, i) => (
                      <tr key={i}>
                        <td className="px-3 py-2.5">
                          <p className="font-medium">{li.description}</p>
                          <p className="text-[10px] text-muted-foreground font-mono">{li.item_id}</p>
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono text-xs">
                          {li.quantity.toLocaleString()} {li.unit}
                        </td>
                        <td className="px-3 py-2.5 text-right font-mono text-xs">{money(li.unit_price)}</td>
                        <td className="px-3 py-2.5 text-right font-mono text-xs font-semibold">{money(li.line_total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Totals */}
              <div className="space-y-1.5 text-sm">
                {invoice.pricing_pending ? (
                  <div className="flex justify-between text-muted-foreground">
                    <span>Pricing</span>
                    <span className="flex items-center gap-1"><Clock size={12} /> Pending vendor confirmation</span>
                  </div>
                ) : (
                  <>
                    <div className="flex justify-between text-muted-foreground">
                      <span>Subtotal</span>
                      <span className="font-mono">{money(invoice.subtotal)}</span>
                    </div>
                    <div className="flex justify-between text-muted-foreground">
                      <span>Blockchain Verification Fee ({(invoice.blockchain_fee_rate * 100).toFixed(1)}%)</span>
                      <span className="font-mono">{money(invoice.blockchain_fee)}</span>
                    </div>
                    {invoice.tax_rate > 0 && (
                      <div className="flex justify-between text-muted-foreground">
                        <span>Tax ({(invoice.tax_rate * 100).toFixed(1)}%)</span>
                        <span className="font-mono">{money(invoice.tax)}</span>
                      </div>
                    )}
                    <div className="flex justify-between pt-2 mt-1 border-t border-border font-heading font-bold text-base">
                      <span>Total Due</span>
                      <span className="text-primary font-mono">{money(invoice.total)}</span>
                    </div>
                  </>
                )}
              </div>

              {/* Blockchain record */}
              <div className="flex items-start gap-2 bg-accent-cyan/5 border border-accent-cyan/20 rounded-lg p-3">
                <ShieldCheck size={16} className="text-accent-cyan mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-xs font-semibold text-foreground">Blockchain Record</p>
                  <p className="text-[11px] font-mono text-muted-foreground break-all mt-0.5">
                    {invoice.contract_hash || "Not yet assigned — generated once the vendor confirms this order."}
                  </p>
                  <p className="text-[11px] text-muted-foreground mt-0.5">
                    Contract status: {invoice.contract_status || "Pending"}
                  </p>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer actions */}
        <div className="p-4 border-t border-border/50 flex gap-2 flex-shrink-0">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 text-sm font-medium border border-border rounded-lg hover:bg-muted/30 transition-colors"
          >
            Close
          </button>
          <button
            onClick={handleDownload}
            disabled={loading || downloading}
            className="flex-1 py-2.5 text-sm font-semibold btn-navy flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            Download Invoice (PDF)
          </button>
        </div>
      </div>
    </div>
  );
};

export default InvoiceModal;
