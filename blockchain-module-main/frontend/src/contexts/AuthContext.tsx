import React, { createContext, useContext } from 'react';

const AuthContext = createContext({ user: { id: "user_1", name: "Admin", email: "admin@nexus.com" }});

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  return (
    <AuthContext.Provider value={{ user: { id: "user_1", name: "Admin", email: "admin@nexus.com" }}}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext);
