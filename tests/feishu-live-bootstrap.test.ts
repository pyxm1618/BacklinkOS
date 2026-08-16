import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { createBootstrapHandler } from '../api/feishu/bootstrap.ts';

const KEY = 'test-bootstrap-secret';
const NOW_MS = 1_786_846_700_000;
const TS = Math.floor(NOW_MS / 1000);

function signature(action: string, ts = TS) {
  return createHmac('sha256', KEY).update(`${action}:${ts}`).digest('hex');
}

function request(action: string, sig = signature(action), ts = TS) {
  return new Request(`https://example.test/api/feishu/bootstrap?action=${encodeURIComponent(action)}&ts=${ts}&sig=${sig}`);
}

test('bootstrap does not import sibling api entrypoints that are absent from a Vercel function bundle', async () => {
  const source = await readFile('api/feishu/bootstrap.ts', 'utf8');
  assert.doesNotMatch(source, /from ['"]\.\/(setup|persist)\.ts['"]/);
});

test('bootstrap rejects invalid signatures before invoking Feishu handlers', async () => {
  let called = false;
  const handler = createBootstrapHandler({
    env: { BACKLINKOS_API_KEY: KEY },
    now: () => NOW_MS,
    setupHandler: async () => { called = true; return Response.json({ ok: true }); },
    persistHandler: async () => { called = true; return Response.json({ ok: true }); },
  });
  const response = await handler(request('dry-run', '0'.repeat(64)));
  assert.equal(response.status, 401);
  assert.equal(called, false);
});

test('bootstrap rejects expired signatures', async () => {
  const oldTs = TS - 301;
  const handler = createBootstrapHandler({ env: { BACKLINKOS_API_KEY: KEY }, now: () => NOW_MS });
  const response = await handler(request('dry-run', signature('dry-run', oldTs), oldTs));
  assert.equal(response.status, 401);
});

test('dry-run forwards a protected setup request with apply=false', async () => {
  let seenHeader = '';
  let seenBody: unknown;
  const handler = createBootstrapHandler({
    env: { BACKLINKOS_API_KEY: KEY },
    now: () => NOW_MS,
    setupHandler: async (req) => {
      seenHeader = req.headers.get('x-backlinkos-key') ?? '';
      seenBody = await req.json();
      return Response.json({ success: true, tables: [] });
    },
  });
  const response = await handler(request('dry-run'));
  assert.equal(response.status, 200);
  assert.equal(seenHeader, KEY);
  assert.deepEqual(seenBody, { apply: false });
});

test('apply forwards a protected setup request with apply=true', async () => {
  let seenBody: unknown;
  const handler = createBootstrapHandler({
    env: { BACKLINKOS_API_KEY: KEY },
    now: () => NOW_MS,
    setupHandler: async (req) => {
      seenBody = await req.json();
      return Response.json({ success: true });
    },
  });
  const response = await handler(request('apply'));
  assert.equal(response.status, 200);
  assert.deepEqual(seenBody, { apply: true });
});

test('test-create and test-update forward the same logical placement with a changed status', async () => {
  const payloads: any[] = [];
  const handler = createBootstrapHandler({
    env: { BACKLINKOS_API_KEY: KEY },
    now: () => NOW_MS,
    persistHandler: async (req) => {
      payloads.push(await req.json());
      return Response.json({ success: true });
    },
  });
  assert.equal((await handler(request('test-create'))).status, 200);
  assert.equal((await handler(request('test-update'))).status, 200);
  assert.equal(payloads[0].main_record.placement_key, payloads[1].main_record.placement_key);
  assert.equal(payloads[0].main_record.状态, '未做');
  assert.equal(payloads[1].main_record.状态, '已验证');
  assert.equal(payloads[0].evidence_records[0].evidence_key, payloads[1].evidence_records[0].evidence_key);
});
