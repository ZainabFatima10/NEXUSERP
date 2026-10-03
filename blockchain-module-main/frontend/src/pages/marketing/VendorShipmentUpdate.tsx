// src/pages/marketing/VendorShipmentUpdate.tsx
// Public, no login, multi-use link (valid 30 days) — lets the vendor mark
// Dispatched (carrier/tracking/ETA) and post In Transit / Out for Delivery
// checkpoints. Cannot mark Arrived or approve anything — those are
// orderer-only (see Order Tracking's detail page).
import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { Loader2, AlertCircle, Truck, MapPin, CheckCircle2 } from "lucide-react";
import Navbar from "@/components/marketing/Navbar";
import Footer from "@/components/marketing/Footer";
import { getPublicShipment, submitVendorShipmentUpdate, PublicShipment } from "@/services/api";

const cardCls = "bg-navy-900/60 border border-white/10 rounded-2xl p-6 sm:p-8";
const inputCls =
  "w-full px-4 py-2.5 rounded-lg bg-white/5 border border-white/15 text-white placeholder:text-white/30 text-sm focus:outline-none focus:ring-2 focus:ring-accent-cyan/50";
const labelCls = "block text-sm font-medium text-white/70 mb-1.5";

const STATUS_LABELS: Record<string, string> = {
  Preparing: "Preparing", Dispatched: "Dispatched", InTransit: "In Transit",
  OutForDelivery: "Out for Delivery", Arrived: "Arrived (confirmed by orderer)",
  Approved: "Approved", Executed: "Completed", Disputed: "Disputed", Cancelled: "Cancelled",
};

