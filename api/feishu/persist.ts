import { authorizeBacklinkOS, loadFeishuConfig } from '../../lib/feishu/config.js';
import { createFeishuClient, FeishuApiError } from '../../lib/feishu/client.js';
import { persistPlacement } from '../../lib/feishu/persistence.js';
import { PersistenceValidationError, validatePersistRequest } from '../../lib/feishu/validation.js';
import type { FeishuClientFactory } from '../../lib/feishu/types.js';

type PersistDeps = {
  env?: NodeJS.ProcessEnv;
  clientFactory?: FeishuClientFactory;
  validateImpl?: typeof validatePersistRequest;
  persistPlacementImpl?: typeof persistPlacement;
};

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

export function createPersistHandler(deps: PersistDeps = {}) {
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

    let config;
    try {
      config = loadFeishuConfig(env);
    } catch (error) {
      return json({ success: false, error: error instanceof Error ? error.message : 'Feishu configuration is incomplete' }, 503);
    }

    const validate = deps.validateImpl ?? validatePersistRequest;
    let validated;
    try {
      validated = validate(payload);
    } catch (error) {
      if (error instanceof PersistenceValidationError || error instanceof Error) {
        return json({ success: false, error: error.message }, 400);
      }
      return json({ success: false, error: 'Invalid persistence request' }, 400);
    }

    const factory = deps.clientFactory ?? ((value) => createFeishuClient(value));
    const persist = deps.persistPlacementImpl ?? persistPlacement;

    try {
      const result = await persist(factory(config), config, validated);
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

export const POST = createPersistHandler();
