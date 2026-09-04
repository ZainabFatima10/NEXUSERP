// src/pages/NotFound.tsx
import { Link } from "react-router-dom";
import { LogoMark } from "@/components/Logo";

const NotFound = () => (
  <div className="min-h-screen flex flex-col items-center justify-center bg-background px-4 text-center relative overflow-hidden">
    <div className="absolute inset-0 grid-bg opacity-40 pointer-events-none" />
    <div className="relative">
      <div className="mb-6 flex justify-center"><LogoMark size={48} /></div>
      <h1 className="text-5xl font-heading font-bold">404</h1>
      <p className="text-muted-foreground mt-2 mb-6">This page doesn't exist, or the grid signal was lost.</p>
      <Link to="/" className="px-5 py-2.5 btn-navy text-sm font-medium">
        Back to home
      </Link>
    </div>
  </div>
);

export default NotFound;
