/* Run polling was removed: POST /api/agent streams the run, so
   there is nothing to poll. This stub keeps the old path answering
   with a clear message instead of a bare 404. */

const NO_STORE = { "Cache-Control": "no-store" } as const;

export async function GET() {
  return Response.json(
    { detail: "run polling was removed; POST /api/agent streams the run" },
    { status: 404, headers: NO_STORE },
  );
}
