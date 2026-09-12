import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // The repo root holds the Python project; the web app is a subdirectory.
  turbopack: { root: path.resolve(__dirname) },
  reactStrictMode: true,
};

export default nextConfig;
