import type { NextConfig } from "next";

// mvp/911-console-live — deployed under the /prism42 path on
// www.thegoatnote.com via Vercel. basePath keeps links portable
// across both `vercel dev` (http://localhost:3042) and production
// (https://www.thegoatnote.com/prism42). Flip PRISM42_BASE_PATH=
// empty for a root-mounted deploy.
const basePath = process.env.PRISM42_BASE_PATH ?? "/prism42";

const nextConfig: NextConfig = {
  basePath: basePath === "" ? undefined : basePath,
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
        source: "/api/chat/completions",
        headers: [
          { key: "Cache-Control", value: "no-store, no-transform" },
          { key: "X-Accel-Buffering", value: "no" },
        ],
      },
      {
        source: "/api/session/:id/stream",
        headers: [
          { key: "Cache-Control", value: "no-store, no-transform" },
          { key: "X-Accel-Buffering", value: "no" },
        ],
      },
    ];
  },
};

export default nextConfig;
