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

test('discovering-backlinks maps pending_semrush to the live project-pool schema instead of inventing a new sheet state', async () => {
  const skill = await repoText('.agents/skills/discovering-backlinks/SKILL.md');
  const cases = await repoText('.agents/skills/discovering-backlinks/references/test-cases.md');

  assert.match(skill, /pending_semrush[^\n]*待Semrush|待Semrush[^\n]*pending_semrush/i);
  assert.match(skill, /待Semrush筛选/);
  assert.match(skill, /(项目池|sheet|落表)[^\n]*(待Semrush)/i);
  assert.match(cases, /待Semrush/);
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

test('screening-backlinks uses fact-specific evidence precedence for technical rel observations', async () => {
  const skill = await repoText('.agents/skills/screening-backlinks/SKILL.md');
  const rules = await repoText('.agents/skills/screening-backlinks/references/screening-rules.md');
  const cases = await repoText('.agents/skills/screening-backlinks/references/test-cases.md');

  assert.match(skill, /(技术事实|technical)[^\n]*(DOM|结果页|result page)/i);
  assert.match(rules, /(rel|Follow)[^\n]*(结果页|listing|DOM)[^\n]*(高于|优先|outrank)/i);
  assert.match(rules, /(官方|official)[^\n]*(营销|宣传|marketing)[^\n]*(不能|不得|not)[^\n]*(覆盖|override)/i);
  assert.match(cases, /ToolIDX|toolidx/i);
  assert.match(cases, /(官方.*Dofollow.*第三方.*nofollow|third-party.*nofollow)/i);
  assert.match(cases, /(待确认|DOM)/i);
});

test('discovering-backlinks routes directly to master and project sheets and isolates verified facts', async () => {
  const skill = await repoText('.agents/skills/discovering-backlinks/SKILL.md');
  const contract = await repoText('.agents/skills/discovering-backlinks/references/master-sheet-contract.md');
  const cases = await repoText('.agents/skills/discovering-backlinks/references/test-cases.md');

  // 控制面表名与主链路
  assert.match(skill, /外链总表/);
  assert.match(skill, /外链管理/);
  assert.match(skill, /Upsert/i);
  assert.match(skill, /backlink-autofill/);

  // 字段隔离：严禁 Discovery 填写实测字段
  assert.match(skill, /实测免费/);
  assert.match(skill, /实测需登录/);
  assert.match(skill, /实测登录方式/);
  assert.match(skill, /实测限制/);
  assert.match(skill, /实测链接属性/);
  assert.match(skill, /(绝对不填写|严禁填写|不填写)[^\n]*(实测)/i);

  // 基础状态与硬黑名单
  assert.match(contract, /候选/);
  assert.match(contract, /已排除/);
  assert.match(contract, /失效/);
  assert.match(contract, /(不得覆盖|不覆盖)[^\n]*(已有真实|实测)/i);
  assert.match(contract, /(绝不得把|绝不把)[^\n]*(已排除|失效)[^\n]*(候选)/i);
  assert.match(contract, /硬黑名单/);

  assert.match(cases, /外链总表/);
  assert.match(cases, /实测免费/);
});

test('discovering-backlinks defines bounded submission entry enrichment and project row materialization', async () => {
  const skill = await repoText('.agents/skills/discovering-backlinks/SKILL.md');
  const contract = await repoText('.agents/skills/discovering-backlinks/references/master-sheet-contract.md');
  const cases = await repoText('.agents/skills/discovering-backlinks/references/test-cases.md');

  // 入口准备与 Policy Guard
  assert.match(skill, /Submission Entry Enrichment/i);
  assert.match(skill, /Policy Guard/i);
  assert.match(skill, /(pricing|terms|category|report)/i);
  assert.match(skill, /(找不到入口|未找到入口)[^\n]*(继续为空|保持为空|留空)[^\n]*(保留|不因为)/i);
  assert.match(skill, /(首页|homepage)[^\n]*(CTA|明确)/i);

  // 项目 Materialization
  assert.match(skill, /quick-iching/);
  assert.match(skill, /待提交/);
  assert.match(skill, /(唯一|重复)[^\n]*(project_id|backlink_id)/i);
  assert.match(skill, /Quick I Ching/);

  // 存量池 Bounded Batch Hydration
  assert.match(skill, /Bounded Batch Hydration/i);
  assert.match(skill, /limit/i);

  assert.match(contract, /Submission Entry Enrichment/i);
  assert.match(contract, /待提交/);
  assert.match(cases, /Policy Guard/i);
  assert.match(cases, /Quick I Ching/);
});

