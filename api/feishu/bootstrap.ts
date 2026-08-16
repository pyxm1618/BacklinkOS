import { createHmac, timingSafeEqual } from 'node:crypto';
import { createSetupHandler } from './setup.ts';
import { createPersistHandler } from './persist.ts';

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

    const setup = deps.setupHandler ?? createSetupHandler({ env });
    const persist = deps.persistHandler ?? createPersistHandler({ env });

    if (action === 'dry-run' || action === 'apply') {
      return setup(internalRequest(request.url, apiKey, { apply: action === 'apply' }));
    }

    const status = action === 'test-create' ? '未做' : '已验证';
    return persist(internalRequest(request.url, apiKey, testPayload(status)));
  };
}

export const GET = createBootstrapHandler();
