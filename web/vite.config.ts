import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const backend = process.env.BACKEND_URL ?? 'http://127.0.0.1:43651';

export default defineConfig({
  plugins: [
    sveltekit({
      // Single-page app: the backend serves index.html for every app route.
      adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', strict: false }),
      version: { name: process.env.APP_VERSION ?? 'dev' }
    })
  ],
  server: {
    proxy: {
      '/api': backend,
      '/auth': backend,
      '/avatar': backend,
      '/healthz': backend
    }
  }
});
