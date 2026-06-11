/** @type {import('next').NextConfig} */
const nextConfig = {
  transpilePackages: ['react-datepicker'],
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
    return [
      {
        source: '/api/video/:path*',
        destination: `${backendUrl}/api/video/:path*`,
      },
      {
        source: '/pipeline/:path*',
        destination: `${backendUrl}/pipeline/:path*`,
      },
      {
        source: '/api/hot/:path*',
        destination: `${backendUrl}/api/hot/:path*`,
      },
      {
        source: '/api/serve-file',
        destination: `${backendUrl}/api/serve-file`,
      },
      {
        source: '/api/video-info',
        destination: `${backendUrl}/api/video-info`,
      },
      {
        source: '/api/stream-video',
        destination: `${backendUrl}/api/stream-video`,
      },
    ];
  },

  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '**',
      },
    ],
  },

  output: undefined,
};

module.exports = nextConfig;
