"use client";

import Link from "next/link";
import { useState } from "react";
import { ThemeToggle } from "./theme";

export function BrandLockup({ compact = false }: { compact?: boolean }) {
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
      {!compact && (
        <span className="mt-1 hidden text-[13px] leading-tight text-ink-muted min-[600px]:block">
          Covenant monitoring
          <br />
          for private credit
        </span>
      )}
    </Link>
  );
}

const MARKETING_NAV = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#sleep-number", label: "Sleep Number" },
  { href: "/accuracy", label: "Accuracy" },
  { href: "/#questions", label: "Questions" },
];

const BANNER_ITEMS = [
  "Jun 12, 2026: Sleep Number files for Chapter 11",
  "Onya flagged high risk from the January numbers, before the breach",
];

function Banner() {
  const items = [...BANNER_ITEMS, ...BANNER_ITEMS];
  return (
    <div className="mx-auto max-w-6xl px-3 sm:px-6">
      <Link
        href="/#sleep-number"
        className="marquee block rounded-b-[14px] rounded-t-[4px] text-[13px] font-medium shadow-[0_10px_24px_-14px_var(--shadow-float)]"
        style={{
          background: "var(--banner-bg)",
          color: "var(--banner-ink)",
          ["--marquee-duration" as string]: "36s",
        }}
      >
        <span className="sr-only">{BANNER_ITEMS.join(". ")}.</span>
        <span aria-hidden="true" className="marquee-track py-1.5">
          {[...items, ...items].map((text, i) => (
            <span key={i} className="flex shrink-0 items-center gap-3 px-4">
              <span className="whitespace-nowrap">{text}</span>
              <span>&rarr;</span>
            </span>
          ))}
        </span>
      </Link>
    </div>
  );
}

export function MarketingHeader() {
  const [open, setOpen] = useState(false);
  return (
    <div className="sticky top-0 z-40 no-print">
      <header className="border-b border-hairline bg-[color-mix(in_srgb,var(--paper)_82%,transparent)] backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center gap-x-8 px-4 py-3 sm:px-6">
          <BrandLockup compact />
          <nav
            aria-label="Marketing"
            className="mx-auto hidden items-center gap-x-1 md:flex"
          >
            {MARKETING_NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="rounded-full px-3 py-1.5 text-[14px] text-ink-muted transition-colors hover:bg-[var(--hairline)] hover:text-ink"
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 md:ml-0">
            <ThemeToggle />
            <Link href="/app/watchlist" className="btn btn-primary btn-sm">
              Get started
            </Link>
            <button
              type="button"
              aria-expanded={open}
              aria-label="Menu"
              onClick={() => setOpen(!open)}
              className="btn btn-secondary btn-sm md:hidden"
            >
              {open ? "Close" : "Menu"}
            </button>
          </div>
        </div>
      </header>
      <Banner />
      {open && (
        <div className="px-3 pt-2 md:hidden">
          <nav
            aria-label="Marketing mobile"
            className="card-float enter p-2"
          >
            {MARKETING_NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className="block rounded-xl px-3 py-2.5 text-[15px] hover:bg-inset"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      )}
    </div>
  );
}

export function MarketingFooter() {
  const repoUrl = process.env.NEXT_PUBLIC_REPO_URL;
  const columns: { title: string; links: { href: string; label: string; external?: boolean }[] }[] = [
    {
      title: "Product",
      links: [
        { href: "/app/watchlist", label: "Watchlist" },
        { href: "/app/company/SNBR", label: "Sleep Number case" },
        { href: "/app/agent", label: "Agent" },
      ],
    },
    {
      title: "Proof",
      links: [
        { href: "/accuracy", label: "Accuracy" },
        { href: "/#how-it-works", label: "How it works" },
        { href: "/#questions", label: "Questions" },
      ],
    },
    {
      title: "Source",
      links: [
        { href: "https://www.sec.gov/edgar/search/", label: "SEC EDGAR", external: true },
        ...(repoUrl ? [{ href: repoUrl, label: "GitHub", external: true }] : []),
      ],
    },
  ];
  return (
    <footer className="no-print mt-24 px-3 pb-3 sm:px-6 sm:pb-6">
      <div className="card mx-auto max-w-6xl overflow-hidden p-6 sm:p-10">
        <div className="grid gap-10 md:grid-cols-[minmax(0,1.2fr)_repeat(3,minmax(0,1fr))]">
          <div>
            <BrandLockup />
            <p className="mt-4 max-w-[34ch] text-[13px] text-ink-muted">
              Built on public SEC filings.
            </p>
            <p className="mt-4 inline-flex items-center gap-2 rounded-full border border-hairline bg-inset px-3 py-1 text-[12px] font-medium">
              <span aria-hidden="true" className="dot bg-pass" />
              Built with Muse Spark Open
            </p>
          </div>
          {columns.map((column) => (
            <div key={column.title}>
              <p className="text-[13px] font-semibold">{column.title}</p>
              <ul className="mt-3 space-y-2">
                {column.links.map((link) => (
                  <li key={link.label}>
                    {link.external ? (
                      <a
                        href={link.href}
                        className="text-[13px] text-ink-muted transition-colors hover:text-ink"
                      >
                        {link.label}
                      </a>
                    ) : (
                      <Link
                        href={link.href}
                        className="text-[13px] text-ink-muted transition-colors hover:text-ink"
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <p className="mt-10 border-t border-hairline pt-5 text-[12px] text-ink-muted">
          Onya supports review by credit professionals. It is not financial,
          legal or investment advice.
        </p>
      </div>
    </footer>
  );
}

export function MarketingShell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <MarketingHeader />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 sm:px-6">
        {children}
      </main>
      <MarketingFooter />
    </>
  );
}
