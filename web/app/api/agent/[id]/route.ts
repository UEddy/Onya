/* Agent poll proxy: public run state only, token stays server-side.
   No-store: every poll fetches upstream uncached and returns
   Cache-Control: no-store, so a finished run is never served stale. */

const RUN_ID_RE = /^[0-9a-fA-F-]{1,64}$/;
const NO_STORE = { "Cache-Control": "no-store" } as const;
const UPSTREAM_TIMEOUT_MS = 30_000;

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!RUN_ID_RE.test(id)) {
    return Response.json(
      { detail: "unknown run" },
      { status: 404, headers: NO_STORE },
    );
  }
  const base = process.env.ONYA_API_BASE;
  const token = process.env.ONYA_DEMO_TOKEN;
  const basetenKey = process.env.BASETEN_API_KEY;
  if (!base || !token) {
    return Response.json(
      { detail: "agent service is not configured" },
      { status: 500, headers: NO_STORE },
    );
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${base}/agent/run/${id}`, {
      headers: {
        "X-Onya-Token": token,
        ...(basetenKey
          ? { Authorization: `Api-Key ${basetenKey}` }
          : {}),
      },
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch {
    return Response.json(
      { detail: "agent service is unreachable" },
      { status: 502, headers: NO_STORE },
    );
  }
  const data = (await upstream.json().catch(() => ({
    detail: "agent service returned an invalid response",
  }))) as unknown;
  return Response.json(data, { status: upstream.status, headers: NO_STORE });
}
