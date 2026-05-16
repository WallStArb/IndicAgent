// dashboard/src/components/signals/signals-page.tsx
"use client";

import { useState, useCallback } from "react";
import { DashboardNav } from "@/components/dashboard-nav";
import { CommandStrip } from "./command-strip";
import { AttributionRow } from "./attribution-row";
import { ClusterStrip } from "./cluster-strip";
import { FilterBar, FilterState, defaultFilters } from "./filter-bar";
import { SignalLedger } from "./signal-ledger";

export function SignalsPage() {
  const [filters, setFilters] = useState<FilterState>(defaultFilters);

  const handleFilterChange = useCallback((next: Partial<FilterState>) => {
    setFilters((prev) => ({ ...prev, ...next }));
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-[var(--bg-base)]">
      <DashboardNav />

      {/* Zone 1 — Command Strip (sticky below header) */}
      <div className="sticky top-[41px] z-40 border-b border-[var(--border-subtle)]"
           style={{ background: "rgba(10, 14, 20, 0.95)" }}>
        <CommandStrip />
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[1600px] mx-auto px-4 py-4 flex flex-col gap-4">
          {/* Zone 2 — Attribution Row */}
          <AttributionRow onSetupClick={(setup) => handleFilterChange({ setup_plugin: [setup] })}
                          onAssetClassClick={(ac) => handleFilterChange({ asset_class: [ac] })} />

          {/* Zone 3 — Cluster Strip */}
          <ClusterStrip onClusterClick={(symbols) => handleFilterChange({ symbol: symbols })} />

          {/* Zone 4 — Filter Bar */}
          <FilterBar filters={filters} onChange={handleFilterChange} />

          {/* Zone 5 — Signal Ledger */}
          <SignalLedger filters={filters} />
        </div>
      </div>
    </div>
  );
}
