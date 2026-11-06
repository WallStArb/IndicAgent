import { groups, ideas, truths } from "@/lib/copy/landing";
import { MONO_LABEL, SectionHeading, pad2 } from "./section-heading";

/** The lead principles as cards, then every other principle indexed under its group. */
export function IdeasSection() {
  const leads = truths.filter((t) => t.lead);
  return (
    <section className="px-6 py-12 border-t" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="max-w-7xl mx-auto">
        <SectionHeading eyebrow={ideas.eyebrow} title={ideas.title} intro={ideas.intro} accent="var(--accent-amber)" />

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px" style={{ background: "var(--border-subtle)" }}>
          {leads.map((truth) => (
            <article key={truth.id} className="flex flex-col p-6" style={{ background: "#080b11" }}>
              <span style={{ ...MONO_LABEL, color: "var(--accent-cyan)" }}>{pad2(truth.id)}</span>
              <h3 className="mt-3 text-lg font-bold leading-tight" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                {truth.title}
              </h3>
              <p className="mt-1 text-xs font-medium" style={{ color: "var(--accent-amber)" }}>
                {truth.line}
              </p>
              <p className="mt-3 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                {truth.essay[0]}
              </p>
              <p className="mt-auto pt-4 text-[0.7rem] leading-relaxed" style={{ color: "var(--text-muted)" }}>
                <span className="block" style={MONO_LABEL}>
                  {ideas.exampleLabel}
                </span>
                <span className="mt-1 block">{truth.example}</span>
              </p>
            </article>
          ))}
        </div>

        <h3 className="mt-12 mb-2" style={MONO_LABEL}>
          {ideas.restTitle}
        </h3>
        <div className="grid gap-x-12 gap-y-8 md:grid-cols-2">
          {groups.map((group) => {
            const rest = truths.filter((t) => t.group === group.id && !t.lead);
            return (
              <div key={group.id}>
                <h4 className="text-sm font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  {group.title}
                </h4>
                <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
                  {group.blurb}
                </p>
                <ol className="mt-3">
                  {rest.map((truth) => (
                    <li
                      key={truth.id}
                      className="grid grid-cols-[2rem_1fr] gap-x-3 border-t py-3"
                      style={{ borderColor: "var(--border-subtle)" }}
                    >
                      <span style={{ ...MONO_LABEL, color: "var(--accent-cyan)" }}>{pad2(truth.id)}</span>
                      <div>
                        <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                          {truth.title}
                        </p>
                        <p className="mt-0.5 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                          {truth.line}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
