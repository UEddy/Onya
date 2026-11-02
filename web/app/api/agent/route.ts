/* Agent POST proxy: adds the server-only token, never exposes it.
   No-store: the start request and its response are never cached. */

const NO_STORE = { "Cache-Control": "no-store" } as const;
const UPSTREAM_TIMEOUT_MS = 30_000;

export async function POST(req: Request) {
  const forwardedFor =
    req.headers.get("x-vercel-forwarded-for") ||
    req.headers.get("x-forwarded-for") ||
    "";
  const clientIp = forwardedFor.split(",")[0].trim();
  const base = process.env.ONYA_API_BASE;
  const token = process.env.ONYA_DEMO_TOKEN;
  const basetenKey = process.env.BASETEN_API_KEY;
  if (!base || !token) {
    return Response.json(
      { detail: "agent service is not configured" },
      { status: 500, headers: NO_STORE },
    );
  }
  let question = "";
  try {
    const body = (await req.json()) as { question?: unknown };
    if (typeof body.question === "string") question = body.question;
  } catch {
    return Response.json(
      { detail: "invalid request" },
      { status: 400, headers: NO_STORE },
    );
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${base}/agent/run`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Onya-Token": token,
        ...(basetenKey
          ? { Authorization: `Api-Key ${basetenKey}` }
          : {}),
        ...(clientIp ? { "X-Onya-Client-IP": clientIp } : {}),
      },
      body: JSON.stringify({ question }),
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
