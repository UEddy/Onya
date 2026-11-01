import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      { source: "/app", destination: "/app/watchlist", permanent: true },
      { source: "/watchlist", destination: "/app/watchlist", permanent: true },
      { source: "/agent", destination: "/app/agent", permanent: true },
      {
        source: "/company/:ticker",
        destination: "/app/company/:ticker",
        permanent: true,
      },
    ];
  },
  cacheComponents: true,
  partialPrefetching: true,
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
