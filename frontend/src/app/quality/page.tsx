"use client";

import { Suspense } from "react";
import { QualityPage } from "@/components/quality/QualityPage";
import { Loading } from "@/components/ui";

/** The skill and version are read from the address (so the library can link straight to one), which a statically built page may only do inside a Suspense boundary. */
export default function QualityRoute() {
  return (
    <Suspense fallback={<Loading what="the Quality Report" />}>
      <QualityPage />
    </Suspense>
  );
}
