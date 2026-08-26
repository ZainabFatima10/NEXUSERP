// src/components/marketing/Footer.tsx
import { LogoMark } from "@/components/Logo";

const Footer = () => (
  <footer className="border-t border-white/10 bg-navy-950">
    <div className="max-w-7xl mx-auto px-5 sm:px-8 py-12">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-10">
        <div className="md:col-span-2">
          <div className="flex items-center gap-2 mb-3">
            <LogoMark size={28} />
            <span className="font-heading font-bold text-white text-sm">NEXUS ERP</span>
          </div>
          <p className="text-sm text-white/50 max-w-sm leading-relaxed">
            A single-portal control tower for Pakistan's electricity distribution companies — AI outage forecasting,
            blockchain-verified procurement, and voice-automated complaint resolution.
          </p>
        </div>

        <div>
          <p className="text-xs font-semibold text-white/70 uppercase tracking-wider mb-3">Modules</p>
          <ul className="space-y-2 text-sm text-white/50">
            <li>Inventory Management</li>
            <li>Outage Prediction</li>
            <li>User Complaints (VEMA)</li>
            <li>Notifications</li>
          </ul>
        </div>

        <div>
          <p className="text-xs font-semibold text-white/70 uppercase tracking-wider mb-3">Project</p>
          <ul className="space-y-2 text-sm text-white/50">
            <li>FAST-NUCES Islamabad</li>
            <li>FYP · Session 2022–2026</li>
            <li>Dept. of Computer Science &amp; AI</li>
          </ul>
        </div>
      </div>

      <div className="mt-10 pt-6 border-t border-white/10 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <p className="text-xs text-white/40">
          Built by Zainab Fatima, Ayesha Tahir &amp; Ayesha Imran — supervised by Mr. Ahmed Raza &amp; Dr. Noshina Tariq.
        </p>
        <p className="text-xs text-white/40">Developed for academic purposes as a Final Year Project.</p>
      </div>
    </div>
  </footer>
);

export default Footer;
