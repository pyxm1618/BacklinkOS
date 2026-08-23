import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

async function repoText(relativePath: string): Promise<string> {
  return readFile(path.join(process.cwd(), relativePath), 'utf8');
}

test('discovering-backlinks exposes balanced seed expansion and source-url enrichment contract', async () => {
  const skill = await repoText('.agents/skills/discovering-backlinks/SKILL.md');
  const handoff = await repoText('.agents/skills/discovering-backlinks/references/screening-handoff.md');
  const cases = await repoText('.agents/skills/discovering-backlinks/references/test-cases.md');

  assert.match(skill, /100[^\n]*(批次|batch)[^\n]*(不是|not)[^\n]*(停止|stop)/i);
  assert.match(skill, /来源[^\n]*(占比|集中|均衡)|source[^\n]*(balance|concentration)/i);
  assert.match(skill, /pending_semrush/);
  assert.match(skill, /source_url_enrichment_required/);
  assert.match(skill, /source_url/);

  assert.match(handoff, /source_url_enrichment_required/);
  assert.match(handoff, /source_url/);
  assert.match(handoff, /未验证[^\n]*(endpoint|请求)|unverified[^\n]*(endpoint|request)/i);
  assert.match(handoff, /Screening[^\n]*(请求|request)[^\n]*Discovery/i);

  assert.match(cases, /pending_semrush/);
  assert.match(cases, /source_url_enrichment_required/);
});

test('screening-backlinks separates evidence precedence, acquisition mode, and disposition', async () => {
  const skill = await repoText('.agents/skills/screening-backlinks/SKILL.md');
  const rules = await repoText('.agents/skills/screening-backlinks/references/screening-rules.md');
  const schema = await repoText('.agents/skills/screening-backlinks/references/output-schema.md');
  const cases = await repoText('.agents/skills/screening-backlinks/references/test-cases.md');

  assert.match(skill, /证据优先级|evidence precedence/i);
  assert.match(skill, /处理结果/);
  assert.match(skill, /付费排除/);
  assert.match(skill, /source_url_enrichment_required/);
  assert.doesNotMatch(skill, /`付费`、Nofollow\/UGC\/Sponsored、没有外部 URL、入口失效、页面 noindex、明显垃圾站 → 回收站/);

  assert.match(rules, /没找到[^\n]*(不等于|≠)[^\n]*回收|not found[^\n]*!=[^\n]*recycle/i);
  assert.match(rules, /AS=0[^\n]*(不等于|≠)[^\n]*回收/);
  assert.match(rules, /历史[^\n]*0[^\n]*Follow[^\n]*(不等于|≠)[^\n]*回收/);
  assert.match(rules, /目标[^\n]*写入[^\n]*回读[^\n]*源|target[^\n]*write[^\n]*readback[^\n]*source/i);
  assert.match(rules, /ARRAYFORMULA|公式列/);

  assert.match(schema, /获取方式/);
  assert.match(schema, /处理结果/);
  assert.match(schema, /正式机会/);
  assert.match(schema, /付费排除/);
  assert.match(schema, /回收/);
  assert.match(schema, /待确认/);

  assert.match(cases, /付费排除/);
  assert.match(cases, /source_url_enrichment_required/);
});
