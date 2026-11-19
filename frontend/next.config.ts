import path from "node:path";
import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Trace files from this folder, not from the Git root's parents: a stray package-lock.json higher up must not matter.
  outputFileTracingRoot: path.resolve(process.cwd()),
  // The browser talks straight to the local API (NEXT_PUBLIC_API_URL), which allows this UI's origin.
  // node_modules and .next are junctions to C:\dev (see README.md), so the bundler must be webpack, not Turbopack:
  // Turbopack refuses a link that points outside the project. The scripts in package.json already pass --webpack.
};

export default config;
