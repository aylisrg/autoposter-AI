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
};

export default nextConfig;
