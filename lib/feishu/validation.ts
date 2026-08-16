export class PersistenceValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PersistenceValidationError';
  }
}

export type MainRecord = {
  placement_key: string;
  URL: string;
  注册登录?: string;
  行业?: string;
  外链形式?: string;
  链接属性?: string;
  免费情况?: string;
  DR?: number;
  月访问量?: number;
  域龄?: string;
  评级?: string;
  状态?: string;
  已发布外链URL?: string;
  [key: string]: unknown;
};

export type EvidenceRecord = {
  evidence_key: string;
  placement_key: string;
  evidence_type: string;
  canonical_domain?: string;
  source?: string;
  status?: string;
  value_number?: number;
  value_text?: string;
  period?: string;
  checked_at?: string;
  evidence_url?: string;
  hard_rejection_scope?: 'domain' | 'placement';
  hard_rejection_reason?: string;
  notes?: string;
  payload_json?: string | Record<string, unknown>;
  [key: string]: unknown;
};

export type ValidatedPersistRequest = {
  main_record: MainRecord;
  evidence_records: EvidenceRecord[];
};

const MAIN_SELECTS: Record<string, readonly string[]> = {
  注册登录: ['无需注册', '需要注册登录', '需要审核', '未确认'],
  外链形式: ['Profile', 'Blog/Post', 'Comment', 'Classified', 'Directory', 'Community/Forum', 'Other'],
  链接属性: ['Dofollow', 'Nofollow', '未确认'],
  免费情况: ['免费', '部分免费', '付费', '未确认'],
  评级: ['A', 'B', 'C', 'D', 'F'],
  状态: ['未做', '已验证', '已注册', '已发布', '淘汰'],
};

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function requireString(object: Record<string, unknown>, key: string): string {
  const value = object[key];
  if (typeof value !== 'string' || !value.trim()) {
    throw new PersistenceValidationError(`${key} is required`);
  }
  return value.trim();
}

function validateSelects(main: MainRecord): void {
  for (const [field, allowed] of Object.entries(MAIN_SELECTS)) {
    const value = main[field];
    if (value === undefined || value === '') continue;
    if (typeof value !== 'string' || !allowed.includes(value)) {
      throw new PersistenceValidationError(`${field} must be one of: ${allowed.join(' / ')}`);
    }
  }
}

function parsePayload(value: unknown): Record<string, unknown> | null {
  if (value === undefined || value === null || value === '') return null;
  if (isObject(value)) return value;
  if (typeof value !== 'string') throw new PersistenceValidationError('payload_json must be JSON text or object');
  try {
    const parsed = JSON.parse(value);
    if (!isObject(parsed)) throw new Error('not object');
    return parsed;
  } catch {
    throw new PersistenceValidationError('payload_json must contain a JSON object');
  }
}

export function validatePersistRequest(input: unknown): ValidatedPersistRequest {
  if (!isObject(input) || !isObject(input.main_record)) {
    throw new PersistenceValidationError('main_record is required');
  }
  if (!Array.isArray(input.evidence_records)) {
    throw new PersistenceValidationError('evidence_records must be an array');
  }

  const main = { ...input.main_record } as MainRecord;
  main.placement_key = requireString(main, 'placement_key');
  main.URL = requireString(main, 'URL');

  if ('相关度' in main) {
    throw new PersistenceValidationError('相关度 is not part of the screening persistence schema');
  }

  validateSelects(main);

  if (main.DR !== undefined) {
    if (typeof main.DR !== 'number' || !Number.isFinite(main.DR) || main.DR < 0 || main.DR > 100) {
      throw new PersistenceValidationError('DR must be a finite numeric Ahrefs Domain Rating from 0 to 100');
    }
  }

  if (main['月访问量'] !== undefined) {
    const value = main['月访问量'];
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
      throw new PersistenceValidationError('月访问量 must be a positive confirmed total-monthly-visits estimate; zero/unknown is not allowed');
    }
  }

  const evidence = input.evidence_records.map((raw, index): EvidenceRecord => {
    if (!isObject(raw)) throw new PersistenceValidationError(`evidence_records[${index}] must be an object`);
    const item = { ...raw } as EvidenceRecord;
    item.evidence_key = requireString(item, 'evidence_key');
    item.placement_key = requireString(item, 'placement_key');
    item.evidence_type = requireString(item, 'evidence_type');
    if (item.placement_key !== main.placement_key) {
      throw new PersistenceValidationError(`evidence_records[${index}].placement_key must match main placement_key`);
    }
    if (item.hard_rejection_scope !== undefined && item.hard_rejection_scope !== 'domain' && item.hard_rejection_scope !== 'placement') {
      throw new PersistenceValidationError(`evidence_records[${index}].hard_rejection_scope must be domain or placement`);
    }
    if (item.value_number !== undefined && (typeof item.value_number !== 'number' || !Number.isFinite(item.value_number))) {
      throw new PersistenceValidationError(`evidence_records[${index}].value_number must be numeric`);
    }
    if (item.checked_at !== undefined && (typeof item.checked_at !== 'string' || Number.isNaN(Date.parse(item.checked_at)))) {
      throw new PersistenceValidationError(`evidence_records[${index}].checked_at must be an ISO date/time`);
    }
    parsePayload(item.payload_json);
    return item;
  });

  if (main['月访问量'] !== undefined) {
    const monthly = main['月访问量'];
    const matching = evidence.some((item) => {
      if (item.evidence_type !== 'Traffic' || item.status !== 'CONFIRMED' || item.value_number !== monthly) return false;
      const payload = parsePayload(item.payload_json);
      return payload?.traffic_metric_type === 'total_monthly_visits_estimate';
    });
    if (!matching) {
      throw new PersistenceValidationError('月访问量 requires matching CONFIRMED total_monthly_visits_estimate evidence');
    }
  }

  if (main.评级 === 'F') {
    const hardRejection = evidence.some((item) =>
      item.evidence_type === 'HardRejection' &&
      item.status === 'CONFIRMED' &&
      typeof item.hard_rejection_reason === 'string' &&
      item.hard_rejection_reason.trim().length > 0
    );
    if (!hardRejection) {
      throw new PersistenceValidationError('评级=F requires confirmed hard-rejection evidence and reason');
    }
  }

  return { main_record: main, evidence_records: evidence };
}
