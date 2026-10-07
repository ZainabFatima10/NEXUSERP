// src/pages/marketing/VendorRespond.tsx
// Public, no login — reached from the Accept/Reject buttons in the Phase 2
// vendor order email. Requires an explicit click before the mutating
// request fires (protects against an email/security scanner silently
// pre-fetching the link and auto-accepting/rejecting on the vendor's behalf).
import { useState, useEffect } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { CheckCircle2, XCircle, Loader2, AlertCircle, PackageCheck } from "lucide-react";
import Navbar from "@/components/marketing/Navbar";
import Footer from "@/components/marketing/Footer";
import { getPublicVendorOrder, respondVendorOrder, PublicVendorOrderSummary } from "@/services/api";

const cardCls = "bg-navy-900/60 border border-white/10 rounded-2xl p-6 sm:p-8";

const VendorRespond = () => {
  const [params] = useSearchParams();
  const orderId = params.get("order_id") || "";
  const token = params.get("token") || "";
  const urlDecision = (params.get("decision") === "reject" ? "reject" : "accept") as "accept" | "reject";

  const [order, setOrder] = useState<PublicVendorOrderSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [decision, setDecision] = useState<"accept" | "reject">(urlDecision);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    if (!orderId || !token) {
      setError("This link is missing required information.");
      setLoading(false);
      return;
    }
    getPublicVendorOrder(orderId, token)
      .then(setOrder)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "This link is invalid or has expired."))
      .finally(() => setLoading(false));
  }, [orderId, token]);

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await respondVendorOrder(orderId, token, decision, decision === "reject" ? reason : undefined);
      setResult(res.message);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not record your response.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="marketing min-h-screen">
      <Navbar />
      <div className="max-w-xl mx-auto px-5 pt-32 pb-28">
        {loading ? (
          <div className="flex justify-center py-20"><Loader2 className="animate-spin text-accent-cyan" size={36} /></div>
        ) : result ? (
          <div className={`${cardCls} text-center`}>
            <PackageCheck className="mx-auto mb-4 text-accent-cyan" size={36} />
            <h1 className="text-xl font-heading font-bold text-white mb-2">Response Recorded</h1>
            <p className="text-white/60">{result}</p>
            <Link to="/" className="inline-block mt-6 px-5 py-2.5 rounded-lg bg-primary text-white text-sm font-medium hover:opacity-90">
              Back to Home
            </Link>
          </div>
        ) : error && !order ? (
          <div className={`${cardCls} text-center`}>
            <AlertCircle className="mx-auto mb-4 text-destructive" size={36} />
            <h1 className="text-xl font-heading font-bold text-white mb-2">Link Unavailable</h1>
            <p className="text-white/60">{error}</p>
          </div>
        ) : order ? (
          <div className={cardCls}>
            <h1 className="text-2xl font-heading font-bold text-white mb-1">Order {order.order_code}</h1>
            <p className="text-white/50 text-sm mb-6">from {order.vendor_name}</p>

            {order.already_responded ? (
              <p className="text-white/70">This order already recorded a response ({order.status}).</p>
            ) : (
              <>
                <div className="grid sm:grid-cols-2 gap-4 text-sm mb-5">
                  <div>
                    <p className="text-white/40 text-xs uppercase mb-1">Destination</p>
                    <p className="text-white">{order.destination_name}{order.destination_city ? `, ${order.destination_city}` : ""}</p>
                  </div>
                  <div>
                    <p className="text-white/40 text-xs uppercase mb-1">Requested Delivery</p>
                    <p className="text-white">{order.requested_delivery_date || "Not specified"}</p>
                  </div>
                </div>

                <table className="w-full text-sm mb-5">
                  <thead>
                    <tr className="text-left text-xs text-white/40 uppercase border-b border-white/10">
                      <th className="py-2">Item</th><th className="py-2 text-center">Qty</th>
                      <th className="py-2 text-right">Price</th><th className="py-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {order.items.map((it, i) => (
                      <tr key={i} className="border-b border-white/5 text-white/80">
                        <td className="py-2">{it.name}</td>
                        <td className="py-2 text-center">{it.quantity} {it.unit}</td>
                        <td className="py-2 text-right">{it.unit_price.toLocaleString()}</td>
                        <td className="py-2 text-right">{it.line_total.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="text-right mb-6 space-y-1">
                  <p className="text-white font-semibold">
                    You will be paid: PKR {(order.vendor_payout_amount ?? order.subtotal).toLocaleString("en-PK", { minimumFractionDigits: 2 })}
                  </p>
                  <p className="text-xs text-white/50">
                    Funds are held in escrow when you accept and transferred to your registered IBAN after the buyer confirms delivery.
                  </p>
                </div>

                <div className="flex gap-2 mb-5">
                  <button
                    onClick={() => setDecision("accept")}
                    className={`flex-1 py-2.5 rounded-lg text-sm font-medium flex items-center justify-center gap-1.5 transition-colors ${
                      decision === "accept" ? "bg-success text-white" : "bg-white/5 text-white/60 border border-white/15"
                    }`}
                  >
                    <CheckCircle2 size={15} /> Accept
                  </button>
                  <button
                    onClick={() => setDecision("reject")}
                    className={`flex-1 py-2.5 rounded-lg text-sm font-medium flex items-center justify-center gap-1.5 transition-colors ${
                      decision === "reject" ? "bg-destructive text-white" : "bg-white/5 text-white/60 border border-white/15"
                    }`}
                  >
                    <XCircle size={15} /> Reject
                  </button>
                </div>

                {decision === "reject" && (
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Reason (optional, but helpful)"
                    rows={3}
                    className="w-full mb-5 px-4 py-2.5 rounded-lg bg-white/5 border border-white/15 text-white placeholder:text-white/30 text-sm focus:outline-none focus:ring-2 focus:ring-accent-cyan/50"
                  />
                )}

                {error && <p className="text-destructive text-sm mb-4">{error}</p>}

                <button
                  onClick={handleSubmit}
                  disabled={submitting}
                  className={`w-full py-3 rounded-lg font-semibold text-white disabled:opacity-50 flex items-center justify-center gap-2 ${
                    decision === "accept" ? "bg-success" : "bg-destructive"
                  }`}
                >
                  {submitting && <Loader2 size={16} className="animate-spin" />}
                  Confirm {decision === "accept" ? "Accept" : "Reject"}
                </button>
              </>
            )}
          </div>
        ) : null}
      </div>
      <Footer />
    </div>
  );
};

export default VendorRespond;
