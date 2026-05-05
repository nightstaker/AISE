// Integration test: TypeScript compiles successfully and all expected
// output files are present in the dist/ directory.

import { describe, it, expect } from 'vitest';
import { execSync } from 'child_process';
import { existsSync, readFileSync } from 'fs';

describe('typescript_compiles', () => {
  it('tsc compiles successfully with exit code 0', () => {
    const output = execSync('npx tsc', { encoding: 'utf-8' });
    expect(output).toBeDefined();
  });

  it('compiled files exist in dist/', () => {
    const files = [
      'dist/index.js',
      'dist/server/app_builder.js',
      'dist/server/router.js',
      'dist/routes/health_handler.js',
      'dist/routes/echo_handler.js',
      'dist/middleware/error_handler.js',
    ];
    files.forEach((f) => expect(existsSync(f)).toBe(true));
  });

  it('compiled files have correct module structure', () => {
    const entry = 'dist/index.js';
    expect(existsSync(entry)).toBe(true);
    const content = readFileSync(entry, 'utf-8');
    expect(content).toContain('createApp');
    expect(content).toContain('app.listen');
  });
});
