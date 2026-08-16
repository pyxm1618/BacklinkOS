import type { FeishuClient, FeishuField, FeishuFieldInput, FeishuFieldProperty } from './types.ts';

export type TableKind = 'opportunity' | 'evidence';

export type SchemaAction =
  | { kind: 'create'; body: FeishuFieldInput }
  | { kind: 'update'; fieldId: string; body: FeishuFieldInput };

export type SchemaPlan = {
  actions: SchemaAction[];
  conflicts: string[];
};

type DesiredField = {
  name: string;
  type: number;
  uiType: string;
  options?: string[];
};

const OPPORTUNITY_FIELDS: DesiredField[] = [
  { name: 'URL', type: 1, uiType: 'Text' },
  { name: 'placement_key', type: 1, uiType: 'Text' },
  { name: '注册登录', type: 3, uiType: 'SingleSelect', options: ['无需注册','需要注册登录','需要审核','未确认'] },
  { name: '行业', type: 1, uiType: 'Text' },
  { name: '外链形式', type: 3, uiType: 'SingleSelect', options: ['Profile','Blog/Post','Comment','Classified','Directory','Community/Forum','Other'] },
  { name: '链接属性', type: 3, uiType: 'SingleSelect', options: ['Dofollow','Nofollow','未确认'] },
  { name: '免费情况', type: 3, uiType: 'SingleSelect', options: ['免费','部分免费','付费','未确认'] },
  { name: 'DR', type: 2, uiType: 'Number' },
  { name: '月访问量', type: 2, uiType: 'Number' },
  { name: '域龄', type: 1, uiType: 'Text' },
  { name: '评级', type: 3, uiType: 'SingleSelect', options: ['A','B','C','D','F'] },
  { name: '状态', type: 3, uiType: 'SingleSelect', options: ['未做','已验证','已注册','已发布','淘汰'] },
  { name: '已发布外链URL', type: 1, uiType: 'Text' },
];

const EVIDENCE_FIELDS: DesiredField[] = [
  { name: 'placement_key', type: 1, uiType: 'Text' },
  { name: 'evidence_key', type: 1, uiType: 'Text' },
  { name: 'evidence_type', type: 1, uiType: 'Text' },
  { name: 'canonical_domain', type: 1, uiType: 'Text' },
  { name: 'source', type: 1, uiType: 'Text' },
  { name: 'status', type: 1, uiType: 'Text' },
  { name: 'value_number', type: 2, uiType: 'Number' },
  { name: 'value_text', type: 1, uiType: 'Text' },
  { name: 'period', type: 1, uiType: 'Text' },
  { name: 'checked_at', type: 5, uiType: 'DateTime' },
  { name: 'evidence_url', type: 1, uiType: 'Text' },
  { name: 'hard_rejection_scope', type: 3, uiType: 'SingleSelect', options: ['domain','placement'] },
  { name: 'hard_rejection_reason', type: 1, uiType: 'Text' },
  { name: 'notes', type: 1, uiType: 'Text' },
  { name: 'payload_json', type: 1, uiType: 'Text' },
];

function desired(kind: TableKind): DesiredField[] {
  return kind === 'opportunity' ? OPPORTUNITY_FIELDS : EVIDENCE_FIELDS;
}

function primaryTarget(kind: TableKind): string {
  return kind === 'opportunity' ? 'URL' : 'placement_key';
}

function createBody(field: DesiredField): FeishuFieldInput {
  return {
    field_name: field.name,
    type: field.type,
    ui_type: field.uiType,
    ...(field.options ? { property: { options: field.options.map((name) => ({ name })) } } : {}),
  };
}

function fullUpdateBody(field: FeishuField, name = field.field_name, property: FeishuFieldProperty = field.property ?? null): FeishuFieldInput {
  return {
    field_name: name,
    type: field.type,
    property,
    ...(field.description !== undefined ? { description: field.description } : {}),
    ...(field.ui_type ? { ui_type: field.ui_type } : {}),
  };
}

function uiCompatible(existing: FeishuField, expected: DesiredField): boolean {
  if (existing.type !== expected.type) return false;
  if (!existing.ui_type) return true;
  return existing.ui_type === expected.uiType;
}

