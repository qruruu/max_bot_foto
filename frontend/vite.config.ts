import { randomUUID } from 'node:crypto';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({command, mode}) => {
  // One identifier is embedded in the client and emitted with the same build.
  const version = command === 'build' ? randomUUID() : 'development';
  return {
    build: mode === 'citizens' ? {outDir: 'dist-citizens', rollupOptions: {input: 'citizens.html'}} :
      {rollupOptions: {input: {main: 'index.html', citizens: 'citizens.html'}}},
    define: { __APP_VERSION__: JSON.stringify(version) },
    plugins: [react(), {
      name: 'app-version',
      apply: 'build',
      generateBundle() {
        this.emitFile({type: 'asset', fileName: 'version.json', source: JSON.stringify({version})});
      },
    }],
    server: { proxy: { '/api': 'http://127.0.0.1:8000', '^/org/[^/]+/api/': 'http://127.0.0.1:8000' } },
  };
});
