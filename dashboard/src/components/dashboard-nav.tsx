"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

function IndicAgentLogo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="2"  y="5"  width="24" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.4" />
      <rect x="5"  y="10" width="18" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.65" />
      <rect x="8"  y="15" width="12" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.85" />
      <rect x="11" y="20" width="6"  height="3" rx="1.5" fill="var(--accent-cyan)" />
      <circle cx="24" cy="21.5" r="2.5" fill="var(--accent-cyan)" opacity="0.9" />
    </svg>
  );
}

const NAV_ITEMS = [
  {
    label: "Dashboard",
    href: "/dashboard",
    match: (p: string) => p === "/dashboard",
  },
  {
    label: "Signals",
    href: "/signals",
    match: (p: string) => p.startsWith("/signals"),
  },
  {
    label: "System",
    href: "/dashboard/observability",
    match: (p: string) => p === "/dashboard/observability",
  },
  {
    label: "AI Swarm",
    href: "/dashboard/ai",
    match: (p: string) => p === "/dashboard/ai",
  },
  {
    label: "Hub",
    href: "/dashboard/hub",
    match: (p: string) => p === "/dashboard/hub",
  },
] as const;

export function DashboardNav() {
  const pathname = usePathname();

  return (
    <nav
      className="sticky top-0 z-50 flex items-center gap-0 border-b shrink-0"
      style={{
        height: "40px",
        background: "rgba(6, 9, 15, 0.96)",
        backdropFilter: "blur(12px)",
        borderColor: "var(--border-subtle)",
      }}
    >
      {/* Logo + wordmark */}
      <Link
        href="/dashboard"
        className="flex items-center gap-2 px-5 hover:opacity-80 transition-opacity shrink-0"
        style={{ height: "40px" }}
      >
        <IndicAgentLogo size={20} />
        <span
          style={{
            fontFamily: "var(--font-display)",
            fontWeight: 800,
            fontSize: "0.82rem",
            letterSpacing: "-0.02em",
            color: "var(--text-primary)",
          }}
        >
          Indic<span style={{ color: "var(--accent-cyan)" }}>Agent</span>
        </span>
      </Link>

      {/* Divider */}
      <div className="w-px h-4 shrink-0" style={{ background: "var(--border-bright)" }} />

      {/* Nav items */}
      {NAV_ITEMS.map((item) => {
        const isActive = item.match(pathname);
        return (
          <Link
            key={item.href}
            href={item.href}
            className="flex items-center transition-colors"
            style={{
              fontFamily: "var(--font-jetbrains)",
              fontSize: "0.6rem",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              fontWeight: isActive ? 600 : 400,
              color: isActive ? "var(--accent-cyan)" : "var(--text-muted)",
              padding: "0 12px",
              height: "40px",
              borderBottom: isActive
                ? "2px solid var(--accent-cyan)"
                : "2px solid transparent",
              marginBottom: "-1px",
            }}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
