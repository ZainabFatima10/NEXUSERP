// src/pages/marketing/Landing.tsx
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Package, CloudLightning, MessageSquare, Bell, ArrowRight, ShieldCheck,
  FileCheck2, Truck, Mail, PenLine, CheckCircle2, Zap, Target, TrendingUp,
} from "lucide-react";
import Navbar from "@/components/marketing/Navbar";
import Footer from "@/components/marketing/Footer";

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] } },
};

const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};

const PROBLEM_STATS = [
  { value: "PKR 100Bn+", label: "annual payment delays reported by NEPRA" },
  { value: "25%", label: "of procurement events fail on first attempt" },
  { value: "18–20%", label: "transmission & distribution losses" },
  { value: "8–12 hrs", label: "typical complaint response backlog" },
];

const MODULES = [
  {
    icon: Package,
    title: "Inventory Management",
    desc: "Real-time stock monitoring with automated low-stock detection, VEMA-triggered reorders at the 20% threshold, and blockchain-logged procurement.",
  },
  {
    icon: CloudLightning,
    title: "Outage Prediction",
    desc: "AI-generated 7-day weather-driven forecasts — per-day probability, risk level, affected zones, and recommended pre-emptive actions.",
  },
  {
    icon: MessageSquare,
    title: "User Complaints (VEMA)",
    desc: "24/7 voice-based complaint intake via Whisper + Rasa, auto-ticketed and routed to Admins, with SLA-based escalation.",
  },
  {
    icon: Bell,
    title: "Notifications",
    desc: "One consolidated feed across confirmations, resource allocation, outage updates, and complaints — nothing falls through the cracks.",
  },
];

const LIFECYCLE_STEPS = [
  { icon: ShieldCheck, label: "Verified", desc: "Smart contract checks budget, quantity & authorization rules" },
  { icon: Mail, label: "Vendor Notified", desc: "SendGrid dispatches the purchase order automatically" },
  { icon: PenLine, label: "Contract Signed", desc: "Order is signed and logged to Hyperledger Fabric" },
  { icon: Truck, label: "Shipped & Delivered", desc: "Delivery check-ins recorded against the order" },
  { icon: FileCheck2, label: "Immutable Record", desc: "Execution hash stored for audit & compliance" },
];

const MODEL_STATS = [
  { value: "89.8%", label: "Outage prediction accuracy", sub: "XGBoost Classifier", icon: Target },
  { value: "94.9%", label: "Demand forecasting R²", sub: "XGBoost Regressor", icon: TrendingUp },
  { value: "0.8865", label: "Outage model ROC-AUC", sub: "vs. 85% FYP target", icon: CheckCircle2 },
];

const STACK = [
  "React", "TypeScript", "Tailwind CSS", "FastAPI", "Python 3.11", "XGBoost",
  "PostgreSQL", "TimescaleDB", "Hyperledger Fabric", "Whisper", "Rasa", "SendGrid",
  "OpenWeather API", "PMD API",
];

