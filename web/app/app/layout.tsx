import { Suspense } from "react";
import { AppShell } from "../../components/app-shell";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Suspense
      fallback={
        <p role="status" className="px-4 py-8 text-[15px] text-ink-muted">
          Opening the app.
        </p>
      }
    >
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
