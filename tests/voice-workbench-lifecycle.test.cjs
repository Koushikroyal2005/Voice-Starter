const assert = require('node:assert/strict');
const { test, afterEach } = require('node:test');
const React = require('react');
const { createRoot } = require('react-dom/client');
const { JSDOM } = require('jsdom');
const { EventEmitter } = require('node:events');
const { RoomEvent, DisconnectReason } = require('livekit-client');
const { createLoader } = require('./helpers/load-typescript.cjs');
const dom = new JSDOM('<!doctype html><html><body></body></html>');
global.window = dom.window;
global.document = dom.window.document;
global.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = React;
const cleanups = [];
afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
const wireTool = (status = 'running', revision = 1, id = 'tool-1') => ({
  type: 'tool',
  id,
  name: 'Calculate',
  status,
  revision,
});
const config = (id) =>
  JSON.stringify({
    schema_version: 1,
    id,
    name: id,
    description: 'Verified assistant',
    languages: ['en'],
    result_card_types: ['text'],
    notice: '',
  });
async function harness({ connected = true, strict = false, useCaseId } = {}) {
  const room = new EventEmitter();
  const calls = [];
  let disconnects = 0,
    starts = 0,
    ends = 0;
  room.disconnect = async () => {
    disconnects++;
  };
  room.localParticipant = {
    performRpc(args) {
      const response = deferred();
      calls.push({ ...args, ...response });
      return response.promise;
    },
  };
  let session = {
    room,
    connectionState: connected ? 'connected' : 'disconnected',
    isConnected: connected,
    local: {},
    prepareConnection: async () => {},
    start: async () => {
      starts++;
    },
    end: async () => {
      ends++;
    },
  };
  let agent = {
    isConnected: connected,
    identity: 'agent-1',
    state: 'listening',
    attributes: useCaseId ? { 'voice.usecase': useCaseId } : {},
  };
  const load = createLoader({
    '@livekit/components-react': {
      useSessionContext: () => session,
      useAgent: () => agent,
      useSessionMessages: () => ({ messages: [] }),
    },
  });
  const { useVoiceWorkbench } = load('components/voice/use-voice-workbench.ts');
  let voice;
  function Probe() {
    voice = useVoiceWorkbench();
    return null;
  }
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  let mounted = true;
  async function render() {
    await act(async () =>
      root.render(
        strict
          ? React.createElement(React.StrictMode, null, React.createElement(Probe))
          : React.createElement(Probe)
      )
    );
  }
  async function unmount() {
    if (mounted) {
      mounted = false;
      await act(async () => root.unmount());
      host.remove();
    }
  }
  cleanups.push(unmount);
  await render();
  return {
    room,
    calls,
    get voice() {
      return voice;
    },
    get session() {
      return session;
    },
    get starts() {
      return starts;
    },
    get ends() {
      return ends;
    },
    get disconnects() {
      return disconnects;
    },
    async update(s = {}, a = {}) {
      session = { ...session, ...s };
      agent = { ...agent, ...a };
      await render();
    },
    async emit(name, ...args) {
      await act(async () => room.emit(name, ...args));
    },
    async data(event, identity = 'agent-1') {
      await act(async () =>
        room.emit(
          RoomEvent.DataReceived,
          new TextEncoder().encode(JSON.stringify(event)),
          { identity },
          undefined,
          'voice.workbench.v1'
        )
      );
    },
    unmount,
  };
}
async function resolve(call, value) {
  await act(async () => call.resolve(value));
}
function rpc(h, method) {
  return h.calls.filter((c) => c.method === method).at(-1);
}

