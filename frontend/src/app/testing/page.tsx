"use client";

import { Suspense } from "react";
import { TestingLab } from "@/components/testing/TestingLab";
import { Loading } from "@/components/ui";

/** The skill and version are read from the address (so the library can link straight to one), which a statically built page may only do inside a Suspense boundary. */
export default function TestingPage() {
  return (
    <Suspense fallback={<Loading what="the Testing Lab" />}>
      <TestingLab />
    </Suspense>
  );
}
