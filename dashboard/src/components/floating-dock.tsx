"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { LayoutGrid, Activity, Cpu, BrainCircuit } from "lucide-react";

const ITEMS = [
  { icon: LayoutGrid, label: "Dashboard", href: "/dashboard",              match: (p: string) => p === "/dashboard",              live: false },
  { icon: Activity,   label: "Signals",   href: "/signals",                match: (p: string) => p.startsWith("/signals"),         live: false },
  { icon: Cpu,        label: "System",    href: "/dashboard/observability", match: (p: string) => p === "/dashboard/observability", live: false },
  { icon: BrainCircuit, label: "AI Swarm", href: "/dashboard/ai",          match: (p: string) => p === "/dashboard/ai",            live: true  },
] as const;

export function FloatingDock() {
  const pathname = usePathname();
  const [hovered, setHovered] = useState<string | null>(null);

  return (
    <>
      <style>{`
        @keyframes dock-enter {
          from { opacity: 0; transform: translateY(28px) scale(0.94); }
          to   { opacity: 1; transform: translateY(0)    scale(1);    }
        }
        @keyframes live-pulse {
          0%, 100% { opacity: 1;    box-shadow: 0 0 0 0 rgba(78,214,200,0.7); }
          50%       { opacity: 0.5; box-shadow: 0 0 0 4px rgba(78,214,200,0); }
        }
        @keyframes active-glow {
          0%, 100% { box-shadow: 0 0 6px 1px rgba(78,214,200,0.55); }
          50%       { box-shadow: 0 0 10px 3px rgba(78,214,200,0.2); }
        }
      `}</style>

      <div
        style={{
          position: "fixed",
          bottom: 0,
          left: 0,
          width: "100vw",
          display: "flex",
          justifyContent: "center",
          pointerEvents: "none",
          zIndex: 100,
          paddingBottom: "20px",
        }}
      >
        <nav
          style={{
            pointerEvents: "auto",
            display: "flex",
            alignItems: "center",
            gap: "2px",
            padding: "6px",
            background: "rgba(6, 9, 15, 0.84)",
            backdropFilter: "blur(32px) saturate(160%)",
            WebkitBackdropFilter: "blur(32px) saturate(160%)",
            border: "1px solid rgba(78,214,200,0.10)",
            borderRadius: "22px",
            boxShadow:
              "0 16px 56px rgba(0,0,0,0.6), " +
              "0 0 0 1px rgba(255,255,255,0.03) inset, " +
              "0 1px 0 rgba(255,255,255,0.06) inset",
            animation: "dock-enter 0.5s cubic-bezier(0.34,1.56,0.64,1) both",
          }}
        >
          {ITEMS.map((item) => {
            const isActive = item.match(pathname);
            const isHov   = hovered === item.href;
            const Icon    = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                onMouseEnter={() => setHovered(item.href)}
                onMouseLeave={() => setHovered(null)}
                style={{
                  position: "relative",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "5px",
                  width: "72px",
                  height: "62px",
                  borderRadius: "16px",
                  textDecoration: "none",
                  transition: "transform 0.28s cubic-bezier(0.34,1.56,0.64,1), background 0.15s",
                  transform: isHov ? "scale(1.16) translateY(-5px)" : "scale(1) translateY(0)",
                  background: isActive
                    ? "rgba(78,214,200,0.07)"
                    : isHov
                    ? "rgba(255,255,255,0.04)"
                    : "transparent",
                }}
              >
                {/* Live pulse dot — top-right corner */}
                {item.live && (
                  <span style={{
                    position: "absolute",
                    top: "11px",
                    right: "15px",
                    width: "5px",
                    height: "5px",
                    borderRadius: "50%",
                    background: "var(--accent-cyan)",
                    animation: "live-pulse 2s ease-in-out infinite",
                  }} />
                )}

                <Icon
                  size={20}
                  style={{
                    color: isActive ? "var(--accent-cyan)" : isHov ? "var(--text-secondary)" : "var(--text-muted)",
                    strokeWidth: isActive ? 2 : 1.5,
                    transition: "color 0.15s",
                  }}
                />

                <span style={{
                  fontFamily: "var(--font-jetbrains)",
                  fontSize: "0.52rem",
                  letterSpacing: "0.09em",
                  textTransform: "uppercase",
                  color: isActive ? "var(--accent-cyan)" : "var(--text-muted)",
                  opacity: isActive ? 1 : isHov ? 0.85 : 0.55,
                  transition: "color 0.15s, opacity 0.15s",
                  lineHeight: 1,
                }}>
                  {item.label}
                </span>

                {/* Active indicator dot */}
                {isActive && (
                  <span style={{
                    position: "absolute",
                    bottom: "6px",
                    left: "50%",
                    transform: "translateX(-50%)",
                    width: "4px",
                    height: "4px",
                    borderRadius: "50%",
                    background: "var(--accent-cyan)",
                    animation: "active-glow 2.2s ease-in-out infinite",
                  }} />
                )}
              </Link>
            );
          })}
        </nav>
      </div>
    </>
  );
}
