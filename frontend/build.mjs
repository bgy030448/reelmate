import { build } from 'esbuild';
import { copyFile, mkdir } from 'node:fs/promises';

await mkdir('dist', { recursive: true });
await build({
  entryPoints: { app: 'src/main.jsx' },
  outdir: 'dist',
  bundle: true,
  minify: true,
  jsx: 'automatic',
  target: ['es2022'],
  legalComments: 'linked',
  define: { 'process.env.NODE_ENV': '"production"' },
});
await copyFile('index.html', 'dist/index.html');
