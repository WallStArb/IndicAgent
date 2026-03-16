// dashboard/src/app/signals/page.tsx
"use client";

import { Suspense } from "react";
import { SignalsPage } from "@/components/signals/signals-page";

export default function Signals() {
  return (
    <Suspense>
      <SignalsPage />
    </Suspense>
  );
}
