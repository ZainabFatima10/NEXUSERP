// src/pages/NotFound.tsx
import { Link } from "react-router-dom";
import { Zap } from "lucide-react";

const NotFound = () => (
  <div className="min-h-screen flex flex-col items-center justify-center bg-background px-4 text-center">
    <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center mb-6">
      <Zap size={22} className="text-white" fill="white" />
    </div>
    <h1 className="text-5xl font-heading font-bold">404</h1>
    <p className="text-muted-foreground mt-2 mb-6">This page doesn't exist, or the grid signal was lost.</p>
    <Link to="/" className="px-5 py-2.5 btn-navy text-sm font-medium">
      Back to home
    </Link>
  </div>
);

export default NotFound;
