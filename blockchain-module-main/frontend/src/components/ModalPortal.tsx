// src/components/ModalPortal.tsx
// Renders a modal overlay straight into <body>. Pages animate in with
// `animate-slide-up` / framer-motion, which leave a CSS transform on the
// page wrapper — and any transformed ancestor becomes the containing block
// for `position: fixed`, so an in-place `fixed inset-0` overlay gets sized
// to the (tall, scrolled) page instead of the viewport and its top is cut
// off under the topbar. Portalling out of that wrapper keeps every modal
// centred in the visible window.
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

const ModalPortal = ({ children }: { children: ReactNode }) => {
  // Stop the page behind the modal from scrolling while it's open.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  return createPortal(children, document.body);
};

export default ModalPortal;
