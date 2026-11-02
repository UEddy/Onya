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
            className={`flex items-center justify-between rounded-xl px-3 py-2 text-[15px] transition-colors ${
              active
                ? "border border-hairline bg-inset font-semibold shadow-[0_1px_2px_var(--shadow-soft)]"
                : "border border-transparent text-ink-muted hover:bg-[var(--hairline)] hover:text-ink"
            }`}
          >
            <span>{item.label}</span>
            {item.label === "Watchlist" && companies && (
              <span className="flex items-center gap-2">
                <span className="index-label rounded-full bg-[var(--hairline)] px-1.5 text-[12px] text-ink-muted">
                  {companies.length}
                </span>
                {breaches !== null && (
                  <span
                    className="flex items-center gap-1 rounded-full px-1.5 text-[12px]"
                    style={{
                      background:
                        "color-mix(in srgb, var(--breach) 14%, transparent)",
                    }}
                    title={`${breaches} in breach`}
                  >
                    <span aria-hidden="true" className="dot bg-breach" />
                    <span className="index-label text-ink-muted">
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
      <div className="hidden w-[256px] shrink-0 p-3 pr-0 min-[900px]:block">
        <aside className="card sticky top-3 flex h-[calc(100vh-24px)] flex-col p-4">
          <div className="px-1 pt-1">
            <BrandLockup />
          </div>
          <div className="card-inset mt-6 px-3 py-2.5">
            <p className="text-[13px] font-medium">Demo portfolio</p>
            <p className="text-[12px] text-ink-muted">Public SEC data</p>
          </div>
          <div className="mt-4 flex-1">{nav()}</div>
          <div className="border-t border-hairline pt-4">
            <p className="inline-flex items-center gap-2 text-[12px] font-medium">
              <span aria-hidden="true" className="dot bg-pass" />
              Built with Muse Spark Open
            </p>
            <p className="mt-2 text-[12px] leading-snug text-ink-muted">
              Onya supports review by credit professionals. It is not financial,
              legal or investment advice.
            </p>
            <div className="mt-3">
              <ThemeToggle />
            </div>
          </div>
        </aside>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-30 border-b border-hairline bg-[color-mix(in_srgb,var(--paper)_82%,transparent)] backdrop-blur-xl">
          <div className="flex items-center gap-4 px-4 py-3 min-[900px]:hidden">
            <BrandLockup compact />
            <button
              type="button"
              aria-expanded={menuOpen}
              aria-label="Menu"
              onClick={() => setMenuOpen(!menuOpen)}
              className="btn btn-secondary btn-sm ml-auto"
            >
              {menuOpen ? "Close" : "Menu"}
            </button>
          </div>
          <div className="mx-auto flex w-full max-w-6xl items-center gap-4 border-t border-hairline px-4 py-3 sm:px-6 min-[900px]:border-t-0 min-[900px]:py-4">
            <h1 className="text-[18px] font-semibold tracking-tight sm:text-[20px]">
              {isCase ? (
                <>
                  <Link
                    href="/app/watchlist"
                    className="text-ink-muted transition-colors hover:text-ink"
                  >
                    Watchlist
                  </Link>{" "}
                  <span className="text-ink-muted">/</span> Sleep Number
                </>
              ) : (
                title
              )}
            </h1>
            {!isAgent && (
              <Link href="/app/agent" className="btn btn-primary btn-sm ml-auto">
                Run agent
              </Link>
            )}
          </div>
        </div>
        {menuOpen && (
          <div className="fixed inset-x-3 top-[60px] z-40 min-[900px]:hidden">
            <div className="card-float enter p-3">
              <div className="card-inset mb-3 px-3 py-2.5">
                <p className="text-[13px] font-medium">Demo portfolio</p>
                <p className="text-[12px] text-ink-muted">Public SEC data</p>
              </div>
              {nav(() => setMenuOpen(false))}
              <div className="mt-3 border-t border-hairline pt-3">
                <ThemeToggle />
              </div>
            </div>
          </div>
        )}
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 sm:px-6">
          {children}
        </main>
      </div>
    </div>
  );
}
