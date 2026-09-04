// src/contexts/AuthContext.tsx
import React, { createContext, useContext, useEffect, useState } from "react";
import { loginUser, signupUser, AuthUser } from "@/services/api";

const STORAGE_USER = "nexus_user";
const STORAGE_TOKEN = "nexus_token";

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  initializing: boolean;
  login: (email: string, password: string) => Promise<AuthUser>;
  signup: (name: string, email: string, password: string) => Promise<AuthUser>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  token: null,
  loading: false,
  initializing: true,
  login: async () => { throw new Error("AuthProvider not mounted"); },
  signup: async () => { throw new Error("AuthProvider not mounted"); },
  logout: () => {},
});

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [initializing, setInitializing] = useState(true);

  // Rehydrate session from localStorage on first load
  useEffect(() => {
    try {
      const storedUser = localStorage.getItem(STORAGE_USER);
      const storedToken = localStorage.getItem(STORAGE_TOKEN);
      if (storedUser && storedToken) {
        setUser(JSON.parse(storedUser));
        setToken(storedToken);
      }
    } catch {
      // corrupted storage — ignore and start fresh
    } finally {
      setInitializing(false);
    }
  }, []);

  const login = async (email: string, password: string) => {
    setLoading(true);
    try {
      const res = await loginUser(email, password);
      setUser(res.user);
      setToken(res.token);
      localStorage.setItem(STORAGE_USER, JSON.stringify(res.user));
      localStorage.setItem(STORAGE_TOKEN, res.token);
      return res.user;
    } finally {
      setLoading(false);
    }
  };

  const signup = async (name: string, email: string, password: string) => {
    setLoading(true);
    try {
      await signupUser(name, email, password);
      return await login(email, password);
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    setUser(null);
    setToken(null);
    localStorage.removeItem(STORAGE_USER);
    localStorage.removeItem(STORAGE_TOKEN);
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, initializing, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
