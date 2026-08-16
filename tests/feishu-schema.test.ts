import test from 'node:test';
import assert from 'node:assert/strict';
import { planTableSetup } from '../lib/feishu/schema.ts';
import type { FeishuField } from '../lib/feishu/types.ts';

const primary = (name='文本'): FeishuField => ({
  field_id: 'fld_primary', field_name: name, type: 1, is_primary: true, ui_type: 'Text', property: null,
});

test('empty opportunity table plans primary rename and missing field creation', () => {
  const plan = planTableSetup('opportunity', [primary()], false);
  assert.equal(plan.conflicts.length, 0);
  assert.ok(plan.actions.some((a) => a.kind === 'update' && a.fieldId === 'fld_primary' && a.body.field_name === 'URL'));
  assert.ok(plan.actions.some((a) => a.kind === 'create' && a.body.field_name === 'placement_key'));
  assert.ok(plan.actions.some((a) => a.kind === 'create' && a.body.field_name === 'DR' && a.body.type === 2));
});

test('fully matching opportunity schema is idempotent', () => {
  const fields: FeishuField[] = [
    primary('URL'),
    { field_id:'f2', field_name:'placement_key', type:1, ui_type:'Text', property:null },
    { field_id:'f3', field_name:'注册登录', type:3, ui_type:'SingleSelect', property:{ options:[{id:'o1',name:'无需注册'},{id:'o2',name:'需要注册登录'},{id:'o3',name:'需要审核'},{id:'o4',name:'未确认'}] } },
    { field_id:'f4', field_name:'行业', type:1, ui_type:'Text', property:null },
    { field_id:'f5', field_name:'外链形式', type:3, ui_type:'SingleSelect', property:{ options:[{name:'Profile'},{name:'Blog/Post'},{name:'Comment'},{name:'Classified'},{name:'Directory'},{name:'Community/Forum'},{name:'Other'}] } },
    { field_id:'f6', field_name:'链接属性', type:3, ui_type:'SingleSelect', property:{ options:[{name:'Dofollow'},{name:'Nofollow'},{name:'未确认'}] } },
    { field_id:'f7', field_name:'免费情况', type:3, ui_type:'SingleSelect', property:{ options:[{name:'免费'},{name:'部分免费'},{name:'付费'},{name:'未确认'}] } },
    { field_id:'f8', field_name:'DR', type:2, ui_type:'Number', property:null },
    { field_id:'f9', field_name:'月访问量', type:2, ui_type:'Number', property:null },
    { field_id:'f10', field_name:'域龄', type:1, ui_type:'Text', property:null },
    { field_id:'f11', field_name:'评级', type:3, ui_type:'SingleSelect', property:{ options:[{name:'A'},{name:'B'},{name:'C'},{name:'D'},{name:'F'}] } },
    { field_id:'f12', field_name:'状态', type:3, ui_type:'SingleSelect', property:{ options:[{name:'未做'},{name:'已验证'},{name:'已注册'},{name:'已发布'},{name:'淘汰'}] } },
    { field_id:'f13', field_name:'已发布外链URL', type:1, ui_type:'Text', property:null },
  ];
  const plan = planTableSetup('opportunity', fields, false);
  assert.deepEqual(plan, { actions: [], conflicts: [] });
});

test('wrong type becomes an explicit conflict', () => {
  const plan = planTableSetup('opportunity', [primary('URL'), { field_id:'f2', field_name:'DR', type:1, ui_type:'Text', property:null }], false);
  assert.ok(plan.conflicts.some((c) => c.includes('DR')));
});

test('nonempty default primary rename is blocked', () => {
  const plan = planTableSetup('opportunity', [primary()], true);
  assert.ok(plan.conflicts.some((c) => c.includes('primary')));
  assert.equal(plan.actions.some((a) => a.kind === 'update' && a.fieldId === 'fld_primary'), false);
});

test('single select merge preserves existing options and adds required missing options', () => {
  const plan = planTableSetup('opportunity', [
    primary('URL'),
    { field_id:'f3', field_name:'链接属性', type:3, ui_type:'SingleSelect', property:{ options:[{id:'keep',name:'Dofollow',color:1},{id:'custom',name:'自定义'}] } },
  ], false);
  const update = plan.actions.find((a) => a.kind === 'update' && a.fieldId === 'f3');
  assert.ok(update && update.kind === 'update');
  const names = ((update.body.property as {options:Array<{name:string}>}).options).map((o) => o.name);
  assert.deepEqual(names, ['Dofollow','自定义','Nofollow','未确认']);
});
