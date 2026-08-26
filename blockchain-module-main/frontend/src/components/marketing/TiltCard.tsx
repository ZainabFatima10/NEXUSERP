// src/components/marketing/TiltCard.tsx
import { useRef } from "react";
import { motion, useMotionValue, useMotionTemplate, useSpring, useTransform } from "framer-motion";

interface Props {
  children: React.ReactNode;
  className?: string;
}

/**
 * Wraps a marketing-card with a subtle pointer-driven 3D tilt and a
 * cursor-following radial glow. Degrades gracefully on touch devices
 * (no pointer move events, so it just sits flat).
 */
const TiltCard = ({ children, className = "" }: Props) => {
  const ref = useRef<HTMLDivElement>(null);
  const mx = useMotionValue(0.5);
  const my = useMotionValue(0.5);

  const rotateX = useSpring(useTransform(my, [0, 1], [6, -6]), { stiffness: 200, damping: 20 });
  const rotateY = useSpring(useTransform(mx, [0, 1], [-6, 6]), { stiffness: 200, damping: 20 });
  const glowX = useTransform(mx, (v) => `${v * 100}%`);
  const glowY = useTransform(my, (v) => `${v * 100}%`);
  const background = useMotionTemplate`radial-gradient(180px circle at ${glowX} ${glowY}, rgba(127,216,255,0.14), transparent 70%)`;

  const handleMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    mx.set((e.clientX - rect.left) / rect.width);
    my.set((e.clientY - rect.top) / rect.height);
  };

  const reset = () => {
    mx.set(0.5);
    my.set(0.5);
  };

  return (
    <motion.div
      ref={ref}
      onPointerMove={handleMove}
      onPointerLeave={reset}
      style={{ rotateX, rotateY, transformPerspective: 800 }}
      className={`marketing-card relative overflow-hidden group ${className}`}
    >
      <motion.div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300"
        style={{ background }}
      />
      <div className="relative">{children}</div>
    </motion.div>
  );
};

export default TiltCard;
