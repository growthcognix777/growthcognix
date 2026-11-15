"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "./api";
import { tokenStore } from "./api/token";
import type { Session } from "./types";

interface AuthState { session: Session | null; loading: boolean; setSession: (s: Session | null) => void; logout: () => Promise<void>; refresh: () => Promise<void>; }
const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    if (!tokenStore.get()) { setSession(null); setLoading(false); return; }
    try { setSession(await api.me()); } catch { tokenStore.clear(); setSession(null); } finally { setLoading(false); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  const logout = useCallback(async () => { try { await api.logout(); } finally { tokenStore.clear(); setSession(null); } }, []);
  return <Ctx.Provider value={{ session, loading, setSession, logout, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth() { const c = useContext(Ctx); if (!c) throw new Error("useAuth outside AuthProvider"); return c; }

/** Redirects to /login when there is no session. */
export function useRequireAuth() {
  const a = useAuth(); const router = useRouter();
  useEffect(() => { if (!a.loading && !a.session) router.replace("/login/"); }, [a.loading, a.session, router]);
  return a;
}
