#!/usr/bin/env node

// Backward-compatible wrapper: some workflows/prompts reference gsd-tools.js.
// Canonical implementation lives in gsd-tools.cjs (CommonJS) to avoid ESM issues.

const path = require('path');
const { spawnSync } = require('child_process');

const cjsPath = path.join(__dirname, 'gsd-tools.cjs');
const args = process.argv.slice(2);

const result = spawnSync(process.execPath, [cjsPath, ...args], { stdio: 'inherit' });

if (result.error) {
  console.error(result.error.message || String(result.error));
  process.exit(1);
}

if (result.signal) {
  // Mirror the child termination signal if possible.
  try {
    process.kill(process.pid, result.signal);
  } catch {
    process.exit(1);
  }
}

process.exit(typeof result.status === 'number' ? result.status : 0);