test('snapshot resolving after native disconnect cannot restore running tools', async () => {
  const h = await harness();
  const pending = rpc(h, 'voice.tools_state');
  await h.data(wireTool());
  await h.emit(RoomEvent.Disconnected, DisconnectReason.CLIENT_INITIATED);
  await resolve(pending, JSON.stringify([wireTool()]));
  assert.equal(h.voice.tools[0].status, 'unknown');
});
test('old snapshot cannot enter a newly started conversation', async () => {
  const h = await harness();
  const old = rpc(h, 'voice.tools_state');
  await act(async () => h.voice.start());
  await resolve(old, JSON.stringify([wireTool()]));
  assert.deepEqual(h.voice.tools, []);
});
test('late use-case response cannot replace new agent configuration', async () => {
  const h = await harness({ useCaseId: 'education' });
  const old = rpc(h, 'voice.usecase_config');
  await h.update({}, { identity: 'agent-2', attributes: { 'voice.usecase': 'finance' } });
  await resolve(rpc(h, 'voice.usecase_config'), config('finance'));
  await resolve(old, config('education'));
  assert.equal(h.voice.useCase.id, 'finance');
});
test('cancel during preparation never starts SDK connection', async () => {
  const h = await harness({ connected: false });
  const preparation = deferred();
  await h.update({ prepareConnection: () => preparation.promise });
  let work;
  await act(async () => {
    work = h.voice.start();
  });
  await act(async () => h.voice.cancelStart());
  await act(async () => {
    preparation.resolve();
    await work;
  });
  assert.equal(h.starts, 0);
  assert.equal(h.voice.control.command, 'idle');
});
test('cancel during connection aborts the native signal', async () => {
  const h = await harness({ connected: false });
  const connection = deferred();
  let signal;
  await h.update({
    start: (options) => {
      signal = options.signal;
      return connection.promise;
    },
  });
  let work;
  await act(async () => {
    work = h.voice.start();
  });
  await act(async () => h.voice.cancelStart());
  assert.equal(signal.aborted, true);
  await act(async () => {
    connection.reject(new Error('aborted'));
    await work;
  });
  assert.equal(h.voice.control.error, null);
});
test('double-start is serialized and text mode disables only microphone acquisition', async () => {
  const h = await harness({ connected: false });
  const connection = deferred();
  const options = [];
  await h.update({
    start: (value) => {
      options.push(value);
      return connection.promise;
    },
  });
  let work;
  await act(async () => {
    work = h.voice.start(true);
    await h.voice.start();
  });
  assert.equal(options.length, 1);
  assert.equal(options[0].tracks.microphone.enabled, false);
  await act(async () => {
    connection.resolve();
    await work;
  });
});
test('double-end is serialized', async () => {
  const h = await harness();
  const ending = deferred();
  let count = 0;
  await h.update({
    end: () => {
      count++;
      return ending.promise;
    },
  });
  let work;
  await act(async () => {
    work = h.voice.end();
    await h.voice.end();
  });
  assert.equal(count, 1);
  assert.equal(h.voice.state, 'disconnecting');
  await act(async () => {
    ending.resolve();
    await work;
  });
});
test('interrupt and end share command exclusion', async () => {
  const h = await harness();
  let work;
  await act(async () => {
    work = h.voice.interrupt();
    await h.voice.end();
  });
  assert.equal(h.ends, 0);
  await act(async () => {
    rpc(h, 'voice.interrupt').resolve('{"interrupted":true}');
    await work;
  });
  assert.equal(h.voice.control.interrupted, true);
});
test('reconnect invalidates pending snapshot and subscribes without duplication', async () => {
  const h = await harness();
  const old = rpc(h, 'voice.tools_state');
  await h.update({ connectionState: 'reconnecting', isConnected: false });
  await h.update({ connectionState: 'connected', isConnected: true });
  await resolve(rpc(h, 'voice.tools_state'), JSON.stringify([wireTool('completed', 3, 'new')]));
  await resolve(old, JSON.stringify([wireTool('running', 1, 'old')]));
  assert.deepEqual(
    h.voice.tools.map((t) => t.id),
    ['new']
  );
  assert.equal(h.room.listenerCount(RoomEvent.DataReceived), 1);
});
test('newer live revision wins over an older snapshot', async () => {
  const h = await harness();
  await h.data(wireTool('completed', 3));
  await resolve(rpc(h, 'voice.tools_state'), JSON.stringify([wireTool('running', 1)]));
  assert.equal(h.voice.tools[0].status, 'completed');
});
test('unmount removes every subscription exactly once and ignores pending responses', async () => {
  const h = await harness();
  const removed = [];
  h.room.on('removeListener', (event) => removed.push(event));
  await h.unmount();
  await resolve(rpc(h, 'voice.tools_state'), JSON.stringify([wireTool()]));
  for (const event of [
    RoomEvent.DataReceived,
    RoomEvent.MediaDevicesError,
    RoomEvent.Disconnected,
    RoomEvent.ConnectionStateChanged,
  ]) {
    assert.equal(h.room.listenerCount(event), 0);
    assert.equal(removed.filter((name) => name === event).length, 1);
  }
});
test('Strict Mode effect replay leaves exactly one active listener and no stale snapshot', async () => {
  const h = await harness({ strict: true });
  const snapshots = h.calls.filter((c) => c.method === 'voice.tools_state');
  assert.equal(snapshots.length, 2);
  await resolve(snapshots[1], JSON.stringify([wireTool('completed', 2, 'current')]));
  await resolve(snapshots[0], JSON.stringify([wireTool('running', 1, 'disposed')]));
  assert.deepEqual(
    h.voice.tools.map((t) => t.id),
    ['current']
  );
  assert.equal(h.room.listenerCount(RoomEvent.DataReceived), 1);
});
test('permission failure disconnects and provides text fallback guidance', async () => {
  const h = await harness({ connected: false });
  const error = new Error('private');
  error.name = 'NotAllowedError';
  await h.update({
    start: async () => {
      throw error;
    },
  });
  await act(async () => h.voice.start());
  assert.match(h.voice.control.error, /Microphone access denied/);
  assert.equal(h.disconnects, 1);
});
test('RPC timeout is safe feedback and snapshots remain optional', async () => {
  const h = await harness();
  await act(async () => rpc(h, 'voice.tools_state').reject(new Error('timeout')));
  assert.equal(h.voice.control.error, null);
  let work;
  await act(async () => {
    work = h.voice.interrupt();
  });
  await act(async () => {
    rpc(h, 'voice.interrupt').reject(new Error('secret'));
    await work;
  });
  assert.match(h.voice.control.error, /could not confirm interruption/);
  assert.doesNotMatch(h.voice.control.error, /secret/);
});
test('late confirmation response cannot initiate another snapshot in a changed session', async () => {
  const h = await harness();
  let work;
  await act(async () => {
    work = h.voice.confirmTool('confirmation-token-12345', true).catch(() => {});
  });
  const confirmation = rpc(h, 'voice.confirm_tool');
  await h.update({}, { identity: 'agent-2' });
  const before = h.calls.length;
  await resolve(confirmation, '{"accepted":true}');
  const after = h.calls.length;
  // Drain an incorrectly launched follow-up too, so a regression fails rather than hangs.
  for (const call of h.calls.slice(before)) await resolve(call, '[]');
  await act(async () => work);
  assert.equal(after, before);
});
test('late interrupt acknowledgement cannot mark a disconnected session interrupted', async () => {
  const h = await harness();
  let work;
  await act(async () => {
    work = h.voice.interrupt();
  });
  await h.emit(RoomEvent.Disconnected, DisconnectReason.CLIENT_INITIATED);
  await act(async () => {
    rpc(h, 'voice.interrupt').resolve('{"interrupted":true}');
    await work;
  });
  assert.equal(h.voice.control.interrupted, false);
});

