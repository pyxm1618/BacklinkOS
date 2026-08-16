import test from 'node:test';
import assert from 'node:assert/strict';
import { PersistenceValidationError, validatePersistRequest } from '../lib/feishu/validation.ts';

function base() {
  return {
    main_record: {
      placement_key: 'example.com|Profile|https://example.com/profile/edit',
      URL: 'https://example.com/profile/edit',
      DR: 0,
      评级: 'B',
      状态: '已验证',
    },
    evidence_records: [
      {
        evidence_key: 'example|dr|ahrefs',
        placement_key: 'example.com|Profile|https://example.com/profile/edit',
        evidence_type: 'DR',
        canonical_domain: 'example.com',
        source: 'Ahrefs',
        status: 'CONFIRMED',
        value_number: 0,
      },
    ],
  };
}

test('numeric DR zero remains valid', () => {
  const result = validatePersistRequest(base());
  assert.equal(result.main_record.DR, 0);
});

test('nonnumeric DR is rejected instead of coerced to zero', () => {
  const input = base() as any;
  input.main_record.DR = 'unknown';
  assert.throws(() => validatePersistRequest(input), PersistenceValidationError);
});

test('visible monthly visits zero is rejected', () => {
  const input = base() as any;
  input.main_record['月访问量'] = 0;
  assert.throws(() => validatePersistRequest(input), /月访问量/);
});

test('visible monthly visits requires confirmed total-visits evidence with same value', () => {
  const input = base() as any;
  input.main_record['月访问量'] = 52300;
  input.evidence_records.push({
    evidence_key: 'example|traffic|organic',
    placement_key: input.main_record.placement_key,
    evidence_type: 'Traffic',
    canonical_domain: 'example.com',
    source: 'Ahrefs Traffic Checker',
    status: 'CONFIRMED',
    value_number: 52300,
    payload_json: JSON.stringify({ traffic_metric_type: 'organic_search_traffic_estimate' }),
  });
  assert.throws(() => validatePersistRequest(input), /total_monthly_visits_estimate/);
});

test('confirmed total monthly visits evidence may populate visible monthly visits', () => {
  const input = base() as any;
  input.main_record['月访问量'] = 52300;
  input.evidence_records.push({
    evidence_key: 'example|traffic|crawlora|2026-07',
    placement_key: input.main_record.placement_key,
    evidence_type: 'Traffic',
    canonical_domain: 'example.com',
    source: 'Crawlora',
    status: 'CONFIRMED',
    value_number: 52300,
    payload_json: JSON.stringify({ traffic_metric_type: 'total_monthly_visits_estimate' }),
  });
  assert.equal(validatePersistRequest(input).main_record['月访问量'], 52300);
});

test('F requires hard rejection evidence and reason', () => {
  const input = base() as any;
  input.main_record.评级 = 'F';
  input.main_record.状态 = '淘汰';
  assert.throws(() => validatePersistRequest(input), /hard-rejection/);
  input.evidence_records.push({
    evidence_key: 'example|hard_rejection|domain',
    placement_key: input.main_record.placement_key,
    evidence_type: 'HardRejection',
    canonical_domain: 'example.com',
    source: 'direct verification',
    status: 'CONFIRMED',
    hard_rejection_scope: 'domain',
    hard_rejection_reason: 'Domain expired',
  });
  assert.equal(validatePersistRequest(input).main_record.评级, 'F');
});

test('evidence placement key must match main placement key', () => {
  const input = base() as any;
  input.evidence_records[0].placement_key = 'other';
  assert.throws(() => validatePersistRequest(input), /placement_key/);
});

test('unsupported main-table select values are rejected before Feishu write', () => {
  const cases: Array<[string, string]> = [
    ['注册登录', '随便填'],
    ['外链形式', 'UnknownType'],
    ['链接属性', 'Maybe'],
    ['免费情况', '不知道'],
    ['评级', 'S'],
    ['状态', '处理中'],
  ];
  for (const [field, value] of cases) {
    const input = base() as any;
    input.main_record[field] = value;
    assert.throws(() => validatePersistRequest(input), new RegExp(field));
  }
});

test('unsupported hard rejection scope is rejected before Feishu write', () => {
  const input = base() as any;
  input.evidence_records[0].hard_rejection_scope = 'all';
  assert.throws(() => validatePersistRequest(input), /hard_rejection_scope/);
});
