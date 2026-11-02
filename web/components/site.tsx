
export function StatusMark({
  tone,
  word,
}: {
  tone: "pass" | "watch" | "breach" | "neutral";
  word: string;
}) {
  const fill =
    tone === "pass"
      ? "bg-pass"
      : tone === "watch"
        ? "bg-watch"
        : tone === "breach"
          ? "bg-breach"
          : "bg-ink-muted";
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span aria-hidden="true" className={`dot ${fill}`} />
      <span>{word}</span>
    </span>
  );
}

export function StatusPill({
  tone,
  word,
}: {
  tone: "pass" | "watch" | "breach" | "neutral";
  word: string;
}) {
  const color =
    tone === "pass"
      ? "var(--pass)"
      : tone === "watch"
        ? "var(--watch)"
        : tone === "breach"
          ? "var(--breach)"
          : "var(--ink-muted)";
  return (
    <span
      className="inline-flex items-center gap-2 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[13px] font-medium"
      style={{
        background: `color-mix(in srgb, ${color} 14%, transparent)`,
        boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${color} 30%, transparent)`,
      }}
    >
      <span aria-hidden="true" className="dot" style={{ background: color }} />
      <span>{word}</span>
    </span>
  );
}

export function DataNote({ children }: { children?: React.ReactNode }) {
  return (
    <p className="text-[13px] text-ink-muted">
      {children ?? "Public SEC data"}
    </p>
  );
}

export function LoadingLine({ text }: { text: string }) {
  return (
    <div className="card mt-6 p-6">
      <p role="status" className="text-[15px] text-ink-muted">
        {text}
      </p>
      <div aria-hidden="true" className="mt-5 space-y-3">
        <div className="skeleton h-2.5 w-2/3" />
        <div className="skeleton h-2.5 w-1/2" />
        <div className="skeleton h-2.5 w-3/5" />
      </div>
    </div>
  );
}

export function ErrorLine({
  title,
  children,
  onRetry,
}: {
  title: string;
  children: React.ReactNode;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="card mt-6 p-6">
      <p className="flex items-center gap-2 text-[17px] font-medium">
        <span aria-hidden="true" className="dot bg-watch" />
        {title}
      </p>
      <p className="mt-1 max-w-[65ch] text-[15px] text-ink-muted">{children}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="btn btn-secondary btn-sm mt-4"
        >
          Try again
        </button>
      )}
    </div>
  );
}

/** A big centered line in two tones: the claim, then the muted follow-on. */
export function Statement({
  lead,
  rest,
  id,
  as: Tag = "h2",
}: {
  lead: string;
  rest?: string;
  id?: string;
  as?: "h1" | "h2" | "p";
}) {
  return (
    <Tag
      id={id}
      className="mx-auto max-w-[860px] text-balance text-center text-[26px] font-semibold leading-[1.18] tracking-tight sm:text-[36px]"
    >
      <span>{lead}</span>
      {rest ? <span className="text-ink-muted"> {rest}</span> : null}
    </Tag>
  );
}

/** A titled card for one section of an app page. */
export function Panel({
  title,
  description,
  id,
  children,
  className,
  action,
}: {
  title?: string;
  description?: React.ReactNode;
  id?: string;
  children: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
}) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={title ? headingId : undefined}
      className={`card scroll-mt-24 p-5 sm:p-7 ${className ?? ""}`}
    >
      {(title || action) && (
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            {title && (
              <h2
                id={headingId}
                className="text-[20px] font-semibold tracking-tight"
              >
                {title}
              </h2>
            )}
            {description && (
              <p className="mt-1 max-w-[75ch] text-[13px] text-ink-muted">
                {description}
              </p>
            )}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
