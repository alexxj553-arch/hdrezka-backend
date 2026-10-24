import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('package metadata declares expected API scripts', async () => {
  const pkg = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(pkg.name, 'hdrezka-backend');
  assert.ok(pkg.scripts.start);
  assert.ok(pkg.scripts.test);
});

test('mirror management routes are exposed by Node API', async () => {
  const source = await readFile(new URL('../src/server.js', import.meta.url), 'utf8');
  for (const route of ['/api/mirrors', '/api/mirrors/check', '/api/mirrors/add', '/api/mirrors/select']) {
    assert.ok(source.includes(route), `missing route ${route}`);
  }
});

test('Python bridge includes parallel mirror checks and HTTPS allowlist', async () => {
  const source = await readFile(new URL('../python_bridge/app.py', import.meta.url), 'utf8');
  assert.ok(source.includes('ThreadPoolExecutor'));
  assert.ok(source.includes('HDREZKA_ALLOWED_HOSTS'));
  assert.ok(source.includes('https'));
});
