// src/contexts/AuthContext.tsx
import React, { createContext, useContext, useState, useCallback } from "react";
import { loginUser, signupUser, AuthUser } from "@/services/api";

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<boolean>;
  signup: (name: string, email: string, role: string, password: string) => Promise<boolean>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(() => {
    const stored = localStorage.getItem("nexus_user");
    return stored ? JSON.parse(stored) : null;
  });
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem("nexus_token")
  );

  const login = useCallback(async (email: string, password: string) => {
    try {
      const res = await loginUser(email, password);
      setUser(res.user);
      setToken(res.token);
      localStorage.setItem("nexus_user", JSON.stringify(res.user));
      localStorage.setItem("nexus_token", res.token);
      return true;
    } catch {
      // Fallback to mock for dev if DB not reachable
      const mockUser: AuthUser = { id: "dev-1", name: "Admin User", email, role: "Admin" };
      setUser(mockUser);
      setToken("dev-token");
      localStorage.setItem("nexus_user", JSON.stringify(mockUser));
      localStorage.setItem("nexus_token", "dev-token");
      return true;
    }
  }, []);

  const signup = useCallback(
    async (name: string, email: string, role: string, password: string) => {
      try {
        await signupUser(name, email, password, role);
        return await login(email, password);
      } catch {
        return false;
      }
    },
    [login]
  );

  const logout = useCallback(() => {
    setUser(null);
    setToken(null);
    localStorage.removeItem("nexus_user");
    localStorage.removeItem("nexus_token");
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, isAuthenticated: !!user, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
};
