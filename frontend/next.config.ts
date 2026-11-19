import path from "node:path";
import type { NextConfig } from "next";

// Two build-time switches for the hosted version (docs/hosting.md). Without them nothing changes:
//   SKILLFORGE_STANDALONE=1     a self-contained server folder, for the Docker image
//   SKILLFORGE_PROXY_API=<url>  send /api/* to the Python API at that address, so the page and the API share one public address
const proxyTarget = (process.env.SKILLFORGE_PROXY_API ?? "").replace(/\/+$/, "");

const config: NextConfig = {
  reactStrictMode: true,
  // Trace files from this folder, not from the Git root's parents: a stray package-lock.json higher up must not matter.
  outputFileTracingRoot: path.resolve(process.cwd()),
  ...(process.env.SKILLFORGE_STANDALONE === "1" ? { output: "standalone" as const } : {}),
  async rewrites() {
    return proxyTarget ? [{ source: "/api/:path*", destination: `${proxyTarget}/api/:path*` }] : [];
  },
  // Locally the browser talks straight to the API (NEXT_PUBLIC_API_URL), which allows this UI's origin.
  // node_modules and .next are junctions to C:\dev (see README.md), so the bundler must be webpack, not Turbopack:
  // Turbopack refuses a link that points outside the project. The scripts in package.json already pass --webpack.
};

export default config;
