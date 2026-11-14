import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Linux image packaging needs standalone; ordinary Windows builds do not need
  // the symlink privileges required by pnpm's standalone output tracing.
  output: process.env.NEXT_OUTPUT_STANDALONE === 'true' ? 'standalone' : undefined,
};

export default nextConfig;
