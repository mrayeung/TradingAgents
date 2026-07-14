/** @type {import('next').NextConfig} */
const nextConfig = {
  // Route specific API prefixes to the Python desk-server (localhost:8765).
  // Only paths in this list are proxied — everything else (e.g. /api/institutions/)
  // is handled by Next.js route files in app/api/.
  async rewrites() {
    const DESK = "http://localhost:8765";

    // Every top-level path served by desk_server/app.py.
    // Add new entries here if you add routes to app.py.
    const deskPrefixes = [
      "health",
      "capabilities",
      "journal",
      "reports",
      "search",
      "prices",
      "openrouter",
      "test",
      "test_fred",
      "runs",
      "portfolio",
      "options",
    ];

    // ":path*" matches zero-or-more segments, covering both
    // bare paths (/api/health) and sub-paths (/api/runs/123/events).
    return deskPrefixes.map((prefix) => ({
      source: `/api/${prefix}/:path*`,
      destination: `${DESK}/${prefix}/:path*`,
    }));
  },
};

export default nextConfig;
