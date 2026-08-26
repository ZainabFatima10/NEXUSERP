// src/components/Logo.tsx
//
// NEXUS ERP brand mark: a hex "grid node" (the lattice of a distribution
// network) with a current bolt threading through it — same visual
// vocabulary as the marketing site's grid-bg / current-line / node-dot
// motifs, so the mark and the rest of the UI read as one system.

interface LogoMarkProps {
  size?: number;
  className?: string;
}

export const LogoMark = ({ size = 32, className = "" }: LogoMarkProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 40 40"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    role="img"
    aria-label="NEXUS ERP"
  >
    <defs>
      <linearGradient id="nexusMarkGrad" x1="4" y1="4" x2="36" y2="36" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#2F6FED" />
        <stop offset="100%" stopColor="#22D3EE" />
      </linearGradient>
    </defs>
    {/* Hex lattice node */}
    <path
      d="M20 2.5 L35.5 11.25 V28.75 L20 37.5 L4.5 28.75 V11.25 Z"
      stroke="url(#nexusMarkGrad)"
      strokeWidth="2.25"
      fill="none"
    />
    {/* Inner current bolt */}
    <path
      d="M21.6 9.5 L12.8 21.6h6.1l-1.9 9 9.8-13.2h-6.3z"
      fill="url(#nexusMarkGrad)"
    />
    {/* Lattice corner nodes */}
    <circle cx="20" cy="2.5" r="1.6" fill="#22D3EE" />
    <circle cx="20" cy="37.5" r="1.6" fill="#2F6FED" />
  </svg>
);

interface LogoProps {
  size?: number;
  showTagline?: boolean;
  light?: boolean; // true = render for dark backgrounds (sidebar, marketing)
  className?: string;
}

const Logo = ({ size = 32, showTagline = true, light = true, className = "" }: LogoProps) => (
  <div className={`flex items-center gap-2.5 ${className}`}>
    <LogoMark size={size} />
    <div className="min-w-0 leading-tight">
      <p className={`font-heading font-bold tracking-tight truncate ${light ? "text-white" : "text-foreground"}`} style={{ fontSize: size * 0.42 }}>
        NEXUS ERP
      </p>
      {showTagline && (
        <p className={`truncate ${light ? "text-sidebar-muted" : "text-muted-foreground"}`} style={{ fontSize: size * 0.24 }}>
          PowerGrid Optimizer
        </p>
      )}
    </div>
  </div>
);

export default Logo;