const VendorShipmentUpdate = () => {
  const [params] = useSearchParams();
  const orderId = params.get("order_id") || "";
  const token = params.get("token") || "";

  const [orderCode, setOrderCode] = useState("");
  const [vendorName, setVendorName] = useState("");
  const [contractStatus, setContractStatus] = useState("");
  const [shipment, setShipment] = useState<PublicShipment | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const [carrier, setCarrier] = useState("");
  const [trackingNo, setTrackingNo] = useState("");
  const [eta, setEta] = useState("");
  const [checkpointStatus, setCheckpointStatus] = useState<"InTransit" | "OutForDelivery">("InTransit");
  const [location, setLocation] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(() => {
    if (!orderId || !token) {
      setError("This link is missing required information.");
      setLoading(false);
      return;
    }
    setLoading(true);
    getPublicShipment(orderId, token)
      .then((res) => {
        setOrderCode(res.order_code);
        setVendorName(res.vendor_name);
        setContractStatus(res.contract_status);
        setShipment(res.shipment);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "This link is invalid or has expired."))
      .finally(() => setLoading(false));
  }, [orderId, token]);

  useEffect(() => { load(); }, [load]);

  const handleDispatch = async () => {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const res = await submitVendorShipmentUpdate({
        order_id: orderId, token, action: "dispatch",
        carrier, tracking_no: trackingNo, eta: eta || undefined,
      });
      setMessage(res.message);
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not record the update.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCheckpoint = async () => {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const res = await submitVendorShipmentUpdate({
        order_id: orderId, token, action: "checkpoint",
        status: checkpointStatus, location: location || undefined, note: note || undefined,
      });
      setMessage(res.message);
      setLocation("");
      setNote("");
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not record the update.");
    } finally {
      setSubmitting(false);
    }
  };

  const canDispatch = contractStatus === "Preparing";
  const canCheckpoint = contractStatus === "Dispatched" || contractStatus === "InTransit" || contractStatus === "OutForDelivery";
  const isDone = !canDispatch && !canCheckpoint;

  return (
    <div className="marketing min-h-screen">
      <Navbar />
      <div className="max-w-xl mx-auto px-5 pt-32 pb-28">
        {loading ? (
          <div className="flex justify-center py-20"><Loader2 className="animate-spin text-accent-cyan" size={36} /></div>
        ) : error && !orderCode ? (
          <div className={`${cardCls} text-center`}>
            <AlertCircle className="mx-auto mb-4 text-destructive" size={36} />
            <h1 className="text-xl font-heading font-bold text-white mb-2">Link Unavailable</h1>
            <p className="text-white/60">{error}</p>
          </div>
        ) : (
          <div className={cardCls}>
            <h1 className="text-2xl font-heading font-bold text-white mb-1">Order {orderCode}</h1>
            <p className="text-white/50 text-sm mb-6">{vendorName} — shipment status</p>

            <div className="flex items-center gap-2 bg-white/5 border border-white/10 rounded-lg px-4 py-3 mb-6">
              <Truck size={16} className="text-accent-cyan" />
              <span className="text-white text-sm">Current status: <b>{STATUS_LABELS[contractStatus] || contractStatus}</b></span>
            </div>

            {shipment?.carrier && (
              <div className="text-sm text-white/60 mb-6">
                Carrier: {shipment.carrier} · Tracking: {shipment.tracking_no || "—"} · ETA: {shipment.eta || "—"}
              </div>
            )}

            {message && (
              <div className="flex items-center gap-2 bg-success/10 border border-success/30 rounded-lg px-4 py-3 mb-5 text-success text-sm">
                <CheckCircle2 size={15} /> {message}
              </div>
            )}
            {error && (
              <div className="flex items-center gap-2 bg-destructive/10 border border-destructive/30 rounded-lg px-4 py-3 mb-5 text-destructive text-sm">
                <AlertCircle size={15} /> {error}
              </div>
            )}

            {isDone && (
              <p className="text-white/60 text-sm">
                No further shipment updates are needed — this order is at <b>{STATUS_LABELS[contractStatus] || contractStatus}</b>.
                Arrival and approval are confirmed by the orderer, not here.
              </p>
            )}

            {canDispatch && (
              <div className="space-y-4">
                <h2 className="text-white font-semibold text-sm uppercase tracking-wide">Mark as Dispatched</h2>
                <div>
                  <label className={labelCls}>Carrier</label>
                  <input className={inputCls} value={carrier} onChange={(e) => setCarrier(e.target.value)} placeholder="e.g. TCS, Leopards" />
                </div>
                <div>
                  <label className={labelCls}>Tracking / Waybill Number</label>
                  <input className={inputCls} value={trackingNo} onChange={(e) => setTrackingNo(e.target.value)} />
                </div>
                <div>
                  <label className={labelCls}>Estimated Arrival (ETA)</label>
                  <input type="date" className={inputCls} value={eta} onChange={(e) => setEta(e.target.value)} />
                </div>
                <button
                  onClick={handleDispatch}
                  disabled={submitting}
                  className="w-full py-3 rounded-lg font-semibold text-white bg-primary disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {submitting && <Loader2 size={16} className="animate-spin" />}
                  Confirm Dispatched
                </button>
              </div>
            )}

            {canCheckpoint && (
              <div className="space-y-4 mt-2">
                <h2 className="text-white font-semibold text-sm uppercase tracking-wide">Post an Update</h2>
                <div className="flex gap-2">
                  <button
                    onClick={() => setCheckpointStatus("InTransit")}
                    className={`flex-1 py-2 rounded-lg text-sm ${checkpointStatus === "InTransit" ? "bg-accent-cyan/20 text-accent-cyan border border-accent-cyan/50" : "bg-white/5 text-white/60 border border-white/15"}`}
                  >
                    In Transit
                  </button>
                  <button
                    onClick={() => setCheckpointStatus("OutForDelivery")}
                    className={`flex-1 py-2 rounded-lg text-sm ${checkpointStatus === "OutForDelivery" ? "bg-accent-cyan/20 text-accent-cyan border border-accent-cyan/50" : "bg-white/5 text-white/60 border border-white/15"}`}
                  >
                    Out for Delivery
                  </button>
                </div>
                <div>
                  <label className={labelCls}><MapPin size={12} className="inline mr-1" />Location</label>
                  <input className={inputCls} value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Lahore Hub" />
                </div>
                <div>
                  <label className={labelCls}>Note (optional)</label>
                  <input className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} />
                </div>
                <button
                  onClick={handleCheckpoint}
                  disabled={submitting}
                  className="w-full py-3 rounded-lg font-semibold text-white bg-primary disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {submitting && <Loader2 size={16} className="animate-spin" />}
                  Post Update
                </button>
              </div>
            )}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
};

export default VendorShipmentUpdate;
