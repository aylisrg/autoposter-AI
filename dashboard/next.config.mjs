/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Backend serves /static and /api — proxy /static images through next so
  // <img src="/static/..."> works from the dashboard without CORS hassle.
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8787";
    return [
      {
        source: "/static/:path*",
        destination: `${api}/static/:path*`,
      },
    ];
  },
  // UX overhaul renamed routes. Keep old paths working so bookmarks + deep
  // links don't 404.
  async redirects() {
    return [
      { source: "/review", destination: "/queue?status=pending_review", permanent: false },
      { source: "/targets", destination: "/destinations", permanent: false },
      { source: "/targets/:path*", destination: "/destinations/:path*", permanent: false },
      { source: "/humanizer", destination: "/settings/posting-behavior", permanent: false },
    ];
  },
};

export default nextConfig;
