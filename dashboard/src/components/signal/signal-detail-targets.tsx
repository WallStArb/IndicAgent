"use client";

import type { SignalData } from "@/lib/types";
import { Grid, KV } from "../ui/primitives";
import { fmtPrice, fmtNum } from "@/lib/format";

interface SignalDetailTargetsProps {
  signal: SignalData;
}

/**
 * Signal targets display: T1, T2, T3 with risk-reward ratios.
 * Shows structural vs ATR fallback framing method.
 */
export function SignalDetailTargets({ signal }: SignalDetailTargetsProps) {
  const t1 = signal.profit_target ?? null;
  const t2 = signal.profit_target_2 ?? null;
  const t3 = signal.profit_target_3 ?? null;
  const rr1 = signal.rr_t1 ?? signal.risk_reward_ratio ?? 0;
  const rr2 = signal.rr_t2 ?? 0;
  const rr3 = signal.rr_t3 ?? 0;
  const isStructural = signal.framing_method === "structural";
  const labels = signal.target_labels ?? [];

  if (t1 === null) return null;

  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-0.5">
        Targets {isStructural ? <span className="text-[var(--green)] opacity-70">structural</span> : <span className="opacity-50">ATR fallback</span>}
      </span>
      <Grid>
        <KV
          label={`T1${labels[0] ? ` · ${labels[0].split(" ")[0]}` : ""}`}
          value={`${fmtPrice(t1)}${rr1 > 0 ? `  ${fmtNum(rr1, 1)}R` : ""}`}
        />
        {t2 !== null && (
          <KV
            label={`T2${labels[1] ? ` · ${labels[1].split(" ")[0]}` : ""}`}
            value={`${fmtPrice(t2)}${rr2 > 0 ? `  ${fmtNum(rr2, 1)}R` : ""}`}
          />
        )}
        {t3 !== null && isStructural && (
          <KV
            label={`T3${labels[2] ? ` · ${labels[2].split(" ")[0]}` : ""}`}
            value={`${fmtPrice(t3)}${rr3 > 0 ? `  ${fmtNum(rr3, 1)}R` : ""}`}
          />
        )}
      </Grid>
    </div>
  );
}
