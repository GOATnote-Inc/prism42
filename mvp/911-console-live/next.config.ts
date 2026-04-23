import type { NextConfig } from "next";

// mvp/911-console-live — deployed under the /prism42 path on
// www.thegoatnote.com. We deliberately do NOT set `basePath` here:
//
//   1. Vercel Microfrontends explicitly does not support Next.js
//      apps that use basePath
//      (https://vercel.com/docs/microfrontends/quickstart).
//   2. For the simpler rewrite-based multi-project pattern
//      (main project rewrites /prism42/:path* → this deployment),
//      the rewrite preserves the prefix, so Next just sees the
//      full /prism42/* URL. Our file tree (app/prism42/page.tsx,
//      app/prism42/api/*) is authored so paths match naturally
//      without a framework-level prefix.
//
// Result: the URL story is the same across local dev
// (http://localhost:3042/prism42) and production
// (https://www.thegoatnote.com/prism42) — every route is authored
// with the /prism42 prefix.

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    // Server actions rolled into the platform default; kept explicit
    // so future Vercel runtime bumps don't silently flip behavior.
    serverActions: {
      bodySizeLimit: "1mb",
    },
  },
  // ElevenLabs posts JSON messages; occasional transcripts exceed
  // the Next.js default. Response bodies are SSE so no size cap on
  // our side.
  async headers() {
    return [
      {
        source: "/prism42/api/chat/completions",
        headers: [
          { key: "Cache-Control", value: "no-store, no-transform" },
          { key: "X-Accel-Buffering", value: "no" },
        ],
      },
      {
        source: "/prism42/api/session/:id/stream",
        headers: [
          { key: "Cache-Control", value: "no-store, no-transform" },
          { key: "X-Accel-Buffering", value: "no" },
        ],
      },
    ];
  },
};

export default nextConfig;
