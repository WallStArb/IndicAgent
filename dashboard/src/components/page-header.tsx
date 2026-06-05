"use client";

import type { ReactNode } from "react";

function IndicAgentLogo({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect x="2"  y="5"  width="24" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.4" />
      <rect x="5"  y="10" width="18" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.65" />
      <rect x="8"  y="15" width="12" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.85" />
      <rect x="11" y="20" width="6"  height="3" rx="1.5" fill="var(--accent-cyan)" />
      <circle cx="24" cy="21.5" r="2.5" fill="var(--accent-cyan)" opacity="0.9" />
    </svg>
  );
}

interface PageHeaderProps {
  /** Page-specific title shown after the wordmark divider. Omit on the main dashboard. */
  title?: string;
  /** Dim subtitle below the title. */
  subtitle?: string;
  /** Extra content rendered after the wordmark (e.g. profile switcher). */
  left?: ReactNode;
  /** Right-side actions (e.g. timeframe pills, LIVE badge, refresh button). */
  right?: ReactNode;
  className?: string;
}

export function PageHeader({ title, subtitle, left, right, className = "" }: PageHeaderProps) {
  return (
    <header
      className={`flex items-center justify-between px-6 py-3 border-b border-[var(--border-subtle)] shrink-0 ${className}`}
      style={{
        background: "rgba(6, 9, 15, 0.95)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
      }}
    >
      {/* Left cluster */}
      <div className="flex items-center gap-2 md:gap-4">
        {/* Wordmark */}
        <div className="flex items-center gap-2.5">
          <IndicAgentLogo size={24} />
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontWeight: 800,
              fontSize: "1rem",
              letterSpacing: "-0.02em",
              color: "var(--text-primary)",
            }}
          >
            Indic<span style={{ color: "var(--accent-cyan)" }}>Agent</span>
          </span>
        </div>

        {/* Page title — shown when navigated away from the main dashboard */}
        {title && (
          <>
            <span
              aria-hidden
              style={{
                width: 1,
                height: 20,
                background: "var(--border-bright)",
                display: "inline-block",
                borderRadius: 1,
                flexShrink: 0,
              }}
            />
            <div>
              <div
                className="text-[0.85rem] font-semibold text-[var(--text-primary)] leading-tight"
                style={{ fontFamily: "var(--font-display)", letterSpacing: "-0.01em" }}
              >
                {title}
              </div>
              {subtitle && (
                <div className="text-[0.6rem] text-[var(--text-muted)] mt-0.5 leading-tight">
                  {subtitle}
                </div>
              )}
            </div>
          </>
        )}

        {/* Caller-supplied left content (e.g. profile switcher) */}
        {left}
      </div>

      {/* Right-side actions */}
      {right && <div className="flex items-center gap-4">{right}</div>}
    </header>
  );
}
