// dashboard/src/components/signals/signals-page.tsx
"use client";

import { useState, useCallback } from "react";
import { CommandStrip } from "./command-strip";
import { AttributionRow } from "./attribution-row";
import { ClusterStrip } from "./cluster-strip";
import { FilterBar, FilterState, defaultFilters } from "./filter-bar";
import { SignalLedger } from "./signal-ledger";
import { LiveSignalCards } from "./live-signal-cards";
import { EdgeIntelligenceStrip } from "./edge-intelligence-strip";

export function SignalsPage() {
  const [filters, setFilters] = useState<FilterState>(defaultFilters);

  const handleFilterChange = useCallback((next: Partial<FilterState>) => {
    setFilters((prev) => ({ ...prev, ...next }));
  }, []);

  const handleHeatMapClick = useCallback((setup: string, regime: number) => {
    setFilters((prev) => ({
      ...prev,
      setup_plugin: [setup],
      regime: [regime],
    }));
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-[var(--bg-base)]">
      <div className="sticky top-0 z-40 border-b border-[var(--border-subtle)]"
           style={{ background: "rgba(10, 14, 20, 0.95)" }}>
        <CommandStrip />
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[1600px] mx-auto px-4 py-4 flex flex-col gap-4">
          <LiveSignalCards />
          <EdgeIntelligenceStrip onHeatMapCellClick={handleHeatMapClick} />
          <AttributionRow onSetupClick={(setup) => handleFilterChange({ setup_plugin: [setup] })}
                          onAssetClassClick={(ac) => handleFilterChange({ asset_class: [ac] })} />
          <ClusterStrip onClusterClick={(symbols) => handleFilterChange({ symbol: symbols })} />
          <FilterBar filters={filters} onChange={handleFilterChange} />
          <SignalLedger filters={filters} />
        </div>
      </div>
    </div>
  );
}
