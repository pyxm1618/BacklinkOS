import test from 'node:test';
import assert from 'node:assert/strict';
import { persistPlacement } from '../lib/feishu/persistence.ts';
import type { FeishuClient, FeishuRecord } from '../lib/feishu/types.ts';

const config = {
  appId: 'cli_x', appSecret: 'secret', appToken: 'base_x', opportunityTableId: 'tbl_main', evidenceTableId: 'tbl_ev',
};

function request() {
  return {
    main_record: {
      placement_key: 'example.com|Profile|https://example.com/profile/edit',
      URL: 'https://example.com/profile/edit',
      DR: 63,
      评级: 'A',
      状态: '已验证',
    },
    evidence_records: [{
      evidence_key: 'example|dr|ahrefs',
      placement_key: 'example.com|Profile|https://example.com/profile/edit',
      evidence_type: 'DR',
      canonical_domain: 'example.com',
      source: 'Ahrefs',
      status: 'CONFIRMED',
      value_number: 63,
      checked_at: '2026-08-16T01:00:00Z',
    }],
  } as any;
}

function fakeClient(options?: { main?: FeishuRecord[]; evidence?: FeishuRecord[]; evidenceCreateFails?: boolean }) {
  const created: Array<{tableId:string; fields:Record<string,unknown>}> = [];
  const updated: Array<{tableId:string; recordId:string; fields:Record<string,unknown>}> = [];
  const client: FeishuClient = {
    getTenantAccessToken: async () => 'x',
    listFields: async () => [],
    hasAnyRecords: async () => false,
    createField: async () => { throw new Error('unused'); },
    updateField: async () => { throw new Error('unused'); },
    searchRecords: async (tableId) => tableId === 'tbl_main' ? (options?.main ?? []) : (options?.evidence ?? []),
    createRecord: async (tableId, fields) => {
      if (tableId === 'tbl_ev' && options?.evidenceCreateFails) throw new Error('evidence failed');
      created.push({ tableId, fields });
      return { record_id: `${tableId}-new`, fields };
    },
    updateRecord: async (tableId, recordId, fields) => {
      updated.push({ tableId, recordId, fields });
      return { record_id: recordId, fields };
    },
  };
  return { client, created, updated };
}

test('no main match creates one main record and evidence record', async () => {
  const { client, created } = fakeClient();
  const result = await persistPlacement(client, config, request());
  assert.equal(result.success, true);
  assert.equal(result.main.action, 'created');
  assert.equal(result.evidence[0].action, 'created');
  assert.equal(created.length, 2);
});

test('one main match updates existing main record', async () => {
  const main = [{ record_id: 'rec_main', fields: { placement_key: request().main_record.placement_key } }];
  const ev = [{ record_id: 'rec_ev', fields: { evidence_key: request().evidence_records[0].evidence_key } }];
  const { client, updated } = fakeClient({ main, evidence: ev });
  const result = await persistPlacement(client, config, request());
  assert.equal(result.main.action, 'updated');
  assert.equal(result.evidence[0].action, 'updated');
  assert.deepEqual(updated.map((x) => x.recordId), ['rec_main','rec_ev']);
});

test('multiple main matches returns conflict and skips evidence writes', async () => {
  const main = [
    { record_id: 'r1', fields: {} },
    { record_id: 'r2', fields: {} },
  ];
  const { client, created, updated } = fakeClient({ main });
  const result = await persistPlacement(client, config, request());
  assert.equal(result.success, false);
  assert.equal(result.main.action, 'conflict');
  assert.equal(result.evidence.length, 0);
  assert.equal(created.length + updated.length, 0);
});

test('evidence failure is explicit and overall success is false', async () => {
  const { client } = fakeClient({ evidenceCreateFails: true });
  const result = await persistPlacement(client, config, request());
  assert.equal(result.main.action, 'created');
  assert.equal(result.evidence[0].action, 'failed');
  assert.equal(result.success, false);
});

test('search filters use exact key fields', async () => {
  const filters: unknown[] = [];
  const { client } = fakeClient();
  client.searchRecords = async (_tableId, body) => { filters.push(body); return []; };
  await persistPlacement(client, config, request());
  assert.equal((filters[0] as any).filter.conditions[0].field_name, 'placement_key');
  assert.equal((filters[0] as any).filter.conditions[0].operator, 'is');
  assert.equal((filters[1] as any).filter.conditions[0].field_name, 'evidence_key');
});
