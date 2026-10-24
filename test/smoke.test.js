import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('package metadata declares expected API scripts', async () => {
  const pkg = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(pkg.name, 'hdrezka-backend');
  assert.ok(pkg.scripts.start);
  assert.ok(pkg.scripts.test);
});
