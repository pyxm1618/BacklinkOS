import type { FeishuConfig } from './config.ts';
import type { FeishuClient, FeishuRecord } from './types.ts';
import type { EvidenceRecord, MainRecord, ValidatedPersistRequest } from './validation.ts';

export type PersistAction = 'created' | 'updated' | 'conflict' | 'failed';

export type PersistItemResult = {
  action: PersistAction;
  record_id?: string;
  error?: string;
  evidence_key?: string;
};

export type PersistResult = {
  success: boolean;
  main: PersistItemResult;
  evidence: PersistItemResult[];
};

function exactFilter(fieldName: string, value: string): Record<string, unknown> {
  return {
    filter: {
      conjunction: 'and',
      conditions: [{ field_name: fieldName, operator: 'is', value: [value] }],
    },
  };
}

function cleanFields(input: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(input).filter(([, value]) => value !== undefined && value !== null));
}

function mainFields(record: MainRecord): Record<string, unknown> {
  return cleanFields(record);
}

function evidenceFields(record: EvidenceRecord): Record<string, unknown> {
  const fields: Record<string, unknown> = { ...record };
  if (typeof record.checked_at === 'string') {
    fields.checked_at = Date.parse(record.checked_at);
  }
  if (record.payload_json && typeof record.payload_json === 'object') {
    fields.payload_json = JSON.stringify(record.payload_json);
  }
  return cleanFields(fields);
}

async function lookupExact(client: FeishuClient, tableId: string, fieldName: string, key: string): Promise<FeishuRecord[]> {
  return client.searchRecords(tableId, exactFilter(fieldName, key));
}

async function upsert(
  client: FeishuClient,
  tableId: string,
  keyField: string,
  key: string,
  fields: Record<string, unknown>,
): Promise<PersistItemResult> {
  let matches: FeishuRecord[];
  try {
    matches = await lookupExact(client, tableId, keyField, key);
  } catch (error) {
    return { action: 'failed', error: error instanceof Error ? error.message : 'lookup failed' };
  }

  if (matches.length > 1) {
    return { action: 'conflict', error: `Multiple records found for ${keyField}` };
  }

  try {
    if (matches.length === 0) {
      const created = await client.createRecord(tableId, fields);
      return { action: 'created', record_id: created.record_id };
    }
    const updated = await client.updateRecord(tableId, matches[0].record_id, fields);
    return { action: 'updated', record_id: updated.record_id };
  } catch (error) {
    return { action: 'failed', error: error instanceof Error ? error.message : 'write failed' };
  }
}

export async function persistPlacement(
  client: FeishuClient,
  config: FeishuConfig,
  request: ValidatedPersistRequest,
): Promise<PersistResult> {
  const main = await upsert(
    client,
    config.opportunityTableId,
    'placement_key',
    request.main_record.placement_key,
    mainFields(request.main_record),
  );

  if (main.action === 'conflict' || main.action === 'failed') {
    return { success: false, main, evidence: [] };
  }

  const evidence: PersistItemResult[] = [];
  for (const item of request.evidence_records) {
    const result = await upsert(
      client,
      config.evidenceTableId,
      'evidence_key',
      item.evidence_key,
      evidenceFields(item),
    );
    evidence.push({ ...result, evidence_key: item.evidence_key });
  }

  return {
    success: evidence.every((item) => item.action === 'created' || item.action === 'updated'),
    main,
    evidence,
  };
}
