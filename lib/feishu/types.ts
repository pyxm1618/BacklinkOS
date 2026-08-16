import type { FeishuConfig } from './config.js';

export type FeishuFieldProperty = ({
  options?: Array<{ name: string; id?: string; color?: number; [key: string]: unknown }>;
  [key: string]: unknown;
} | null);

export type FeishuField = {
  field_id: string;
  field_name: string;
  type: number;
  is_primary?: boolean;
  ui_type?: string;
  property?: FeishuFieldProperty;
  description?: string;
};

export type FeishuFieldInput = {
  field_name: string;
  type: number;
  property?: FeishuFieldProperty;
  description?: string;
  ui_type?: string;
};

export type FeishuRecord = {
  record_id: string;
  fields: Record<string, unknown>;
};

export type FeishuClient = {
  getTenantAccessToken(): Promise<string>;
  listFields(tableId: string): Promise<FeishuField[]>;
  hasAnyRecords(tableId: string): Promise<boolean>;
  createField(tableId: string, body: FeishuFieldInput): Promise<FeishuField>;
  updateField(tableId: string, fieldId: string, body: FeishuFieldInput): Promise<FeishuField>;
  searchRecords(tableId: string, body?: Record<string, unknown>): Promise<FeishuRecord[]>;
  createRecord(tableId: string, fields: Record<string, unknown>): Promise<FeishuRecord>;
  updateRecord(tableId: string, recordId: string, fields: Record<string, unknown>): Promise<FeishuRecord>;
};

export type FeishuClientFactory = (config: FeishuConfig) => FeishuClient;
