/** @type {import('next').NextConfig} */
const nextConfig = {
  // 将 /api/video/* 请求代理到 FastAPI 后端
  async rewrites() {
    return [
      {
        source: '/api/video/:path*',
        destination: 'http://127.0.0.1:8000/api/video/:path*',
      },
      // pipeline 相关接口也代理到后端
      {
        source: '/pipeline/:path*',
        destination: 'http://127.0.0.1:8000/pipeline/:path*',
      },
      // 其他后端接口
      {
        source: '/api/serve-file',
        destination: 'http://127.0.0.1:8000/api/serve-file',
      },
      {
        source: '/api/video-info',
        destination: 'http://127.0.0.1:8000/api/video-info',
      },
      {
        source: '/api/stream-video',
        destination: 'http://127.0.0.1:8000/api/stream-video',
      },
    ];
  },

  // 图片域名白名单（用于封面图等跨域资源）
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '**',
      },
    ],
  },

  // 开发环境下不强制输出静态页面
  output: undefined,
};

module.exports = nextConfig;
