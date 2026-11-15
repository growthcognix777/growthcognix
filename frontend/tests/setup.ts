import "fake-indexeddb/auto";
const mem = new Map<string, string>();
(globalThis as unknown as { sessionStorage: Storage }).sessionStorage = {
  getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v), removeItem: (k: string) => void mem.delete(k),
  clear: () => mem.clear(), key: () => null, length: 0,
} as Storage;
(globalThis as unknown as { window: unknown }).window = globalThis;
