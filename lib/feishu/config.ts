export type FeishuConfig = {
  appId: string;
  appSecret: string;
  appToken: string;
  opportunityTableId: string;
  evidenceTableId: string;
};

function required(env: NodeJS.ProcessEnv, key: string): string {
  const value = env[key]?.trim();
  if (!value) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value;
}

export function loadFeishuConfig(env: NodeJS.ProcessEnv = process.env): FeishuConfig {
  return {
    appId: required(env, 'FEISHU_APP_ID'),
    appSecret: required(env, 'FEISHU_APP_SECRET'),
    appToken: required(env, 'FEISHU_BITABLE_APP_TOKEN'),
    opportunityTableId: required(env, 'FEISHU_OPPORTUNITY_TABLE_ID'),
    evidenceTableId: required(env, 'FEISHU_EVIDENCE_TABLE_ID'),
  };
}

export function authorizeBacklinkOS(request: Request, expectedKey: string): boolean {
  if (!expectedKey) return false;
  return request.headers.get('X-BacklinkOS-Key') === expectedKey;
}
