import path from "node:path";
import { config as loadDotenv } from "dotenv";
import type { NextConfig } from "next";

// One `.env` at the repo root configures backend and frontend alike. Variables already set
// in the environment win over the file.
loadDotenv({ path: path.resolve(process.cwd(), "..", ".env"), quiet: true });

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // Don't let `next dev` write an AGENTS.md into the repo; CLAUDE.md is the agent guide.
  agentRules: false,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
    // Defaults to the backend's API_TOKEN so a single setting serves both sides.
    NEXT_PUBLIC_API_TOKEN: process.env.NEXT_PUBLIC_API_TOKEN || process.env.API_TOKEN || "",
  },
  async redirects() {
    return [{ source: "/", destination: "/inbox", permanent: false }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
