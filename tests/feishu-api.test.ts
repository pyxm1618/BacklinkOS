import test from 'node:test';
import assert from 'node:assert/strict';
import { createSetupHandler } from '../api/feishu/setup.ts';
import { createPersistHandler } from '../api/feishu/persist.ts';

const env = {
  FEISHU_APP_ID: 'cli_x',
  FEISHU_APP_SECRET: 'secret',
  FEISHU_BITABLE_APP_TOKEN: 'base_x',
  FEISHU_OPPORTUNITY_TABLE_ID: 'tbl_main',
  FEISHU_EVIDENCE_TABLE_ID: 'tbl_ev',
  BACKLINKOS_API_KEY: 'api-key',
} as NodeJS.ProcessEnv;

function req(url: string, body: unknown, key='api-key') {
  return new Request(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'X-BacklinkOS-Key': key },
    body: JSON.stringify(body),
  });
}

test('setup refuses when server API key is not configured', async () => {
  const handler = createSetupHandler({ env: { ...env, BACKLINKOS_API_KEY: '' } as NodeJS.ProcessEnv });
  const response = await handler(req('https://x/api/feishu/setup', { apply:false }));
  assert.equal(response.status, 503);
});

test('setup rejects wrong API key before Feishu access', async () => {
  let called = false;
  const handler = createSetupHandler({
    env,
    clientFactory: () => { called = true; return {} as any; },
  });
  const response = await handler(req('https://x/api/feishu/setup', { apply:false }, 'wrong'));
  assert.equal(response.status, 401);
  assert.equal(called, false);
});

test('setup dry-run returns both table plans', async () => {
  const handler = createSetupHandler({
    env,
    clientFactory: () => ({} as any),
    setupTableImpl: async (_client, tableId, kind, apply) => ({ tableId, kind, apply, actions:[], conflicts:[], fields:[] }),
  });
  const response = await handler(req('https://x/api/feishu/setup', { apply:false }));
  assert.equal(response.status, 200);
  const json = await response.json() as any;
  assert.equal(json.success, true);
  assert.equal(json.tables.length, 2);
  assert.equal(json.tables[0].apply, false);
});

test('setup returns 409 on schema conflict', async () => {
  const handler = createSetupHandler({
    env,
    clientFactory: () => ({} as any),
    setupTableImpl: async (_client, tableId, kind, apply) => ({ tableId, kind, apply, actions:[], conflicts:['bad type'], fields:[] }),
  });
  const response = await handler(req('https://x/api/feishu/setup', { apply:false }));
  assert.equal(response.status, 409);
});

test('persist rejects malformed JSON input with 400', async () => {
  const handler = createPersistHandler({ env, clientFactory: () => ({} as any) });
  const request = new Request('https://x/api/feishu/persist', {
    method:'POST', headers:{'content-type':'application/json','X-BacklinkOS-Key':'api-key'}, body:'{bad',
  });
  const response = await handler(request);
  assert.equal(response.status, 400);
});

test('persist returns persistence result without credentials', async () => {
  const handler = createPersistHandler({
    env,
    clientFactory: () => ({} as any),
    validateImpl: (input:any) => input,
    persistPlacementImpl: async () => ({ success:true, main:{action:'created',record_id:'rec1'}, evidence:[] }),
  });
  const response = await handler(req('https://x/api/feishu/persist', { main_record:{placement_key:'k',URL:'u'}, evidence_records:[] }));
  assert.equal(response.status, 200);
  const text = await response.text();
  assert.equal(text.includes('secret'), false);
  assert.equal(text.includes('api-key'), false);
  assert.match(text, /rec1/);
});
