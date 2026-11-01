import Link from "next/link";

export default function NotFound() {
  return (
    <div className="py-16">
      <h1 className="text-[30px] font-semibold tracking-tight">
        This page is not in the file.
      </h1>
      <p className="mt-2 max-w-[65ch] text-[15px] text-ink-muted">
        Onya has no page at this address.{" "}
        <Link
          href="/"
          className="underline decoration-rule underline-offset-4 hover:decoration-ink"
        >
          Back to the watchlist
        </Link>
      </p>
    </div>
  );
}
