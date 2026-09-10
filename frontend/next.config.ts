import type { NextConfig } from "next";

const backend = process.env.API_PROXY_TARGET || "http://localhost:10000";

const nextConfig: NextConfig = {
  allowedDevOrigins: [".monkeycode-ai.live"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
