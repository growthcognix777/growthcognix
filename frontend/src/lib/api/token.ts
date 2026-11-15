// Local prototype: the access token lives in sessionStorage (cleared when the tab closes).
// Production plan (pre-VPS hardening): httpOnly Secure SameSite cookies + short-lived access tokens + rotating refresh tokens.
const KEY = "gc.session";
export const tokenStore = {
  get(): string | null { if (typeof window === "undefined") return null; return sessionStorage.getItem(KEY); },
  set(t: string) { sessionStorage.setItem(KEY, t); },
  clear() { sessionStorage.removeItem(KEY); },
};
