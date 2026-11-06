import { Separator } from "@/components/ui/separator";

/** Eyebrow, display title and rule shared by the landing sections. */
export function SectionHeading({
  eyebrow,
  title,
  intro,
  accent = "var(--accent-cyan)",
}: {
  eyebrow: string;
  title: string;
  intro?: string;
  accent?: string;
}) {
  return (
    <div className="mb-8">
      <div className="flex items-end gap-6">
        <div>
          <p
            className="mb-1"
            style={{
              fontFamily: "var(--font-jetbrains)",
              fontSize: "0.6rem",
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: accent,
            }}
          >
            {eyebrow}
          </p>
          <h2
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "clamp(1.6rem, 3vw, 2.2rem)",
              fontWeight: 800,
              letterSpacing: "-0.03em",
              color: "var(--text-primary)",
              lineHeight: 1.05,
            }}
          >
            {title}
          </h2>
        </div>
        <Separator className="mb-1 w-auto flex-1 bg-[var(--border-subtle)]" />
      </div>
      {intro && (
        <p className="mt-4 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          {intro}
        </p>
      )}
    </div>
  );
}

export const MONO_LABEL = {
  fontFamily: "var(--font-jetbrains)",
  fontSize: "0.58rem",
  letterSpacing: "0.14em",
  textTransform: "uppercase",
  color: "var(--text-muted)",
} as const;

/** Two-digit index for numbered lists. */
export const pad2 = (n: number) => String(n).padStart(2, "0");
