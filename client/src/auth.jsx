import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import api from './api.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [signupOpen, setSignupOpen] = useState(true);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api.me();
      setUser(data.user);
      setSignupOpen(Boolean(data.signup_open));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const value = useMemo(() => ({
    user,
    signupOpen,
    loading,
    login: async (email, password) => { const d = await api.login(email, password); setUser(d.user); return d.user; },
    register: async (email, name, password) => { const d = await api.register(email, name, password); setUser(d.user); return d.user; },
    logout: async () => { await api.logout(); setUser(null); },
  }), [user, signupOpen, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
};
