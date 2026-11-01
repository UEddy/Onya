"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

type Theme = "dark" | "light";

const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({
  theme: "dark",
  toggle: () => {},
});

export function useTheme() {
  return useContext(ThemeContext);
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() =>
    typeof document !== "undefined" &&
    document.documentElement.classList.contains("dark")
      ? "dark"
      : "light",
  );
  // Re-apply the stored choice after mount and whenever the URL
  // changes (route, query or hash), so a stored Light or Dark choice
  // holds on every route even if a prerendered shell remounts this tree.
  useEffect(() => {
    const apply = () => {
      try {
        const stored = localStorage.getItem("onya-theme");
        if (stored === "dark" || stored === "light") {
          document.documentElement.classList.toggle(
            "dark",
            stored === "dark",
          );
          setTheme(stored);
        }
      } catch {
        /* storage unavailable: keep the current theme */
      }
    };
    const timer = window.setTimeout(apply, 0);
    window.addEventListener("popstate", apply);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("popstate", apply);
    };
  });

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === "dark" ? "light" : "dark";
      document.documentElement.classList.toggle("dark", next === "dark");
      try {
        localStorage.setItem("onya-theme", next);
      } catch {
        /* storage unavailable: theme still applies for this visit */
      }
      return next;
    });
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Use ${next} mode`}
      className="text-[13px] text-ink-muted underline decoration-rule underline-offset-4 hover:text-ink"
    >
      {theme === "dark" ? "Light" : "Dark"}
    </button>
  );
}