test('native connection-change then disconnect retains reason handling', async () => {
  const h = await harness();
  await h.data(wireTool());
  await h.emit(RoomEvent.ConnectionStateChanged, 'disconnected');
  await resolve(rpc(h, 'voice.tools_state'), JSON.stringify([wireTool()]));
  await h.emit(RoomEvent.Disconnected, DisconnectReason.SIGNAL_CLOSE);
  assert.equal(h.voice.tools[0].status, 'unknown');
  assert.match(h.voice.control.error, /Session disconnected/);
  assert.equal(h.room.listenerCount(RoomEvent.DataReceived), 0);
});
test('end invalidates RPCs before native disconnect and removes pending approvals', async () => {
  const h = await harness();
  const old = rpc(h, 'voice.tools_state');
  await h.data({
    ...wireTool('confirmation_required'),
    confirmation_id: 'confirmation-token-12345',
  });
  const ending = deferred();
  await h.update({ end: () => ending.promise });
  let work;
  await act(async () => {
    work = h.voice.end();
  });
  await resolve(old, JSON.stringify([wireTool()]));
  assert.equal(h.voice.tools[0].status, 'unknown');
  assert.equal(h.voice.tools[0].confirmationId, undefined);
  await act(async () => {
    ending.resolve();
    await work;
  });
});
test('revisionless snapshot cannot overwrite live progress received while pending', async () => {
  const h = await harness();
  await h.data({ ...wireTool('completed'), revision: undefined });
  await resolve(
    rpc(h, 'voice.tools_state'),
    JSON.stringify([{ ...wireTool(), revision: undefined }])
  );
  assert.equal(h.voice.tools[0].status, 'completed');
});
test('snapshot with a genuinely newer revision can advance a live update', async () => {
  const h = await harness();
  await h.data(wireTool('running', 1));
  await resolve(rpc(h, 'voice.tools_state'), JSON.stringify([wireTool('completed', 2)]));
  assert.equal(h.voice.tools[0].status, 'completed');
});
test('unmount during preparation prevents a late SDK start; an actual remount works', async () => {
  const h = await harness({ connected: false });
  const preparation = deferred();
  await h.update({ prepareConnection: () => preparation.promise });
  let work;
  await act(async () => {
    work = h.voice.start();
  });
  await h.unmount();
  await act(async () => {
    preparation.resolve();
    await work;
  });
  assert.equal(h.starts, 0);
  const remounted = await harness({ strict: true, connected: false });
  await act(async () => remounted.voice.start(true));
  assert.equal(remounted.starts, 1);
});
test('current confirmation refreshes tools, but stale failures are ignored', async () => {
  const h = await harness();
  let first;
  await act(async () => {
    first = h.voice.confirmTool('confirmation-token-12345', false);
  });
  await resolve(rpc(h, 'voice.confirm_tool'), '{"accepted":true}');
  await act(async () => {
    rpc(h, 'voice.tools_state').resolve('[]');
    await first;
  });
  let stale;
  await act(async () => {
    stale = h.voice.confirmTool('confirmation-token-12345', true);
  });
  const pending = rpc(h, 'voice.confirm_tool');
  await h.update({}, { identity: 'agent-2' });
  await act(async () => {
    pending.reject(new Error('expired'));
    await stale;
  });
  assert.equal(h.voice.control.error, null);
});
test('late config failure after disconnect cannot replace the default notice', async () => {
  const h = await harness({ useCaseId: 'education' });
  const old = rpc(h, 'voice.usecase_config');
  await h.emit(RoomEvent.Disconnected, DisconnectReason.CLIENT_INITIATED);
  await act(async () => old.reject(new Error('private')));
  assert.equal(h.voice.useCase.id, 'general_assistant');
  assert.equal(h.voice.useCase.notice, '');
});
test('authenticated events preserve result cards and reject other senders', async () => {
  const h = await harness();
  const event = {
    type: 'result',
    id: 'result-1',
    title: 'Study plan',
    text: 'Review',
    card_type: 'study_plan',
    data: { topic: 'Math' },
  };
  await h.data(event, 'stranger');
  assert.deepEqual(h.voice.results, []);
  await h.data(event);
  assert.equal(h.voice.results[0].cardType, 'study_plan');
  assert.equal(h.voice.results[0].data.topic, 'Math');
});

