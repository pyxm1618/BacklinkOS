import test from 'node:test';
import assert from 'node:assert/strict';
import { createFeishuClient, FeishuApiError } from '../lib/feishu/client.ts';

const config = {
  appId: 'cli_x',
  appSecret: 'app-secret',
  appToken: 'base_x',
  opportunityTableId: 'tbl_main',
  evidenceTableId: 'tbl_evidence',
};

test('client exchanges app credentials for tenant token', async () => {
  const calls: Array<{url:string; init?:RequestInit}> = [];
  const fetchImpl = async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return new Response(JSON.stringify({ code: 0, tenant_access_token: 'tenant-token', expire: 7200 }), { status: 200 });
  };
  const client = createFeishuClient(config, fetchImpl);
  assert.equal(await client.getTenantAccessToken(), 'tenant-token');
  assert.match(calls[0].url, /auth\/v3\/tenant_access_token\/internal$/);
  assert.match(String(calls[0].init?.body), /cli_x/);
});

test('listFields uses bearer token and returns items', async () => {
  const calls: Array<{url:string; init?:RequestInit}> = [];
  const fetchImpl = async (input: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    if (calls.length === 1) return new Response(JSON.stringify({ code: 0, tenant_access_token: 'tenant-token', expire: 7200 }));
    return new Response(JSON.stringify({ code: 0, data: { items: [{ field_id: 'fld1', field_name: '文本', type: 1, is_primary: true, ui_type: 'Text', property: null }] } }));
  };
  const client = createFeishuClient(config, fetchImpl);
  const fields = await client.listFields('tbl_main');
  assert.equal(fields[0].field_name, '文本');
  const headers = new Headers(calls[1].init?.headers);
  assert.equal(headers.get('authorization'), 'Bearer tenant-token');
});

test('Feishu envelope error is normalized without secret leakage', async () => {
  let count = 0;
  const fetchImpl = async () => {
    count += 1;
    if (count === 1) return new Response(JSON.stringify({ code: 0, tenant_access_token: 'tenant-token', expire: 7200 }));
    return new Response(JSON.stringify({ code: 1254001, msg: 'bad request' }), { status: 200 });
  };
  const client = createFeishuClient(config, fetchImpl);
  await assert.rejects(client.listFields('tbl_main'), (error: unknown) => {
    assert.ok(error instanceof FeishuApiError);
    assert.equal(error.code, 1254001);
    assert.equal(error.message.includes(config.appSecret), false);
    assert.equal(error.message.includes('tenant-token'), false);
    return true;
  });
});

test('malformed provider JSON becomes FeishuApiError', async () => {
  let count = 0;
  const fetchImpl = async () => {
    count += 1;
    if (count === 1) return new Response(JSON.stringify({ code: 0, tenant_access_token: 'tenant-token', expire: 7200 }));
    return new Response('{bad json', { status: 200 });
  };
  const client = createFeishuClient(config, fetchImpl);
  await assert.rejects(client.listFields('tbl_main'), FeishuApiError);
});