export function planTableSetup(kind: TableKind, fields: FeishuField[], hasRecords: boolean): SchemaPlan {
  const actions: SchemaAction[] = [];
  const conflicts: string[] = [];
  const targetPrimary = primaryTarget(kind);
  const primary = fields.find((field) => field.is_primary);
  let primaryWillBeTarget = false;

  if (!primary) {
    conflicts.push(`${kind}: primary field not found`);
  } else if (primary.field_name === targetPrimary) {
    primaryWillBeTarget = true;
    const expected = desired(kind).find((field) => field.name === targetPrimary)!;
    if (!uiCompatible(primary, expected)) {
      conflicts.push(`${kind}: primary field ${targetPrimary} has incompatible type`);
    }
  } else if (primary.field_name === '文本') {
    if (hasRecords) {
      conflicts.push(`${kind}: primary field 文本 cannot be safely renamed because the table already has records`);
    } else if (primary.type !== 1) {
      conflicts.push(`${kind}: primary field 文本 has incompatible type`);
    } else {
      primaryWillBeTarget = true;
      actions.push({ kind: 'update', fieldId: primary.field_id, body: fullUpdateBody(primary, targetPrimary) });
    }
  } else {
    conflicts.push(`${kind}: primary field must be ${targetPrimary}; found ${primary.field_name}`);
  }

  for (const expected of desired(kind)) {
    if (expected.name === targetPrimary && primaryWillBeTarget) continue;

    const existing = fields.find((field) => field.field_name === expected.name);
    if (!existing) {
      actions.push({ kind: 'create', body: createBody(expected) });
      continue;
    }

    if (!uiCompatible(existing, expected)) {
      conflicts.push(`${kind}: field ${expected.name} has incompatible type`);
      continue;
    }

    if (expected.options) {
      const existingOptions = Array.isArray(existing.property?.options) ? existing.property!.options! : [];
      const existingNames = new Set(existingOptions.map((option) => option.name));
      const missing = expected.options.filter((name) => !existingNames.has(name));
      if (missing.length) {
        const currentProperty = existing.property && typeof existing.property === 'object' ? existing.property : {};
        const mergedProperty: FeishuFieldProperty = {
          ...currentProperty,
          options: [...existingOptions, ...missing.map((name) => ({ name }))],
        };
        actions.push({ kind: 'update', fieldId: existing.field_id, body: fullUpdateBody(existing, existing.field_name, mergedProperty) });
      }
    }
  }

  return { actions, conflicts };
}

export async function applyTablePlan(client: FeishuClient, tableId: string, plan: SchemaPlan): Promise<void> {
  if (plan.conflicts.length) return;
  for (const action of plan.actions) {
    if (action.kind === 'create') {
      await client.createField(tableId, action.body);
    } else {
      await client.updateField(tableId, action.fieldId, action.body);
    }
  }
}

export async function setupTable(
  client: FeishuClient,
  tableId: string,
  kind: TableKind,
  apply: boolean,
): Promise<{
  tableId: string;
  kind: TableKind;
  apply: boolean;
  actions: SchemaAction[];
  conflicts: string[];
  fields: FeishuField[];
  remaining_actions?: SchemaAction[];
  verification_conflicts?: string[];
}> {
  const fields = await client.listFields(tableId);
  const hasRecords = await client.hasAnyRecords(tableId);
  const plan = planTableSetup(kind, fields, hasRecords);

  if (!apply || plan.conflicts.length) {
    return { tableId, kind, apply, actions: plan.actions, conflicts: plan.conflicts, fields };
  }

  await applyTablePlan(client, tableId, plan);
  const finalFields = await client.listFields(tableId);
  const finalHasRecords = await client.hasAnyRecords(tableId);
  const verification = planTableSetup(kind, finalFields, finalHasRecords);
  return {
    tableId,
    kind,
    apply,
    actions: plan.actions,
    conflicts: plan.conflicts,
    fields: finalFields,
    remaining_actions: verification.actions,
    verification_conflicts: verification.conflicts,
  };
}
