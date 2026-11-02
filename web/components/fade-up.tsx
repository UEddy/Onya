"use client";

import { useEffect, useRef } from "react";

/**
 * Reveal: the element rises into place when it scrolls into view.
 * `pop` makes it overshoot slightly and drift in from the side, for cards
 * that sit on top of another card. `onLoad` plays the motion right away
 * with CSS only, for content above the fold.
 */
export function Reveal({
  children,
  className,
  delay = 0,
  pop = false,
  popX,
  onLoad = false,
  as: Tag = "div",
  id,
  ariaLabel,
  ariaLabelledBy,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
  pop?: boolean;
  popX?: number;
  onLoad?: boolean;
  as?: "div" | "section" | "li" | "aside";
  id?: string;
  ariaLabel?: string;
  ariaLabelledBy?: string;
}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (onLoad) return;
    const el = ref.current;
    if (!el) return;
    if (
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      typeof IntersectionObserver === "undefined"
    ) {
      el.classList.add("is-visible");
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            el.classList.add("is-visible");
            observer.disconnect();
          }
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -40px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [onLoad]);
  const style = {
    "--reveal-delay": `${delay}ms`,
    ...(popX !== undefined ? { "--pop-x": `${popX}px` } : {}),
  } as React.CSSProperties;
  return (
    <Tag
      ref={ref as React.Ref<never>}
      id={id}
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      style={style}
      className={`${onLoad ? "enter" : "reveal"} ${pop ? "pop-out" : ""} ${className ?? ""}`}
    >
      {children}
    </Tag>
  );
}

export default function FadeUp({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <Reveal className={className}>{children}</Reveal>;
}
