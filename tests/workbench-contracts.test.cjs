const assert = require('node:assert/strict');
const test = require('node:test');
const corpus = require('../contracts/voice-workbench/v1/fixtures.json');
const validators = require('../lib/workbench/generated/validators.cjs');
const { load } = require('./helpers/load-typescript.cjs');
const contracts = load('lib/workbench/contracts.ts');
const { parseWorkerEvent } = load('components/voice/state.ts');
const { parseUseCaseConfig } = load('lib/usecase-config.ts');
const eventSchema = require('../contracts/voice-workbench/v1/events.schema.json');

test('v1 topic and actual Python serializer corpus cover every variant', () => {
  assert.equal(contracts.WORKBENCH_TOPIC, 'voice.workbench.v1');
  assert.equal(contracts.WORKBENCH_TOPIC, corpus.topic);
  assert.deepEqual(
    new Set(corpus.events.map((e) => e.type)),
    new Set(['tool', 'result', 'error', 'interrupted'])
  );
});
for (const [index, event] of corpus.events.entries()) {
  test(`Python event ${index}: ${event.type}/${event.status ?? event.code ?? event.id ?? ''}`, () => {
    assert.equal(validators.validateEvent(event), true);
    const parsed = parseWorkerEvent(JSON.stringify(event));
    assert.ok(parsed);
    assert.equal(parsed.type, event.type);
    if (event.type === 'tool' && event.status === 'confirmation_required')
      assert.equal(parsed.tool.confirmationId, event.confirmation_id);
  });
}
for (const [index, call] of corpus.rpc.entries()) {
  test(`Python RPC ${index}: ${call.method}`, () => {
    assert.equal(validators.validateRpc(call), true);
    assert.deepEqual(
      JSON.parse(contracts.encodeRpcRequest(call.method, call.request)),
      call.request
    );
    assert.deepEqual(
      contracts.parseRpcResponse(call.method, JSON.stringify(call.response)),
      call.response
    );
    if (call.method === 'voice.usecase_config')
      assert.deepEqual(parseUseCaseConfig(JSON.stringify(call.response)), call.response);
  });
}
for (const error of corpus.errors) {
  test(`LiveKit error ${error.code} serialized by Python`, () => {
    assert.equal(validators.validateRpcError(error), true);
    assert.ok(!JSON.stringify(error).includes('must-not-appear'));
  });
}
test('MCP activity and education result use actual shared envelopes', () => {
  assert.ok(corpus.events.some((e) => e.id === 'mcp-clock' && e.status === 'completed'));
  const card = corpus.events.find((e) => e.type === 'result' && e.card_type === 'study_plan');
  const parsed = parseWorkerEvent(JSON.stringify(card));
  assert.equal(parsed.result.cardType, 'study_plan');
  assert.equal(parsed.result.data.sessions.length, 2);
});
test('required fields, statuses and confirmation tokens fail closed', () => {
  const event = { type: 'tool', id: 'one', name: 'Action', status: 'running' };
  for (const key of ['type', 'id', 'name', 'status']) {
    const changed = { ...event };
    delete changed[key];
    assert.equal(parseWorkerEvent(JSON.stringify(changed)), null);
  }
  for (const changed of [
    { status: 'invented' },
    { revision: -1 },
    { revision: true },
    { revision: 2 ** 53 },
    { status: 'confirmation_required' },
  ])
    assert.equal(parseWorkerEvent(JSON.stringify({ ...event, ...changed })), null);
  assert.equal(parseWorkerEvent('{"type":"v2.event"}'), null);
  assert.equal(parseWorkerEvent('{'), null);
});
test('optional fields and legacy projections preserve safe compatibility', () => {
  assert.ok(parseWorkerEvent('{"type":"interrupted"}'));
  assert.equal(
    parseWorkerEvent(
      JSON.stringify({ type: 'error', code: 'provider_unavailable', message: 'private-secret' })
    ).message.includes('private-secret'),
    false
  );
  const event = {
    type: 'result',
    id: 'x'.repeat(201),
    title: 'Result',
    text: 'Text',
    card_type: '../invalid',
    data: [],
  };
  const parsed = parseWorkerEvent(JSON.stringify(event));
  assert.equal(parsed.result.id.length, 200);
  assert.equal(parsed.result.cardType, undefined);
  assert.equal(parsed.result.data, undefined);
});
test('every RPC rejects malformed bodies, responses and unknown methods', () => {
  for (const method of ['voice.interrupt', 'voice.tools_state', 'voice.usecase_config'])
    assert.throws(
      () => contracts.encodeRpcRequest(method, { extra: true }),
      /Invalid workbench request/
    );
  assert.throws(() =>
    contracts.encodeRpcRequest('voice.confirm_tool', { confirmation_id: 'x', approved: 'true' })
  );
  for (const method of ['unknown', '__proto__', 'toString']) {
    assert.throws(() => contracts.encodeRpcRequest(method, {}));
    assert.equal(contracts.parseRpcResponse(method, '{}'), null);
  }
  for (const call of corpus.rpc)
    assert.equal(contracts.parseRpcResponse(call.method, 'null'), null);
  assert.equal(contracts.parseRpcResponse('voice.confirm_tool', '{"accepted":false}'), null);
  assert.equal(contracts.parseRpcResponse('voice.interrupt', '{"interrupted":false}'), null);
  assert.equal(contracts.parseRpcResponse('voice.tools_state', '[]'.repeat(9000)), null);
});
test('public config v1 and Unicode limits agree with Python', () => {
  const config = { ...corpus.rpc.find((c) => c.method === 'voice.usecase_config').response };
  assert.equal(parseUseCaseConfig(JSON.stringify({ ...config, schema_version: 2 })), null);
  config.name = '😀'.repeat(80);
  assert.ok(parseUseCaseConfig(JSON.stringify(config)));
  config.name += '😀';
  assert.equal(parseUseCaseConfig(JSON.stringify(config)), null);
});
test('all event and public-config required fields are enforced', () => {
  const fields = {
    tool: eventSchema.$defs.toolFields.required,
    ...Object.fromEntries(
      ['result', 'error', 'interrupted'].map((kind) => [
        kind,
        eventSchema.$defs[kind + 'Event'].required,
      ])
    ),
  };
  for (const [kind, required] of Object.entries(fields)) {
    const sample = corpus.events.find((event) => event.type === kind);
    for (const key of required) {
      const changed = { ...sample };
      delete changed[key];
      assert.equal(parseWorkerEvent(JSON.stringify(changed)), null);
    }
  }
  const config = corpus.rpc.find((call) => call.method === 'voice.usecase_config').response;
  for (const key of Object.keys(config)) {
    const changed = { ...config };
    delete changed[key];
    assert.equal(parseUseCaseConfig(JSON.stringify(changed)), null);
  }
});
