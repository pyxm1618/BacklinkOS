import type { FeishuConfig } from './config.js';
import type { FeishuClient, FeishuField, FeishuFieldInput, FeishuRecord } from './types.js';

const FEISHU_BASE = 'https://open.feishu.cn/open-apis';

type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

type Envelope<T> = {
  code?: number;
  msg?: string;
  data?: T;
  tenant_access_token?: string;
  expire?: number;
};

export class FeishuApiError extends Error {
  readonly httpStatus: number | null;
  readonly code: number | null;

  constructor(message: string, httpStatus: number | null = null, code: number | null = null) {
    super(message);
    this.name = 'FeishuApiError';
    this.httpStatus = httpStatus;
    this.code = code;
  }
}

async function parseJson(response: Response): Promise<Record<string, unknown>> {
  try {
    const value = await response.json();
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new Error('invalid envelope');
    }
    return value as Record<string, unknown>;
  } catch {
    throw new FeishuApiError('Feishu returned malformed JSON', response.status, null);
  }
}

export function createFeishuClient(config: FeishuConfig, fetchImpl: FetchLike = fetch): FeishuClient {
  let cachedToken = '';

  async function getTenantAccessToken(): Promise<string> {
    if (cachedToken) return cachedToken;

    let response: Response;
    try {
      response = await fetchImpl(`${FEISHU_BASE}/auth/v3/tenant_access_token/internal`, {
        method: 'POST',
        headers: { 'content-type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ app_id: config.appId, app_secret: config.appSecret }),
      });
    } catch {
      throw new FeishuApiError('Feishu token request failed', null, null);
    }

    const payload = await parseJson(response) as Envelope<never>;
    const code = typeof payload.code === 'number' ? payload.code : null;
    if (!response.ok || code !== 0 || typeof payload.tenant_access_token !== 'string' || !payload.tenant_access_token) {
      throw new FeishuApiError(
        code === 0 ? 'Feishu token response was unusable' : (payload.msg || 'Feishu token request failed'),
        response.status,
        code,
      );
    }

    cachedToken = payload.tenant_access_token;
    return cachedToken;
  }

  async function requestData<T>(path: string, init?: RequestInit): Promise<T> {
    const token = await getTenantAccessToken();
    let response: Response;
    try {
      response = await fetchImpl(`${FEISHU_BASE}${path}`, {
        ...init,
        headers: {
          'content-type': 'application/json; charset=utf-8',
          authorization: `Bearer ${token}`,
          ...(init?.headers ?? {}),
        },
      });
    } catch {
      throw new FeishuApiError('Feishu API request failed', null, null);
    }

    const payload = await parseJson(response) as Envelope<T>;
    const code = typeof payload.code === 'number' ? payload.code : null;
    if (!response.ok || code !== 0) {
      throw new FeishuApiError(payload.msg || 'Feishu API request failed', response.status, code);
    }
    return (payload.data ?? {}) as T;
  }

  async function listFields(tableId: string): Promise<FeishuField[]> {
    const result: FeishuField[] = [];
    let pageToken = '';
    do {
      const query = new URLSearchParams({ page_size: '100' });
      if (pageToken) query.set('page_token', pageToken);
      const data = await requestData<{ items?: FeishuField[]; has_more?: boolean; page_token?: string }>(
        `/bitable/v1/apps/${encodeURIComponent(config.appToken)}/tables/${encodeURIComponent(tableId)}/fields?${query}`,
        { method: 'GET' },
      );
      result.push(...(Array.isArray(data.items) ? data.items : []));
      pageToken = data.has_more && typeof data.page_token === 'string' ? data.page_token : '';
    } while (pageToken);
    return result;
  }

  async function searchRecords(tableId: string, body: Record<string, unknown> = {}): Promise<FeishuRecord[]> {
    const data = await requestData<{ items?: FeishuRecord[] }>(
      `/bitable/v1/apps/${encodeURIComponent(config.appToken)}/tables/${encodeURIComponent(tableId)}/records/search?page_size=500`,
      { method: 'POST', body: JSON.stringify(body) },
    );
    return Array.isArray(data.items) ? data.items : [];
  }

  async function hasAnyRecords(tableId: string): Promise<boolean> {
    const data = await requestData<{ items?: FeishuRecord[] }>(
      `/bitable/v1/apps/${encodeURIComponent(config.appToken)}/tables/${encodeURIComponent(tableId)}/records/search?page_size=1`,
      { method: 'POST', body: '{}' },
    );
    return Array.isArray(data.items) && data.items.length > 0;
  }

  async function createField(tableId: string, body: FeishuFieldInput): Promise<FeishuField> {
    const data = await requestData<{ field?: FeishuField }>(
      `/bitable/v1/apps/${encodeURIComponent(config.appToken)}/tables/${encodeURIComponent(tableId)}/fields`,
      { method: 'POST', body: JSON.stringify(body) },
    );
    if (!data.field) throw new FeishuApiError('Feishu create-field response was unusable', 200, 0);
    return data.field;
  }

  async function updateField(tableId: string, fieldId: string, body: FeishuFieldInput): Promise<FeishuField> {
    const data = await requestData<{ field?: FeishuField }>(
      `/bitable/v1/apps/${encodeURIComponent(config.appToken)}/tables/${encodeURIComponent(tableId)}/fields/${encodeURIComponent(fieldId)}`,
      { method: 'PUT', body: JSON.stringify(body) },
    );
    if (!data.field) throw new FeishuApiError('Feishu update-field response was unusable', 200, 0);
    return data.field;
  }

  async function createRecord(tableId: string, fields: Record<string, unknown>): Promise<FeishuRecord> {
    const data = await requestData<{ record?: FeishuRecord }>(
      `/bitable/v1/apps/${encodeURIComponent(config.appToken)}/tables/${encodeURIComponent(tableId)}/records`,
      { method: 'POST', body: JSON.stringify({ fields }) },
    );
    if (!data.record) throw new FeishuApiError('Feishu create-record response was unusable', 200, 0);
    return data.record;
  }

  async function updateRecord(tableId: string, recordId: string, fields: Record<string, unknown>): Promise<FeishuRecord> {
    const data = await requestData<{ record?: FeishuRecord }>(
      `/bitable/v1/apps/${encodeURIComponent(config.appToken)}/tables/${encodeURIComponent(tableId)}/records/${encodeURIComponent(recordId)}`,
      { method: 'PUT', body: JSON.stringify({ fields }) },
    );
    if (!data.record) throw new FeishuApiError('Feishu update-record response was unusable', 200, 0);
    return data.record;
  }

  return {
    getTenantAccessToken,
    listFields,
    hasAnyRecords,
    createField,
    updateField,
    searchRecords,
    createRecord,
    updateRecord,
  };
}
