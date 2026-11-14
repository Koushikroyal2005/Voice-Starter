const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');
const exportsObject = {};
const filename = path.resolve(__dirname, '../components/voice/state.ts');
vm.runInNewContext(
  ts.transpileModule(readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText,
  { exports: exportsObject, Error },
  { filename }
);
const { deriveVoiceState, parseWorkerEvent, mediaErrorMessage, mergeToolActivities } =
  exportsObject;
test('connected but idle agent is not mislabelled as still connecting', () =>
  assert.equal(deriveVoiceState(snapshot({ agent: 'idle' })), 'idle'));
const snapshot = (overrides = {}) => ({
  connection: 'connected',
  agent: 'listening',
  command: 'idle',
  error: null,
  interrupted: false,
  executing: false,
  ...overrides,
});

for (const state of ['listening', 'thinking', 'speaking']) {
  test(`derives ${state} from actual agent state`, () =>
    assert.equal(deriveVoiceState(snapshot({ agent: state })), state));
}
test('idle requires disconnected transport', () =>
  assert.equal(deriveVoiceState(snapshot({ connection: 'disconnected' })), 'idle'));
test('connecting while worker initializes', () =>
  assert.equal(deriveVoiceState(snapshot({ agent: 'initializing' })), 'connecting'));
test('starting and ending are explicit command phases', () => {
  assert.equal(deriveVoiceState(snapshot({ command: 'starting' })), 'connecting');
  assert.equal(deriveVoiceState(snapshot({ command: 'ending' })), 'disconnecting');
});
test('both LiveKit reconnection modes override stale speech', () => {
  for (const connection of ['reconnecting', 'signalReconnecting'])
    assert.equal(deriveVoiceState(snapshot({ connection, agent: 'speaking' })), 'reconnecting');
});
test('tool events alone identify executing state', () => {
  assert.equal(deriveVoiceState(snapshot({ agent: 'thinking' })), 'thinking');
  assert.equal(deriveVoiceState(snapshot({ executing: true })), 'executing');
});
test('confirmed interruption is distinct from mute', () =>
  assert.equal(deriveVoiceState(snapshot({ interrupted: true })), 'interrupted'));
test('errors are explicit, including agent failure', () => {
  assert.equal(deriveVoiceState(snapshot({ error: 'failed' })), 'error');
  assert.equal(deriveVoiceState(snapshot({ agent: 'failed' })), 'error');
});
test('valid real tool/result event contracts', () => {
  assert.equal(
    parseWorkerEvent('{"type":"tool","id":"1","name":"lookup","status":"running"}').tool.status,
    'running'
  );
  assert.equal(
    parseWorkerEvent('{"type":"result","id":"1","title":"Result","text":"Done"}').result.text,
    'Done'
  );
  assert.equal(parseWorkerEvent('{"type":"interrupted"}').type, 'interrupted');
});
test('invalid, oversized, unknown or malformed events are ignored', () => {
  for (const raw of [
    'null',
    '[]',
    '{',
    'x'.repeat(17000),
    '{"type":"tool","id":"1","name":"lookup","status":"made-up"}',
    '{"type":"result","title":4}',
    '{"type":"unknown"}',
  ])
    assert.equal(parseWorkerEvent(raw), null);
});
test('actionable permission and missing-device errors', () => {
  for (const [name, expected] of [
    ['NotAllowedError', /denied/],
    ['NotFoundError', /No microphone/],
    ['NotReadableError', /unavailable/],
  ]) {
    const error = new Error();
    error.name = name;
    assert.match(mediaErrorMessage(error), expected);
  }
  assert.match(mediaErrorMessage(new Error('secret-provider-error')), /configuration/);
  assert.doesNotMatch(mediaErrorMessage(new Error('secret-provider-error')), /secret-provider/);
});

test('human confirmation has its own session state', () => {
  assert.equal(
    deriveVoiceState(snapshot({ awaitingConfirmation: true, executing: true })),
    'confirmation_required'
  );
});
test('only well-formed worker confirmation events expose approval controls', () => {
  const event = {
    type: 'tool',
    id: '1',
    name: 'Reviewed action',
    description: 'Approve the specific action',
    status: 'confirmation_required',
    confirmation_id: 'trusted-request-token-123',
    revision: 2,
  };
  assert.equal(parseWorkerEvent(JSON.stringify(event)).tool.confirmationId, event.confirmation_id);
  assert.equal(parseWorkerEvent(JSON.stringify({ ...event, confirmation_id: null })), null);
  assert.equal(parseWorkerEvent(JSON.stringify({ ...event, revision: -1 })), null);
  assert.equal(parseWorkerEvent(JSON.stringify({ ...event, description: 'x'.repeat(1001) })), null);
});
test('stale snapshots cannot undo completion and actual phases are retained', () => {
  const first = { id: '1', name: 'Calculate expression', status: 'selected', revision: 1 };
  let tools = mergeToolActivities([], first);
  tools = mergeToolActivities(tools, { ...first, status: 'running', revision: 2 });
  tools = mergeToolActivities(tools, { ...first, status: 'completed', revision: 3 });
  tools = mergeToolActivities(tools, { ...first, status: 'running', revision: 2 });
  assert.equal(tools[0].status, 'completed');
  assert.equal(tools[0].phases.join(','), 'selected,running,completed');
});
