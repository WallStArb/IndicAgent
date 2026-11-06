import { edgeSteps } from "@/lib/copy/landing";
import { MONO_LABEL, SectionHeading, pad2 } from "./section-heading";

export function EdgeSteps() {
  return (
    <section className="px-6 py-12 border-t" style={{ borderColor: "var(--border-subtle)", background: "rgba(0,0,0,0.2)" }}>
      <div className="max-w-7xl mx-auto">
        <SectionHeading eyebrow={edgeSteps.eyebrow} title={edgeSteps.title} intro={edgeSteps.intro} />
        <ol>
          {edgeSteps.steps.map((step, index) => (
            <li
              key={step.name}
              className="grid gap-3 border-t py-6 md:grid-cols-[3rem_1fr_1.6fr] md:gap-8"
              style={{ borderColor: "var(--border-subtle)" }}
            >
              <span style={{ ...MONO_LABEL, color: "var(--accent-cyan)" }}>{pad2(index + 1)}</span>
              <div>
                <h3 className="text-base font-bold leading-tight" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  {step.name}
                </h3>
                <p className="mt-1" style={{ ...MONO_LABEL, color: "var(--accent-amber)" }}>
                  {step.term}
                </p>
              </div>
              <div>
                <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {step.body}
                </p>
                {"guards" in step && step.guards && (
                  <ul className="mt-4 grid gap-px sm:grid-cols-3" style={{ background: "var(--border-subtle)" }}>
                    {step.guards.map((guard) => (
                      <li key={guard.name} className="p-4" style={{ background: "#080b11" }}>
                        <p className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
                          {guard.name}
                        </p>
                        <p className="mt-1 text-[0.7rem] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                          {guard.body}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
