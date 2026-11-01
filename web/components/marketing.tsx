"use client";

import Link from "next/link";
import { useState } from "react";
import { ThemeToggle } from "./theme";

export function BrandLockup() {
  return (
    <Link href="/" aria-label="Onya" className="inline-block">
      <span className="flex items-baseline text-[22px] font-medium leading-none tracking-tight">
        <svg
          aria-hidden="true"
          viewBox="0 0 64 64"
          className="h-[1.05em] w-[1.05em] shrink-0 translate-y-[0.14em]"
          fill="none"
        >
          <circle
            cx="32"
            cy="32"
            r="20"
            stroke="currentColor"
            strokeWidth="7"
            strokeDasharray="110 15.66"
          />
          <circle cx="50.48" cy="24.35" r="6.2" fill="var(--breach)" stroke="none" />
        </svg>
        <span>nya</span>
      </span>
      <span className="mt-1 hidden text-[13px] leading-tight text-ink-muted min-[600px]:block">
        Covenant monitoring
        <br />
        for private credit
      </span>
    </Link>
  );
}

const MARKETING_NAV = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#sleep-number", label: "Sleep Number" },
  { href: "/accuracy", label: "Accuracy" },
  { href: "/#questions", label: "Questions" },
];

export function MarketingHeader() {
  const [open, setOpen] = useState(false);
  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex max-w-5xl items-start gap-x-8 px-4 py-4 sm:px-6">
        <BrandLockup />
        <nav
          aria-label="Marketing"
          className="mx-auto hidden items-center gap-x-6 pt-1 md:flex"
        >
          {MARKETING_NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-[15px] text-ink-muted underline decoration-rule underline-offset-4 hover:text-ink"
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4 pt-1 md:ml-0">
          <ThemeToggle />
          <Link
            href="/app/watchlist"
            className="border border-ink bg-ink px-4 py-2 text-[15px] font-medium text-paper"
          >
            Get started
          </Link>
          <button
            type="button"
            aria-expanded={open}
            aria-label="Menu"
            onClick={() => setOpen(!open)}
            className="text-[15px] font-medium md:hidden"
          >
            {open ? "Close" : "Menu"}
          </button>
        </div>
      </div>
      {open && (
        <nav aria-label="Marketing mobile" className="border-t border-rule px-4 py-3 md:hidden">
          {MARKETING_NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className="block py-2 text-[15px]"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

export function MarketingFooter() {
  const repoUrl = process.env.NEXT_PUBLIC_REPO_URL;
  return (
    <footer className="mt-16 border-t border-rule no-print">
      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        <BrandLockup />
        <p className="mt-3 text-[13px] text-ink-muted">
          Built on public SEC filings.
        </p>
        <div className="mt-2 flex gap-x-5 text-[13px]">
          <Link
            href="/accuracy"
            className="text-ink-muted underline decoration-rule underline-offset-4 hover:text-ink"
          >
            Accuracy
          </Link>
          {repoUrl ? (
            <a
              href={repoUrl}
              className="text-ink-muted underline decoration-rule underline-offset-4 hover:text-ink"
            >
              GitHub
            </a>
          ) : null}
        </div>
      </div>
    </footer>
  );
}

export function MarketingShell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <MarketingHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 sm:px-6">
        {children}
      </main>
      <MarketingFooter />
    </>
  );
}
