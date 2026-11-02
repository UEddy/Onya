import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "onya-watchlist";
const CHANGE_EVENT = "onya-watch-change";

/* Per-browser watch list in localStorage. Never touches the network:
   the backend stays anonymous, and every browser keeps its own list.
   Storage failures (private mode, quota) fall back to memory. */

function readStored(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (entry): entry is string =>
        typeof entry === "string" && entry.length > 0,
    );
  } catch {
    return [];
  }
}

export function loadWatch(): string[] {
  if (typeof window === "undefined") return [];
  return readStored();
}

export function useWatch() {
  const [watched, setWatched] = useState<string[]>(() => loadWatch());

  useEffect(() => {
    const refresh = () => setWatched(readStored());
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) refresh();
    };
    // "storage" fires only across documents; the custom event keeps
    // hooks in the same page in sync.
    window.addEventListener("storage", onStorage);
    window.addEventListener(CHANGE_EVENT, refresh);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(CHANGE_EVENT, refresh);
    };
  }, []);

  const toggle = useCallback((ticker: string) => {
    setWatched((current) => {
      const next = current.includes(ticker)
        ? current.filter((entry) => entry !== ticker)
        : [...current, ticker];
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* Memory-only when storage is unavailable. */
      }
      window.dispatchEvent(new Event(CHANGE_EVENT));
      return next;
    });
  }, []);

  return { watched, toggle };
}
