import test from 'node:test';
import assert from 'node:assert/strict';
import { authorizeBacklinkOS, loadFeishuConfig } from '../lib/feishu/config.ts';

test('loadFeishuConfig requires all five Feishu variables', () => {
  assert.throws(
    () => loadFeishuConfig({ FEISHU_APP_ID: 'cli_x' } as NodeJS.ProcessEnv),
    /Missing required environment variable/
  );
});

test('loadFeishuConfig returns the five configured values', () => {
  const result = loadFeishuConfig({
    FEISHU_APP_ID: 'cli_x',
    FEISHU_APP_SECRET: 'secret',
    FEISHU_BITABLE_APP_TOKEN: 'base_x',
    FEISHU_OPPORTUNITY_TABLE_ID: 'tbl_main',
    FEISHU_EVIDENCE_TABLE_ID: 'tbl_evidence',
  } as NodeJS.ProcessEnv);

  assert.deepEqual(result, {
    appId: 'cli_x',
    appSecret: 'secret',
    appToken: 'base_x',
    opportunityTableId: 'tbl_main',
    evidenceTableId: 'tbl_evidence',
  });
});

test('authorizeBacklinkOS accepts only the exact X-BacklinkOS-Key', () => {
  const ok = new Request('https://example.test', {
    headers: { 'X-BacklinkOS-Key': 'secret' },
  });
  const bad = new Request('https://example.test', {
    headers: { 'X-BacklinkOS-Key': 'wrong' },
  });

  assert.equal(authorizeBacklinkOS(ok, 'secret'), true);
  assert.equal(authorizeBacklinkOS(bad, 'secret'), false);
  assert.equal(authorizeBacklinkOS(ok, ''), false);
});
