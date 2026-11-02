import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-1 items-center justify-center px-4 py-16">
      <div className="card enter w-full max-w-[560px] p-8">
        <h1 className="text-[30px] font-semibold tracking-tight">
          This page is not in the file.
        </h1>
        <p className="mt-2 max-w-[65ch] text-[15px] text-ink-muted">
          Onya has no page at this address.
        </p>
        <Link href="/" className="btn btn-primary mt-6">
          Back to the watchlist
        </Link>
      </div>
    </div>
  );
}
