import { authorizeBacklinkOS, loadFeishuConfig } from '../../lib/feishu/config.js';
import { createFeishuClient, FeishuApiError } from '../../lib/feishu/client.js';
import { setupTable } from '../../lib/feishu/schema.js';
import type { FeishuClientFactory } from '../../lib/feishu/types.js';

type SetupImpl = typeof setupTable;

type SetupDeps = {
  env?: NodeJS.ProcessEnv;
  clientFactory?: FeishuClientFactory;
  setupTableImpl?: SetupImpl;
};

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

export function createSetupHandler(deps: SetupDeps = {}) {
  return async function POST(request: Request): Promise<Response> {
    const env = deps.env ?? process.env;
    const apiKey = env.BACKLINKOS_API_KEY?.trim() ?? '';
    if (!apiKey) return json({ success: false, error: 'BacklinkOS API key is not configured' }, 503);
    if (!authorizeBacklinkOS(request, apiKey)) return json({ success: false, error: 'Unauthorized' }, 401);

    let payload: unknown;
    try {
      payload = await request.json();
    } catch {
      return json({ success: false, error: 'Invalid JSON body' }, 400);
    }
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      return json({ success: false, error: 'Request body must be an object' }, 400);
    }
    const applyValue = (payload as Record<string, unknown>).apply;
    if (applyValue !== undefined && typeof applyValue !== 'boolean') {
      return json({ success: false, error: 'apply must be boolean' }, 400);
    }
    const apply = applyValue === true;

    let config;
    try {
      config = loadFeishuConfig(env);
    } catch (error) {
      return json({ success: false, error: error instanceof Error ? error.message : 'Feishu configuration is incomplete' }, 503);
    }

    const factory = deps.clientFactory ?? ((value) => createFeishuClient(value));
    const runSetup = deps.setupTableImpl ?? setupTable;
    const client = factory(config);

    try {
      const opportunity = await runSetup(client, config.opportunityTableId, 'opportunity', apply);
      const evidence = await runSetup(client, config.evidenceTableId, 'evidence', apply);
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

export const POST = createSetupHandler();
