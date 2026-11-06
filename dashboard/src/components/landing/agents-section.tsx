import { agents } from "@/lib/copy/landing";
import { MONO_LABEL, SectionHeading, pad2 } from "./section-heading";

/** How the agents work: the roles, and the gates that bind them. */
export function AgentsSection() {
  return (
    <section className="px-6 py-12 border-t" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="max-w-7xl mx-auto">
        <SectionHeading eyebrow={agents.eyebrow} title={agents.title} intro={agents.intro} accent="var(--accent-amber)" />
        <ol className="grid gap-px sm:grid-cols-2 lg:grid-cols-4" style={{ background: "var(--border-subtle)" }}>
          {agents.steps.map((step, index) => (
            <li key={step.name} className="p-5" style={{ background: "#080b11" }}>
              <span style={{ ...MONO_LABEL, color: "var(--accent-cyan)" }}>{pad2(index + 1)}</span>
              <h3 className="mt-2 text-base font-bold" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                {step.name}
              </h3>
              <p className="mt-2 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                {step.body}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
