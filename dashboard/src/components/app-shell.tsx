"use client";

import { FloatingDock } from "@/components/floating-dock";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-screen flex flex-col bg-[var(--bg-base)] text-[var(--text-primary)]">
      <main className="flex-1 overflow-auto pb-28">
        {children}
      </main>
      <FloatingDock />
    </div>
  );
}
