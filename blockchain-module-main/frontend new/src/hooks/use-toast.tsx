// src/hooks/use-toast.tsx
import React, { createContext, useCallback, useContext, useRef, useState } from "react";

export interface ToastOptions {
  title: string;
  description?: string;
  variant?: "default" | "destructive" | "success";
}

interface ToastItem extends ToastOptions {
  id: number;
}

interface ToastContextValue {
  toast: (opts: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue>({
  toast: () => {},
});

export const ToastProvider = ({ children }: { children: React.ReactNode }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (opts: ToastOptions) => {
      const id = ++idRef.current;
      setToasts((prev) => [...prev, { ...opts, id }]);
      window.setTimeout(() => dismiss(id), 5000);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-full max-w-sm pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            onClick={() => dismiss(t.id)}
            className={`pointer-events-auto glass-card p-4 pr-8 relative animate-slide-up cursor-pointer border-l-4 ${
              t.variant === "destructive"
                ? "border-l-destructive"
                : t.variant === "success"
                ? "border-l-success"
                : "border-l-primary"
            }`}
          >
            <p className="text-sm font-semibold text-foreground">{t.title}</p>
            {t.description && (
              <p className="text-xs text-muted-foreground mt-0.5">{t.description}</p>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                dismiss(t.id);
              }}
              className="absolute top-2 right-2 text-muted-foreground hover:text-foreground text-xs"
              aria-label="Dismiss notification"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => useContext(ToastContext);
