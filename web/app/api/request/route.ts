/* Information-request proxy: adds the server-only token, then
   streams the upstream NDJSON result through to the browser
   unchanged. No timeout here: the tool recomputes the period, and
   the function cap below bounds it. */

import { joinBackendUrl } from "../../../lib/api";

export const maxDuration = 300;

const NO_STORE = { "Cache-Control": "no-store" } as const;

export async function POST(req: Request) {
  const forwardedFor =
    req.headers.get("x-vercel-forwarded-for") ||
    req.headers.get("x-forwarded-for") ||
    "";
  const clientIp = forwardedFor.split(",")[0].trim();
  const base = process.env.ONYA_API_BASE;
  const token = process.env.ONYA_DEMO_TOKEN;
  if (!base || !token) {
    return Response.json(
      { detail: "agent service is not configured" },
      { status: 500, headers: NO_STORE },
    );
  }
  let company = "";
  let periodEnd = "";
  try {
    const body = (await req.json()) as {
      company?: unknown;
      period_end?: unknown;
    };
    if (typeof body.company === "string") company = body.company;
    if (typeof body.period_end === "string") periodEnd = body.period_end;
  } catch {
    return Response.json(
      { detail: "invalid request" },
      { status: 400, headers: NO_STORE },
    );
  }
  let upstream: Response;
  try {
    upstream = await fetch(joinBackendUrl(base, ["agent", "info-request"]), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Onya-Token": token,
        ...(clientIp ? { "X-Onya-Client-IP": clientIp } : {}),
      },
      body: JSON.stringify({ company, period_end: periodEnd }),
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { detail: "agent service is unreachable" },
      { status: 502, headers: NO_STORE },
    );
  }
  if (!upstream.ok || !upstream.body) {
    const data = (await upstream.json().catch(() => ({
      detail: "agent service returned an invalid response",
    }))) as unknown;
    return Response.json(data, {
      status: upstream.status,
      headers: NO_STORE,
    });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "application/x-ndjson",
      ...NO_STORE,
    },
  });
}
