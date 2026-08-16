import test from 'node:test';
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

async function tsFiles(root: string): Promise<string[]> {
  const result: string[] = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const full = path.join(root, entry.name);
    if (entry.isDirectory()) result.push(...await tsFiles(full));
    else if (entry.isFile() && entry.name.endsWith('.ts')) result.push(full);
  }
  return result;
}

test('runtime TypeScript uses emitted .js specifiers for relative imports', async () => {
  const files = [...await tsFiles('api'), ...await tsFiles('lib')];
  const offenders: string[] = [];
  for (const file of files) {
    const source = await readFile(file, 'utf8');
    if (/from\s+['"]\.\.?\/[^'"]+\.ts['"]/.test(source)) offenders.push(file);
  }
  assert.deepEqual(offenders, []);
});
