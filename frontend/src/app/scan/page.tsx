"use client";

import { Suspense } from "react";
import { ScanPage } from "@/components/scan/ScanPage";
import { Loading } from "@/components/ui";

/** The kind, the entry and its version are read from the address (so the library can link straight to one), which a statically built page may only do inside a Suspense boundary. */
export default function BehaviourScanPage() {
  return (
    <Suspense fallback={<Loading what="the Behaviour Scan" />}>
      <ScanPage />
    </Suspense>
  );
}
