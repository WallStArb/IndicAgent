"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, LayoutDashboard, Database, BarChart2 } from "lucide-react";

const NAV_ITEMS = [
  { name: "Trading", shortLabel: "Trade", path: "/dashboard", icon: LayoutDashboard },
  { name: "Signals", shortLabel: "Signals", path: "/signals", icon: BarChart2 },
  { name: "Command Center", shortLabel: "Command", path: "/dashboard/observability", icon: Activity },
  { name: "Forensics", shortLabel: "Forensics", path: "/dashboard/hub", icon: Database },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="h-screen flex flex-col md:flex-row bg-[var(--bg-base)] text-[var(--text-primary)]">
      {/* Sidebar/Dock */}
      <nav className="w-full md:w-20 md:h-full border-b md:border-b-0 md:border-r border-[var(--border-subtle)] flex md:flex-col items-center justify-between md:justify-start p-3 bg-[var(--bg-surface)] z-50">
        <div className="flex md:flex-col gap-4 w-full justify-around md:justify-start">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.path === "/dashboard"
                ? pathname === "/dashboard"
                : pathname.startsWith(item.path);
            return (
              <Link
                key={item.name}
                href={item.path}
                aria-current={isActive ? "page" : undefined}
                className={`p-3 rounded-xl transition-all duration-300 flex flex-col items-center gap-1 ${
                  isActive
                    ? "bg-[var(--bg-hover)] text-[var(--accent-cyan)] shadow-lg"
                    : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                }`}
              >
                <item.icon size={20} strokeWidth={isActive ? 2.5 : 2} />
                <span className="text-[0.625rem] font-bold uppercase">{item.shortLabel}</span>
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  );
}
