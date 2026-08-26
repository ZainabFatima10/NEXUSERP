/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: "hsl(var(--primary))",
        "primary-foreground": "hsl(var(--primary-foreground))",
        secondary: "hsl(var(--secondary))",
        "secondary-foreground": "hsl(var(--secondary-foreground))",
        destructive: "hsl(var(--destructive))",
        "destructive-foreground": "hsl(var(--destructive-foreground))",
        muted: "hsl(var(--muted))",
        "muted-foreground": "hsl(var(--muted-foreground))",
        success: "hsl(var(--success))",
        "success-foreground": "hsl(var(--success-foreground))",
        warning: "hsl(var(--warning))",
        "warning-foreground": "hsl(var(--warning-foreground))",
        border: "hsl(var(--border))",
        "accent-cyan": "hsl(var(--accent-cyan))",
        "accent-green": "hsl(var(--accent-green))",
        "accent-violet": "hsl(var(--accent-violet))",
        "accent-amber": "hsl(var(--accent-amber))",
        sidebar: "hsl(var(--sidebar))",
        "sidebar-foreground": "hsl(var(--sidebar-foreground))",
        "sidebar-muted": "hsl(var(--sidebar-muted))",
        "sidebar-border": "hsl(var(--sidebar-border))",
        navy: {
          950: "#050B18",
          900: "#0A1628",
          800: "#0D1B30",
          700: "#12233D",
          600: "#1A2E4D",
        },
      },
      fontFamily: {
        heading: ["'Chakra Petch'", "sans-serif"],
        sans: ["'Manrope'", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
      boxShadow: {
        "glow-cyan": "0 0 0 1px hsl(var(--accent-cyan) / 0.25), 0 8px 30px -8px hsl(var(--accent-cyan) / 0.35)",
        "glow-primary": "0 0 0 1px hsl(var(--primary) / 0.3), 0 8px 30px -8px hsl(var(--primary) / 0.45)",
        card: "0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06)",
      },
      keyframes: {
        "slide-up": {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "pulse-node": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.5", transform: "scale(1.4)" },
        },
        "flow-x": {
          "0%": { backgroundPosition: "0% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        marquee: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
      },
      animation: {
        "slide-up": "slide-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fade-in 0.5s ease both",
        "pulse-node": "pulse-node 2.4s ease-in-out infinite",
        "flow-x": "flow-x 3s linear infinite",
        marquee: "marquee 28s linear infinite",
      },
    },
  },
  plugins: [],
}
