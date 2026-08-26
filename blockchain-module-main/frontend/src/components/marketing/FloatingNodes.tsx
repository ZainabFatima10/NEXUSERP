// src/components/marketing/FloatingNodes.tsx
import { motion } from "framer-motion";

const NODES = [
  { top: "18%", left: "8%",  size: 3, delay: 0 },
  { top: "32%", left: "22%", size: 2, delay: 0.4 },
  { top: "12%", left: "42%", size: 2, delay: 0.8 },
  { top: "58%", left: "12%", size: 3, delay: 1.1 },
  { top: "68%", left: "34%", size: 2, delay: 0.2 },
  { top: "22%", left: "78%", size: 3, delay: 0.6 },
  { top: "44%", left: "88%", size: 2, delay: 1.4 },
  { top: "72%", left: "72%", size: 2, delay: 0.9 },
  { top: "10%", left: "62%", size: 2, delay: 1.7 },
  { top: "82%", left: "50%", size: 3, delay: 0.3 },
];

/**
 * A handful of softly pulsing nodes scattered across the hero, evoking a
 * transmission grid coming online. Pure CSS animation — negligible cost.
 */
const FloatingNodes = () => (
  <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden>
    {NODES.map((n, i) => (
      <motion.span
        key={i}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1, delay: n.delay }}
        className="absolute rounded-full bg-accent-cyan node-dot"
        style={{
          top: n.top,
          left: n.left,
          width: n.size,
          height: n.size,
          boxShadow: "0 0 8px 1px rgba(127,216,255,0.6)",
          animationDelay: `${n.delay}s`,
        }}
      />
    ))}
  </div>
);

export default FloatingNodes;
