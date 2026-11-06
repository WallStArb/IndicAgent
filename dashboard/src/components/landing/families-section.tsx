import { familiesCopy, familyList, kinds, retiredCopy, retiredReasons } from "@/lib/copy/landing";
import { MONO_LABEL, SectionHeading, pad2 } from "./section-heading";

/** The families of ideas by kind, each with its stated reason to exist, then the retired-ideas ledger. */
export function FamiliesSection() {
  return (
    <section className="px-6 py-12 border-t" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="max-w-7xl mx-auto">
        <SectionHeading eyebrow={familiesCopy.eyebrow} title={familiesCopy.title} intro={familiesCopy.intro} accent="var(--accent-amber)" />

        <div className="grid gap-10">
          {kinds.map((kind) => (
            <div key={kind.id}>
              <div className="flex items-baseline gap-4 mb-3">
                <h3 className="text-sm font-semibold" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  {kind.title}
                </h3>
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {kind.blurb}
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {familyList
                  .filter((family) => family.kind === kind.id)
                  .map((family) => (
                    <article key={family.name} className="flex flex-col gap-3 border p-5" style={{ background: "#080b11", borderColor: "var(--border-subtle)" }}>
                      <div>
                        <h4 className="text-base font-bold leading-tight" style={{ fontFamily: "var(--font-display)", color: "var(--accent-cyan)" }}>
                          {family.name}
                        </h4>
                        <p className="mt-1 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                          {family.idea}
                        </p>
                      </div>
                      <dl className="grid gap-2 text-[0.7rem] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                        <div>
                          <dt style={MONO_LABEL}>{familiesCopy.whyLabel}</dt>
                          <dd>{family.mechanism}</dd>
                        </div>
                        <div>
                          <dt style={MONO_LABEL}>{familiesCopy.counterpartyLabel}</dt>
                          <dd>{family.counterparty}</dd>
                        </div>
                        <div>
                          <dt style={MONO_LABEL}>{familiesCopy.retireLabel}</dt>
                          <dd>{family.retireIf}</dd>
                        </div>
                      </dl>
                      <p className="mt-auto pt-2 border-t text-[0.62rem]" style={{ borderColor: "var(--border-subtle)", color: "var(--text-muted)", fontFamily: "var(--font-jetbrains)" }}>
                        {family.status} · {familiesCopy.restsOn} {family.truths.map(pad2).join(", ")}
                      </p>
                    </article>
                  ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-16">
          <SectionHeading eyebrow={retiredCopy.eyebrow} title={retiredCopy.title} intro={retiredCopy.intro} />
          <ol className="grid gap-x-12 md:grid-cols-2">
            {retiredReasons.map((reason, index) => (
              <li key={reason.title} className="grid grid-cols-[2rem_1fr] gap-x-3 border-t py-4" style={{ borderColor: "var(--border-subtle)" }}>
                <span style={{ ...MONO_LABEL, color: "var(--accent-amber)" }}>{pad2(index + 1)}</span>
                <div>
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                    {reason.title}
                  </p>
                  <p className="mt-1 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                    {reason.lesson}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
