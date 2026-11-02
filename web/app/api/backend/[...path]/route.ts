import { NextResponse } from "next/server";
import { joinBackendUrl } from "../../../../lib/api";

/* Server-side proxy for read-only backend calls. The browser talks
   only to this origin. Reads are public data, so no token is needed;
   agent calls go through /api/agent, which adds the server-only
   token. Gateway errors (502/503/504) pass through untouched so the
   UI can show the waking notice for them. */
const UPSTREAM_TIMEOUT_MS = 30_000;

export async function GET(
  req: Request,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const base = process.env.ONYA_API_BASE;
  if (!base) {
    return NextResponse.json(
      { detail: "Backend is not configured." },
      { status: 502 },
    );
  }
  const { path } = await params;
  const url = new URL(req.url);
  const target = `${joinBackendUrl(base, path)}${url.search}`;
  try {
    const res = await fetch(target, {
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    const body = await res.text();
    return new Response(body, {
      status: res.status,
      headers: {
        "Content-Type": res.headers.get("Content-Type") ?? "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    const timedOut =
      error instanceof DOMException && error.name === "TimeoutError";
    return NextResponse.json(
      {
        detail: timedOut
          ? "Backend timed out (cold start)."
          : "Backend unreachable.",
      },
      { status: timedOut ? 503 : 502 },
    );
  }
}
