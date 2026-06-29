/** @type {import('next').NextConfig} */
const nextConfig = {
  // The portfolio API lives on localhost:8765 (Docker container).
  //
  // We use `afterFiles` so Next.js resolves its own route handlers first
  // (e.g. app/api/institutions/[cik]/route.ts).  Only paths that have no
  // matching Next.js route file fall through to the desk-server proxy.
  async rewrites() {
    return {
      afterFiles: [
        {
          source: "/api/:path*",
          destination: "http://localhost:8765/:path*",
        },
      ],
    };
  },
};

export default nextConfig;
