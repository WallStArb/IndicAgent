import Link from "next/link";

const PAGES = [
  { label: "Data", href: "/data" },
  { label: "Instruments", href: "/instruments" },
  { label: "Concepts", href: "/concepts" },
  { label: "Research", href: "/research" },
  { label: "Books", href: "/books" },
  { label: "System", href: "/system" },
];

/** Inline SVG logo - stacked stages narrowing to one book */
function IndicAgentLogo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Three horizontal bars - each shorter, as the DAG narrows from data to one book */}
      <rect x="2"  y="5"  width="24" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.4" />
      <rect x="5"  y="10" width="18" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.65" />
      <rect x="8"  y="15" width="12" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.85" />
      <rect x="11" y="20" width="6"  height="3" rx="1.5" fill="var(--accent-cyan)" />
      {/* Pulse dot */}
      <circle cx="24" cy="21.5" r="2.5" fill="var(--accent-cyan)" opacity="0.9" />
    </svg>
  );
}

export function LandingNav() {
  return (
    <nav
      className="flex items-center justify-between px-6 py-3 border-b"
      style={{
        borderColor: "var(--border-subtle)",
        background: "rgba(10, 14, 20, 0.85)",
        backdropFilter: "blur(8px)",
        position: "sticky",
        top: 0,
        zIndex: 40,
      }}
    >
      {/* Wordmark */}
      <div className="flex items-center gap-2.5">
        <IndicAgentLogo size={26} />
        <span
          className="text-base font-bold tracking-tight"
          style={{
            color: "var(--text-primary)",
            fontFamily: "var(--font-display)",
            letterSpacing: "-0.01em",
          }}
        >
          Indic
          <span style={{ color: "var(--accent-cyan)" }}>Agent</span>
        </span>
      </div>

      {/* Nav links */}
      <div className="flex items-center gap-4">
        {PAGES.map(({ label, href }) => (
          <Link
            key={href}
            href={href}
            className="hidden md:block text-xs transition-colors hover:text-[var(--text-primary)]"
            style={{ color: "var(--text-secondary)" }}
          >
            {label}
          </Link>
        ))}
        <Link
          href="/pipeline"
          className="flex items-center gap-1.5 px-3 py-1.5 transition-all hover:opacity-90"
          style={{
            fontFamily: "var(--font-display)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            background: "var(--accent-cyan)",
            color: "#080b11",
            borderRadius: "4px",
            fontSize: "0.65rem",
            fontWeight: 700,
          }}
        >
          Pipeline →
        </Link>
      </div>
    </nav>
  );
}
