// src/components/marketing/AnimatedStat.tsx
import { useEffect, useRef } from "react";
import { motion, useInView, useMotionValue, useSpring } from "framer-motion";

interface Props {
  /** Numeric part to count up to, e.g. 89.8 */
  value: number;
  /** Rendered before the number, e.g. "PKR " */
  prefix?: string;
  /** Rendered after the number, e.g. "%" or "Bn+" */
  suffix?: string;
  /** Decimal places to keep (0 for whole numbers) */
  decimals?: number;
  className?: string;
}

/**
 * Counts up from 0 to `value` once it scrolls into view. Falls back to a
 * static render if reduced-motion is preferred (handled globally via the
 * prefers-reduced-motion media query already in index.css).
 */
const AnimatedStat = ({ value, prefix = "", suffix = "", decimals = 0, className }: Props) => {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  const motionVal = useMotionValue(0);
  const spring = useSpring(motionVal, { stiffness: 60, damping: 20, restDelta: 0.001 });

  useEffect(() => {
    if (inView) motionVal.set(value);
  }, [inView, value, motionVal]);

  useEffect(() => {
    return spring.on("change", (v) => {
      if (ref.current) {
        ref.current.textContent = `${prefix}${v.toFixed(decimals)}${suffix}`;
      }
    });
  }, [spring, prefix, suffix, decimals]);

  return (
    <motion.span ref={ref} className={className}>
      {prefix}0{suffix}
    </motion.span>
  );
};

export default AnimatedStat;
