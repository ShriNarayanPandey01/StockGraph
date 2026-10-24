import type { NextConfig } from "next";

const platformUrl = (process.env.MARKETGRAPH_PLATFORM_URL ?? "http://127.0.0.1:8002").replace(/\/$/, "");

const nextConfig: NextConfig = {
  turbopack: { root: process.cwd() },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${platformUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
