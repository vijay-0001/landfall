import type { NextConfig } from "next";

const root = process.cwd();

const config: NextConfig = {
  output: "standalone",
  // sharp (and its LGPL libvips binaries) is stubbed out via npm overrides; images are never optimised.
  images: { unoptimized: true },
  outputFileTracingRoot: root,
  turbopack: { root },
  poweredByHeader: false,
  reactStrictMode: true,
  // Real backend, same paths as the OpenAPI (base path /api). Used only when an endpoint is un-mocked.
  async rewrites() {
    const target = process.env.API_PROXY_TARGET;
    return target ? [{ source: "/api/:path*", destination: `${target}/api/:path*` }] : [];
  },
};

export default config;
