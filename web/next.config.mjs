/** @type {import('next').NextConfig} */
const nextConfig = {
  // The portfolio API lives on localhost:8765 (Docker container)
  // Rewrite /api/* → localhost:8765/* so the browser never needs to hit a
  // cross-origin URL in production builds (dev uses CORS + direct fetch).
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8765/:path*",
      },
    ];
  },
};

export default nextConfig;