const Landing = () => {
  return (
    <div id="top" className="marketing">
      <Navbar />

      {/* ── HERO ─────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden pt-40 pb-28 px-5 sm:px-8">
        <div className="absolute inset-0 grid-bg" />
        <div className="absolute inset-0 hero-glow" />
        <div className="absolute inset-0 noise-overlay pointer-events-none" />

        <div className="max-w-5xl mx-auto relative text-center">
          <motion.div
            initial="hidden"
            animate="show"
            variants={stagger}
            className="flex flex-col items-center"
          >
            <motion.span
              variants={fadeUp}
              className="inline-flex items-center gap-2 text-xs font-medium text-white/70 border border-white/15 rounded-full px-3 py-1.5 mb-6 bg-white/5"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan node-dot" />
              FAST-NUCES FYP · AI + Blockchain for Pakistan's Grid
            </motion.span>

            <motion.h1
              variants={fadeUp}
              className="text-4xl sm:text-6xl font-heading font-bold leading-[1.08] tracking-tight text-white"
            >
              One control tower for
              <br />
              <span className="gradient-text">Pakistan's power grid</span>
            </motion.h1>

            <motion.p variants={fadeUp} className="text-white/60 text-base sm:text-lg mt-6 max-w-2xl mx-auto leading-relaxed">
              NEXUS ERP unifies AI outage forecasting, blockchain-verified procurement, and voice-automated
              complaint resolution into a single portal built for Pakistan's electricity distribution companies.
            </motion.p>

            <motion.div variants={fadeUp} className="flex flex-col sm:flex-row items-center gap-3 mt-9">
              <Link
                to="/login"
                className="w-full sm:w-auto px-6 py-3 rounded-lg bg-primary text-white text-sm font-semibold hover:opacity-90 transition-opacity flex items-center justify-center gap-2"
              >
                Admin Login <ArrowRight size={15} />
              </Link>
              <a
                href="#how-it-works"
                className="w-full sm:w-auto px-6 py-3 rounded-lg border border-white/15 text-white text-sm font-medium hover:bg-white/5 transition-colors text-center"
              >
                See how it works
              </a>
            </motion.div>
          </motion.div>

          {/* Live-looking forecast strip — a preview of the actual product screen */}
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="mt-16 marketing-card p-4 sm:p-6 max-w-3xl mx-auto text-left"
          >
            <div className="flex items-center justify-between mb-4">
              <p className="text-xs font-mono text-white/50">7-DAY OUTAGE FORECAST</p>
              <span className="flex items-center gap-1.5 text-[11px] text-accent-cyan">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-cyan node-dot" /> Live model output
              </span>
            </div>
            <div className="grid grid-cols-4 sm:grid-cols-7 gap-2">
              {[
                { d: "Mon", p: 12, r: "low" }, { d: "Tue", p: 35, r: "med" }, { d: "Wed", p: 78, r: "high" },
                { d: "Thu", p: 45, r: "med" }, { d: "Fri", p: 8, r: "low" }, { d: "Sat", p: 15, r: "low" },
                { d: "Sun", p: 62, r: "high" },
              ].map((f) => (
                <div key={f.d} className="bg-white/5 rounded-lg p-2.5 text-center border border-white/5">
                  <p className="text-[10px] text-white/40 mb-1">{f.d}</p>
                  <p className="text-lg font-heading font-bold text-white">{f.p}%</p>
                  <div className="h-1 rounded-full bg-white/10 mt-1.5 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        f.r === "high" ? "bg-red-400" : f.r === "med" ? "bg-amber-400" : "bg-emerald-400"
                      }`}
                      style={{ width: `${f.p}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── PROBLEM STATS ────────────────────────────────────────────── */}
      <section className="px-5 sm:px-8 py-16 border-y border-white/10 bg-white/[0.02]">
        <div className="max-w-6xl mx-auto">
          <motion.p
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: "-80px" }}
            variants={fadeUp}
            className="text-center text-sm text-white/50 mb-10 max-w-xl mx-auto"
          >
            The cost of running Pakistan's grid on spreadsheets and phone calls — figures reported by NEPRA.
          </motion.p>
          <motion.div
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: "-80px" }}
            variants={stagger}
            className="grid grid-cols-2 lg:grid-cols-4 gap-6"
          >
            {PROBLEM_STATS.map((s) => (
              <motion.div key={s.label} variants={fadeUp} className="text-center">
                <p className="text-3xl sm:text-4xl font-heading font-bold text-white">{s.value}</p>
                <p className="text-xs sm:text-sm text-white/50 mt-2 leading-snug">{s.label}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ── MODULES ──────────────────────────────────────────────────── */}
      <section id="modules" className="px-5 sm:px-8 py-24">
        <div className="max-w-6xl mx-auto">
          <motion.div initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} variants={fadeUp}>
            <p className="text-xs font-semibold text-accent-cyan uppercase tracking-wider mb-3">Modules</p>
            <h2 className="text-3xl sm:text-4xl font-heading font-bold text-white max-w-xl">
              Four systems. One portal.
            </h2>
            <p className="text-white/50 mt-3 max-w-xl">
              Everything an Admin, Procurement Officer, or System Operator needs, without switching between five
              disconnected tools.
            </p>
          </motion.div>

          <motion.div
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: "-80px" }}
            variants={stagger}
            className="grid grid-cols-1 sm:grid-cols-2 gap-5 mt-12"
          >
            {MODULES.map((m) => (
              <motion.div key={m.title} variants={fadeUp} className="marketing-card p-6">
                <div className="w-10 h-10 rounded-lg bg-primary/15 text-accent-cyan flex items-center justify-center mb-4">
                  <m.icon size={20} />
                </div>
                <h3 className="font-heading font-semibold text-white text-lg">{m.title}</h3>
                <p className="text-sm text-white/50 mt-2 leading-relaxed">{m.desc}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ── HOW IT WORKS: procurement lifecycle (real, ordered sequence) ── */}
      <section id="how-it-works" className="px-5 sm:px-8 py-24 border-t border-white/10 bg-white/[0.02]">
        <div className="max-w-6xl mx-auto">
          <motion.div initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} variants={fadeUp}>
            <p className="text-xs font-semibold text-accent-cyan uppercase tracking-wider mb-3">How it works</p>
            <h2 className="text-3xl sm:text-4xl font-heading font-bold text-white max-w-xl">
              Every order leaves a receipt no one can rewrite.
            </h2>
            <p className="text-white/50 mt-3 max-w-xl">
              When stock drops below threshold, NEXUS generates and verifies the order automatically — no manual
              paperwork, and every step is logged to Hyperledger Fabric.
            </p>
          </motion.div>

          <motion.div
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: "-80px" }}
            variants={stagger}
            className="relative mt-14"
          >
            <div className="hidden lg:block absolute top-6 left-0 right-0 h-px current-line" />
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-8 lg:gap-4">
              {LIFECYCLE_STEPS.map((s, i) => (
                <motion.div key={s.label} variants={fadeUp} className="relative flex flex-col items-center text-center">
                  <div className="w-12 h-12 rounded-full bg-navy-900 border border-white/15 flex items-center justify-center relative z-10 mb-4">
                    <s.icon size={18} className="text-accent-cyan" />
                  </div>
                  <p className="text-xs font-mono text-white/30 mb-1">STEP {i + 1}</p>
                  <p className="font-heading font-semibold text-white text-sm">{s.label}</p>
                  <p className="text-xs text-white/50 mt-1.5 max-w-[180px]">{s.desc}</p>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── MODEL PERFORMANCE ────────────────────────────────────────── */}
      <section id="performance" className="px-5 sm:px-8 py-24">
        <div className="max-w-6xl mx-auto">
          <motion.div initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} variants={fadeUp}>
            <p className="text-xs font-semibold text-accent-cyan uppercase tracking-wider mb-3">Model performance</p>
            <h2 className="text-3xl sm:text-4xl font-heading font-bold text-white max-w-xl">
              Forecasts that clear the bar.
            </h2>
            <p className="text-white/50 mt-3 max-w-xl">
              Both models were trained against an 85% accuracy target set for this FYP — and both exceed it.
            </p>
          </motion.div>

          <motion.div
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: "-80px" }}
            variants={stagger}
            className="grid grid-cols-1 sm:grid-cols-3 gap-5 mt-12"
          >
            {MODEL_STATS.map((s) => (
              <motion.div key={s.label} variants={fadeUp} className="marketing-card p-6 flex items-start gap-4">
                <div className="w-10 h-10 rounded-lg bg-accent-cyan/15 text-accent-cyan flex items-center justify-center flex-shrink-0">
                  <s.icon size={18} />
                </div>
                <div>
                  <p className="text-2xl font-heading font-bold text-white">{s.value}</p>
                  <p className="text-sm text-white/70 mt-1">{s.label}</p>
                  <p className="text-xs text-white/40 mt-0.5">{s.sub}</p>
                </div>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ── TECH STACK MARQUEE ───────────────────────────────────────── */}
      <section id="stack" className="py-14 border-y border-white/10 bg-white/[0.02] overflow-hidden">
        <p className="text-center text-xs font-semibold text-white/40 uppercase tracking-wider mb-6">Built with</p>
        <div className="flex overflow-hidden select-none">
          <div className="flex gap-10 animate-marquee flex-shrink-0 pr-10">
            {[...STACK, ...STACK].map((t, i) => (
              <span key={`${t}-${i}`} className="text-white/40 font-mono text-sm whitespace-nowrap">
                {t}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── FINAL CTA ────────────────────────────────────────────────── */}
      <section className="px-5 sm:px-8 py-28 relative overflow-hidden">
        <div className="absolute inset-0 hero-glow opacity-70" />
        <motion.div
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-80px" }}
          variants={fadeUp}
          className="max-w-2xl mx-auto text-center relative"
        >
          <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center mx-auto mb-6">
            <Zap size={22} className="text-white" fill="white" />
          </div>
          <h2 className="text-3xl sm:text-4xl font-heading font-bold text-white">
            Ready to see your grid from mission control?
          </h2>
          <p className="text-white/50 mt-4">
            Sign in to the Admin portal to explore live inventory, forecasts, and complaint queues.
          </p>
          <Link
            to="/login"
            className="inline-flex items-center gap-2 mt-8 px-7 py-3 rounded-lg bg-primary text-white text-sm font-semibold hover:opacity-90 transition-opacity"
          >
            Go to Admin Login <ArrowRight size={15} />
          </Link>
        </motion.div>
      </section>

      <Footer />
    </div>
  );
};

export default Landing;