test('room replacement fences old commands, snapshots and subscriptions', async () => {
  const h = await harness();
  const oldSnapshot = rpc(h, 'voice.tools_state');
  const oldStart = h.voice.start;
  const room = new EventEmitter();
  const requests = [];
  room.disconnect = async () => {};
  room.localParticipant = {
    performRpc(args) {
      const d = deferred();
      requests.push({ ...args, ...d });
      return d.promise;
    },
  };
  await h.update({ room });
  assert.equal(h.room.listenerCount(RoomEvent.DataReceived), 0);
  assert.equal(room.listenerCount(RoomEvent.DataReceived), 1);
  await resolve(oldSnapshot, JSON.stringify([wireTool()]));
  assert.deepEqual(h.voice.tools, []);
  await act(async () => oldStart());
  assert.equal(h.starts, 0);
  await h.unmount();
  assert.equal(room.listenerCount(RoomEvent.DataReceived), 0);
});
test('an invalidated interrupt cannot clear errors in the next session', async () => {
  const h = await harness();
  let pending;
  await act(async () => {
    pending = h.voice.interrupt();
  });
  const response = rpc(h, 'voice.interrupt');
  await h.update({}, { identity: 'agent-2' });
  await h.data({ type: 'error', code: 'provider_unavailable' }, 'agent-2');
  const error = h.voice.control.error;
  await act(async () => {
    response.reject(new Error('old failure'));
    await pending;
  });
  assert.equal(h.voice.control.error, error);
  assert.equal(h.voice.control.command, 'idle');
});
test('only the latest issued snapshot applies when confirmations overlap', async () => {
  const h = await harness();
  let first, second;
  await act(async () => {
    first = h.voice.confirmTool('confirmation-token-11111', true);
  });
  await resolve(rpc(h, 'voice.confirm_tool'), '{"accepted":true}');
  const old = rpc(h, 'voice.tools_state');
  await act(async () => {
    second = h.voice.confirmTool('confirmation-token-22222', false);
  });
  await resolve(rpc(h, 'voice.confirm_tool'), '{"accepted":true}');
  await act(async () => {
    rpc(h, 'voice.tools_state').resolve(JSON.stringify([wireTool('completed', 3, 'new')]));
    await second;
  });
  await act(async () => {
    old.resolve(JSON.stringify([wireTool('running', 1, 'old')]));
    await first;
  });
  assert.deepEqual(
    h.voice.tools.map((tool) => tool.id),
    ['new']
  );
});
test('native connection transitions do not cancel the command that is starting', async () => {
  const h = await harness({ connected: false });
  const connection = deferred();
  let signal;
  await h.update({
    start(options) {
      signal = options.signal;
      return connection.promise;
    },
  });
  let pending;
  await act(async () => {
    pending = h.voice.start();
  });
  await h.update({ connectionState: 'connecting' });
  await h.update({ connectionState: 'connected', isConnected: true }, { isConnected: true });
  await act(async () => {
    connection.resolve();
    await pending;
  });
  assert.equal(signal.aborted, false);
  assert.equal(h.voice.control.command, 'idle');
  assert.equal(h.voice.state, 'listening');
});

test('failed native end restores synchronization without reviving old RPCs', async () => {
  const h = await harness();
  const old = rpc(h, 'voice.tools_state');
  await h.update({
    end: async () => {
      throw new Error('network');
    },
  });
  await act(async () => h.voice.end());
  assert.match(h.voice.control.error, /Connection or browser audio failed/);
  assert.equal(h.room.listenerCount(RoomEvent.DataReceived), 1);
  await resolve(old, JSON.stringify([wireTool('running', 1, 'stale')]));
  await h.data(wireTool('completed', 2, 'current'));
  assert.deepEqual(
    h.voice.tools.map((t) => t.id),
    ['current']
  );
});
