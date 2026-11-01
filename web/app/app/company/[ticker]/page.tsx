import { Suspense } from "react";
import CaseView from "../../../../components/case-view";

async function CaseLoader({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;
  return <CaseView ticker={(ticker ?? "").toUpperCase()} />;
}

export default function CasePage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  return (
    <Suspense
      fallback={
        <p role="status" className="py-8 text-[15px] text-ink-muted">
          Opening the case file.
        </p>
      }
    >
      <CaseLoader params={params} />
    </Suspense>
  );
}
