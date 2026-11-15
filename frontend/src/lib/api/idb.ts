// Minimal promise wrapper over IndexedDB for the browser sandbox driver.
const DB_NAME = "growthcognix-sandbox";
const STORES = ["tenants", "users", "clients", "products", "documents", "blobs", "jobs", "activity", "sessions"] as const;
export type Store = (typeof STORES)[number];

let dbp: Promise<IDBDatabase> | null = null;
function open(): Promise<IDBDatabase> {
  if (dbp) return dbp;
  dbp = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => STORES.forEach((s) => { if (!req.result.objectStoreNames.contains(s)) req.result.createObjectStore(s, { keyPath: "id" }); });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbp;
}

function tx<T>(store: Store, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest): Promise<T> {
  return open().then((db) => new Promise<T>((resolve, reject) => {
    const r = fn(db.transaction(store, mode).objectStore(store));
    r.onsuccess = () => resolve(r.result as T);
    r.onerror = () => reject(r.error);
  }));
}

export const idb = {
  all: <T>(s: Store) => tx<T[]>(s, "readonly", (o) => o.getAll()),
  get: <T>(s: Store, id: string) => tx<T | undefined>(s, "readonly", (o) => o.get(id)),
  put: <T extends { id: string }>(s: Store, v: T) => tx<string>(s, "readwrite", (o) => o.put(v)).then(() => v),
  del: (s: Store, id: string) => tx<undefined>(s, "readwrite", (o) => o.delete(id)),
};
