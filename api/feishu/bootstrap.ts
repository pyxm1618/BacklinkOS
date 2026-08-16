import { createHmac, timingSafeEqual } from 'node:crypto';
import { loadFeishuConfig } from '../../lib/feishu/config.js';
import { createFeishuClient, FeishuApiError } from '../../lib/feishu/client.js';
import { setupTable } from '../../lib/feishu/schema.js';
import { persistPlacement } from '../../lib/feishu/persistence.js';
import { PersistenceValidationError, validatePersistRequest } from '../../lib/feishu/validation.js';

type Handler = (request: Request) => Promise<Response>;

type BootstrapDeps = {
  env?: NodeJS.ProcessEnv;
  now?: () => number;
  setupHandler?: Handler;
  persistHandler?: Handler;
};

const MAX_AGE_SECONDS = 300;
const ACTIONS = new Set(['dry-run', 'apply', 'test-create', 'test-update']);
const TEST_PLACEMENT_KEY = 'example.com|Other|https://example.com/backlinkos-live-persistence-test';
const TEST_EVIDENCE_KEY = `${TEST_PLACEMENT_KEY}|publishability|bootstrap`;

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

function expectedSignature(secret: string, action: string, ts: string): string {
  return createHmac('sha256', secret).update(`${action}:${ts}`).digest('hex');
}

function validSignature(secret: string, action: string, ts: string, supplied: string): boolean {
  if (!/^\d+$/.test(ts) || !/^[a-f0-9]{64}$/i.test(supplied)) return false;
  const expected = expectedSignature(secret, action, ts);
  const a = Buffer.from(expected, 'hex');
  const b = Buffer.from(supplied, 'hex');
  return a.length === b.length && timingSafeEqual(a, b);
}

function internalRequest(url: string, apiKey: string, payload: unknown): Request {
  return new Request(url, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-backlinkos-key': apiKey,
    },
    body: JSON.stringify(payload),
  });
}

function testPayload(status: '未做' | '已验证') {
  return {
    main_record: {
      placement_key: TEST_PLACEMENT_KEY,
      URL: 'https://example.com/backlinkos-live-persistence-test',
      注册登录: '未确认',
      行业: 'BacklinkOS测试',
      外链形式: 'Other',
      链接属性: '未确认',
      免费情况: '未确认',
      域龄: '未确认',
      评级: 'C',
      状态: status,
      已发布外链URL: '',
    },
    evidence_records: [
      {
        evidence_key: TEST_EVIDENCE_KEY,
        placement_key: TEST_PLACEMENT_KEY,
        evidence_type: 'Publishability',
        canonical_domain: 'example.com',
        source: 'BacklinkOS live bootstrap',
        status: 'UNKNOWN',
        value_text: status === '未做' ? 'temporary live create test' : 'temporary live update test',
        notes: 'BacklinkOS live persistence test; safe to delete after verification',
      },
    ],
  };
}

function defaultSetupHandler(env: NodeJS.ProcessEnv): Handler {
  return async (request: Request) => {
    let config;
    try {
      config = loadFeishuConfig(env);
    } catch (error) {
      return json({ success: false, error: error instanceof Error ? error.message : 'Feishu configuration is incomplete' }, 503);
    }

    let apply = false;
    try {
      const payload = await request.json() as { apply?: unknown };
      apply = payload.apply === true;
    } catch {
      return json({ success: false, error: 'Invalid bootstrap setup payload' }, 400);
    }

    const client = createFeishuClient(config);
    try {
      const opportunity = await setupTable(client, config.opportunityTableId, 'opportunity', apply);
      const evidence = await setupTable(client, config.evidenceTableId, 'evidence', apply);
      const tables = [opportunity, evidence];
      const hasConflict = tables.some((table) =>
        table.conflicts.length > 0 ||
        (table.verification_conflicts?.length ?? 0) > 0 ||
        (apply && (table.remaining_actions?.length ?? 0) > 0)
      );
      return json({ success: !hasConflict, apply, tables }, hasConflict ? 409 : 200);
    } catch (error) {
      if (error instanceof FeishuApiError) {
        return json({ success: false, error: error.message, feishu_code: error.code, http_status: error.httpStatus }, 502);
      }
      return json({ success: false, error: error instanceof Error ? error.message : 'Feishu setup failed' }, 500);
    }
  };
}

function defaultPersistHandler(env: NodeJS.ProcessEnv): Handler {
  return async (request: Request) => {
    let config;
    try {
      config = loadFeishuConfig(env);
    } catch (error) {
      return json({ success: false, error: error instanceof Error ? error.message : 'Feishu configuration is incomplete' }, 503);
    }

    let payload: unknown;
    try {
      payload = await request.json();
    } catch {
      return json({ success: false, error: 'Invalid bootstrap persistence payload' }, 400);
    }

    let validated;
    try {
      validated = validatePersistRequest(payload);
    } catch (error) {
      if (error instanceof PersistenceValidationError || error instanceof Error) {
        return json({ success: false, error: error.message }, 400);
      }
      return json({ success: false, error: 'Invalid persistence request' }, 400);
    }

    try {
      const result = await persistPlacement(createFeishuClient(config), config, validated);
      if (result.success) return json(result, 200);
      const hasConflict = result.main.action === 'conflict' || result.evidence.some((item) => item.action === 'conflict');
      return json(result, hasConflict ? 409 : 502);
    } catch (error) {
      if (error instanceof FeishuApiError) {
        return json({ success: false, error: error.message, feishu_code: error.code, http_status: error.httpStatus }, 502);
      }
      return json({ success: false, error: error instanceof Error ? error.message : 'Feishu persistence failed' }, 500);
    }
  };
}

export function createBootstrapHandler(deps: BootstrapDeps = {}) {
  return async function GET(request: Request): Promise<Response> {
    const env = deps.env ?? process.env;
    const apiKey = env.BACKLINKOS_API_KEY?.trim() ?? '';
    if (!apiKey) return json({ success: false, error: 'BacklinkOS API key is not configured' }, 503);

    const url = new URL(request.url);
    const action = url.searchParams.get('action') ?? '';
    const ts = url.searchParams.get('ts') ?? '';
    const sig = url.searchParams.get('sig') ?? '';

    if (!ACTIONS.has(action)) return json({ success: false, error: 'Unsupported bootstrap action' }, 400);

    const tsNumber = Number(ts);
    const nowSeconds = Math.floor((deps.now?.() ?? Date.now()) / 1000);
    if (!Number.isInteger(tsNumber) || Math.abs(nowSeconds - tsNumber) > MAX_AGE_SECONDS) {
      return json({ success: false, error: 'Bootstrap signature expired' }, 401);
    }
    if (!validSignature(apiKey, action, ts, sig)) {
      return json({ success: false, error: 'Unauthorized' }, 401);
    }

    const setup = deps.setupHandler ?? defaultSetupHandler(env);
    const persist = deps.persistHandler ?? defaultPersistHandler(env);

    if (action === 'dry-run' || action === 'apply') {
      return setup(internalRequest(request.url, apiKey, { apply: action === 'apply' }));
    }

    const status = action === 'test-create' ? '未做' : '已验证';
    return persist(internalRequest(request.url, apiKey, testPayload(status)));
  };
}

export const GET = createBootstrapHandler();
