/* Agent POST proxy: adds the server-only token, never exposes it,
   then streams the upstream NDJSON run through to the browser
   unchanged. No timeout here: the run itself can take minutes, and
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
    upstream = await fetch(joinBackendUrl(base, ["agent", "run"]), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Onya-Token": token,
        ...(clientIp ? { "X-Onya-Client-IP": clientIp } : {}),
      },
      body: JSON.stringify({ question }),
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
