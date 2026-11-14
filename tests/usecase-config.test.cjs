const assert = require('node:assert/strict');
const test = require('node:test');
const { load } = require('./helpers/load-typescript.cjs');
const { DEFAULT_USE_CASE, parseUseCaseConfig } = load('lib/usecase-config.ts');
const { parseStudyPlan } = load('components/usecases/education/study-plan.ts');
const { parseWorkerEvent } = load('components/voice/state.ts');

test('default public config preserves the general assistant', () => {
  assert.equal(DEFAULT_USE_CASE.id, 'general_assistant');
  assert.equal(parseUseCaseConfig(JSON.stringify(DEFAULT_USE_CASE)).name, 'Voice Workbench');
});
test('public config drops backend fields and rejects invalid versions and shapes', () => {
  const config = parseUseCaseConfig(
    JSON.stringify({ ...DEFAULT_USE_CASE, api_key: 'private', instructions: 'private prompt' })
  );
  assert.ok(!('api_key' in config) && !('instructions' in config));
  for (const changed of [
    { schema_version: 2 },
    { languages: [] },
    { result_card_types: ['../code'] },
    { name: 'x'.repeat(100) },
  ])
    assert.equal(parseUseCaseConfig(JSON.stringify({ ...DEFAULT_USE_CASE, ...changed })), null);
  assert.equal(parseUseCaseConfig('x'.repeat(6001)), null);
});
const data = {
  topic: 'Fractions',
  total_minutes: 60,
  sessions: [
    { day: 1, focus: 'Review the basics', minutes: 20 },
    { day: 2, focus: 'Practice worked examples', minutes: 20 },
    { day: 3, focus: 'Recall and self-check', minutes: 20 },
  ],
};
test('a real-shaped public tool result reaches the custom-card contract', () => {
  const event = parseWorkerEvent(
    JSON.stringify({
      type: 'result',
      id: 'plan1',
      title: 'Study plan',
      text: '3 sessions',
      card_type: 'study_plan',
      data,
    })
  );
  assert.equal(event.result.cardType, 'study_plan');
  const plan = parseStudyPlan(event.result.data);
  assert.equal(plan.total_minutes, 60);
  assert.equal(plan.sessions.length, 3);
});
test('malformed study plans fail closed while generic text remains available', () => {
  for (const value of [
    undefined,
    {},
    { ...data, total_minutes: 999 },
    { ...data, sessions: [{ day: 1, focus: 'bad', minutes: -20 }] },
    { ...data, sessions: [data.sessions[0], data.sessions[0], data.sessions[0]] },
  ])
    assert.equal(parseStudyPlan(value), null);
  const event = parseWorkerEvent(
    JSON.stringify({
      type: 'result',
      id: 'x',
      title: 'Unknown card',
      text: 'Plain fallback',
      card_type: 'future_card',
      data: {},
    })
  );
  assert.equal(event.result.text, 'Plain fallback');
});
