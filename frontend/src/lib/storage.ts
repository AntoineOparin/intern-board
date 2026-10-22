// localStorage holds JSON values under the keys the old frontend used: filters, view, baseline,
// lastActive, toolListing (lastVisit is legacy). Keep them compatible so settings carry over.
export function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : (JSON.parse(v) as T);
  } catch {
    return fallback;
  }
}

export function store(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode or full */ }
}

export function remove(key: string) {
  try { localStorage.removeItem(key); } catch { /* ignore */ }
}
