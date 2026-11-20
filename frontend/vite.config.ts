import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target = env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

  return {
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      watch: { ignored: ['**/*.tmpdir/**', '**/*.tmp'] },
      proxy: {
        '/api': { target, changeOrigin: true },
      },
    },
    preview: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      watch: { ignored: ['**/*.tmpdir/**', '**/*.tmp'] },
      proxy: {
        '/api': { target, changeOrigin: true },
      },
    },
  };
});
