"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { BrandLockup } from "./marketing";
import { ThemeToggle } from "./theme";
import { apiGet, type CompanyRow } from "../lib/api";

const APP_NAV = [
  { href: "/app/watchlist", label: "Watchlist", match: "/app/watchlist" },
  { href: "/app/company/SNBR", label: "Sleep Number", match: "/app/company" },
  { href: "/app/agent", label: "Agent", match: "/app/agent" },
  { href: "/app/accuracy", label: "Accuracy", match: "/app/accuracy" },
];

function pageTitle(pathname: string): string {
  if (pathname.startsWith("/app/company")) return "Sleep Number";
  if (pathname.startsWith("/app/agent")) return "Agent";
  if (pathname.startsWith("/app/accuracy")) return "Accuracy";
  return "Watchlist";
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/app/watchlist";
  const [companies, setCompanies] = useState<CompanyRow[] | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    let cancelled = false;
    apiGet<{ companies: CompanyRow[] }>("/companies").then(
      (data) => {
        if (!cancelled) setCompanies(data.companies);
      },
      () => undefined,
    );
    return () => {
      cancelled = true;
    };
  }, []);
  const breaches =
    companies?.filter((c) => c.status === "fail").length ?? null;
  const title = pageTitle(pathname);
  const isCase = pathname.startsWith("/app/company");
  const isAgent = pathname.startsWith("/app/agent");

  const nav = (onNavigate?: () => void) => (
    <nav aria-label="App" className="flex flex-col gap-1">
      {APP_NAV.map((item) => {
        const active = pathname.startsWith(item.match);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={`flex items-baseline justify-between px-3 py-2 text-[15px] ${
              active
                ? "bg-[color-mix(in_srgb,var(--ink)_8%,transparent)] font-semibold"
                : "text-ink-muted hover:text-ink"
            }`}
          >
            <span>{item.label}</span>
            {item.label === "Watchlist" && companies && (
              <span className="flex items-baseline gap-3">
                <span className="index-label text-[13px] text-ink-muted">
                  {companies.length}
                </span>
                {breaches !== null && (
                  <span
                    className="flex items-center gap-1.5"
                    title={`${breaches} in breach`}
                  >
                    <span
                      aria-hidden="true"
                      className="inline-block h-2 w-2 bg-breach"
                    />
                    <span className="index-label text-[13px] text-ink-muted">
                      {breaches}
                    </span>
                    <span className="sr-only">in breach</span>
                  </span>
                )}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className="flex min-h-full flex-1 flex-col min-[900px]:flex-row">
      <aside className="hidden w-[232px] shrink-0 flex-col border-r border-rule bg-surface px-4 py-5 min-[900px]:flex">
        <BrandLockup />
        <p className="mt-6 text-[13px] font-medium text-ink-muted">
          Demo portfolio
        </p>
        <p className="text-[13px] text-ink-muted">Public SEC data</p>
        <div className="mt-4 flex-1">{nav()}</div>
        <div className="border-t border-rule pt-4">
          <ThemeToggle />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-4 border-b border-rule px-4 py-3 min-[900px]:hidden">
          <BrandLockup />
          <button
            type="button"
            aria-expanded={menuOpen}
            aria-label="Menu"
            onClick={() => setMenuOpen(!menuOpen)}
            className="ml-auto text-[15px] font-medium"
          >
            {menuOpen ? "Close" : "Menu"}
          </button>
        </div>
        {menuOpen && (
          <div className="border-b border-rule bg-surface px-4 py-3 min-[900px]:hidden">
            {nav(() => setMenuOpen(false))}
            <div className="mt-3 border-t border-rule pt-3">
              <ThemeToggle />
            </div>
          </div>
        )}

        <div className="flex items-center gap-4 border-b border-rule px-4 py-4 sm:px-6">
          <h1 className="text-[22px] font-semibold tracking-tight">
            {isCase ? (
              <>
                <Link
                  href="/app/watchlist"
                  className="text-ink-muted underline decoration-rule underline-offset-4 hover:text-ink"
                >
                  Watchlist
                </Link>{" "}
                / Sleep Number
              </>
            ) : (
              title
            )}
          </h1>
          {!isAgent && (
            <Link
              href="/app/agent"
              className="ml-auto border border-ink bg-ink px-4 py-2 text-[15px] font-medium text-paper"
            >
              Run agent
            </Link>
          )}
        </div>
        <main className="mx-auto w-full max-w-5xl flex-1 px-4 sm:px-6">
          {children}
        </main>
      </div>
    </div>
  );
}
