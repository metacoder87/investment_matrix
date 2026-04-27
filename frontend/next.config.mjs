/** @type {import('next').NextConfig} */
const nextConfig = {
    output: "standalone",
    skipTrailingSlashRedirect: true,
    async rewrites() {
        const internalApiUrl = process.env.INTERNAL_API_URL || "http://localhost:8000/api";
        const normalizedApiUrl = internalApiUrl.replace(/\/+$/, "");
        return [
            {
                source: "/api/:path*",
                destination: `${normalizedApiUrl}/:path*`,
            },
        ];
    },
};

export default nextConfig;
