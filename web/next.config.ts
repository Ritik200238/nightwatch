import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  // The repo root holds the Python project; the web app is a subdirectory.
  turbopack: { root: path.resolve(__dirname) },
  reactStrictMode: true,
  // Self-contained server bundle for the container image (node server.js).
  output: "standalone",
  // The QA browser opens the desk via 127.0.0.1; without this, dev-mode hydration is blocked.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
