
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
      <span aria-hidden="true" className={`inline-block h-2.5 w-2.5 ${fill}`} />
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
    <p role="status" className="py-8 text-[15px] text-ink-muted">
      {text}
    </p>
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
    <div role="alert" className="border-t border-rule py-8">
      <p className="text-[17px] font-medium">{title}</p>
      <p className="mt-1 max-w-[65ch] text-[15px] text-ink-muted">{children}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 text-[15px] underline decoration-rule underline-offset-4 hover:text-ink"
        >
          Try again
        </button>
      )}
    </div>
  );
}
