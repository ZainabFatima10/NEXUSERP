// src/components/marketing/Navbar.tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Zap, Menu, X } from "lucide-react";

const LINKS = [
  { href: "#modules", label: "Modules" },
  { href: "#how-it-works", label: "How it works" },
  { href: "#performance", label: "Performance" },
  { href: "#stack", label: "Tech stack" },
];

const Navbar = () => {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`fixed top-0 inset-x-0 z-50 transition-colors duration-300 ${
        scrolled ? "bg-navy-950/85 backdrop-blur-md border-b border-white/10" : "bg-transparent"
      }`}
    >
      <div className="max-w-7xl mx-auto px-5 sm:px-8 h-16 flex items-center justify-between">
        <a href="#top" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <Zap size={16} className="text-white" fill="white" />
          </div>
          <span className="font-heading font-bold text-white text-sm sm:text-base">NEXUS ERP</span>
        </a>

        <nav className="hidden md:flex items-center gap-8">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} className="text-sm text-white/70 hover:text-white transition-colors">
              {l.label}
            </a>
          ))}
        </nav>

        <div className="hidden md:flex items-center gap-3">
          <Link to="/login" className="text-sm text-white/80 hover:text-white transition-colors px-3 py-2">
            Admin Login
          </Link>
          <Link
            to="/signup"
            className="text-sm font-medium px-4 py-2 rounded-lg bg-primary text-white hover:opacity-90 transition-opacity"
          >
            Request Access
          </Link>
        </div>

        <button
          className="md:hidden text-white p-2 -mr-2"
          onClick={() => setOpen((o) => !o)}
          aria-label="Toggle menu"
        >
          {open ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>

      {open && (
        <div className="md:hidden bg-navy-950/95 backdrop-blur-md border-b border-white/10 px-5 py-4 space-y-3">
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              onClick={() => setOpen(false)}
              className="block text-sm text-white/80 hover:text-white py-1"
            >
              {l.label}
            </a>
          ))}
          <div className="flex gap-3 pt-2">
            <Link to="/login" className="flex-1 text-center text-sm text-white/90 border border-white/20 rounded-lg py-2">
              Admin Login
            </Link>
            <Link to="/signup" className="flex-1 text-center text-sm bg-primary text-white rounded-lg py-2">
              Request Access
            </Link>
          </div>
        </div>
      )}
    </header>
  );
};

export default Navbar;
