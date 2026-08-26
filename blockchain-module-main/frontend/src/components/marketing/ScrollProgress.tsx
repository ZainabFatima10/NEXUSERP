// src/components/marketing/ScrollProgress.tsx
import { motion, useScroll, useSpring } from "framer-motion";

/**
 * Thin gradient progress bar pinned to the very top of the viewport,
 * fills left-to-right as the visitor scrolls through the marketing site.
 */
const ScrollProgress = () => {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, {
    stiffness: 120,
    damping: 24,
    restDelta: 0.001,
  });

  return (
    <motion.div
      className="fixed top-0 left-0 right-0 h-[2.5px] origin-left z-[60]"
      style={{
        scaleX,
        background: "linear-gradient(90deg, #7fd8ff 0%, #6fa8ff 45%, #a48bff 100%)",
      }}
    />
  );
};

export default ScrollProgress;
