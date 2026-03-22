import { defineConfig } from 'tsup';
import { readFileSync, writeFileSync, readdirSync } from 'fs';
import { join } from 'path';

export default defineConfig({
  entry: ['src/index.ts'],
  format: ['cjs', 'esm'],
  dts: true,
  clean: true,
  platform: 'node',
  external: [
    '@memgrafter/flatmachines',
  ],
  async onSuccess() {
    // esbuild strips node: protocol from dynamic require() calls in CJS/ESM output.
    // node:sqlite only works with the prefix, so restore it post-build.
    const distDir = join(import.meta.dirname, 'dist');
    for (const file of readdirSync(distDir)) {
      if (!file.endsWith('.js') && !file.endsWith('.mjs')) continue;
      const path = join(distDir, file);
      let code = readFileSync(path, 'utf8');
      const patched = code
        .replace(/require\("sqlite"\)/g, 'require("node:sqlite")')
        .replace(/__require\("sqlite"\)/g, '__require("node:sqlite")');
      if (patched !== code) writeFileSync(path, patched);
    }
  },
});
