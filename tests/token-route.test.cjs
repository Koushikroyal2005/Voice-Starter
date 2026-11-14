// Offline contract checks for the actual route; no LiveKit/network requests.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { createRequire } = require('node:module');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');

const filename = path.resolve(__dirname, '../app/api/token/route.ts');
const code = ts.transpileModule(readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function route(env = {}) {
  const exports = {};
  vm.runInNewContext(
    code,
    {
      exports,
      require: createRequire(filename),
      process: { env },
      Headers,
      console,
    },
    { filename }
  );
  return exports;
}

function environment(extra = {}) {
  return {
    NODE_ENV: 'development',
    LIVEKIT_URL: 'wss://test.livekit.cloud',
    LIVEKIT_API_KEY: 'synthetic-key',
    LIVEKIT_API_SECRET: 'synthetic-secret-for-offline-tests-only',
    ...extra,
  };
}

function request(body = {}) {
  return new Request('http://localhost/api/token', {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  });
}

function claims(token) {
  return JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8'));
}

test('production and preview never issue unauthenticated tokens', async () => {
  for (const IS_VERCEL_PREVIEW of ['false', 'true']) {
    const response = await route(environment({ NODE_ENV: 'production', IS_VERCEL_PREVIEW })).POST(
      request()
    );
    assert.equal(response.status, 403);
  }
});

test('missing development configuration reports variable names', async () => {
  const response = await route({ NODE_ENV: 'development' }).POST(request());
  assert.equal(response.status, 503);
  assert.match(await response.text(), /LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET/);
});

test('named dispatch uses server name and does not return secrets', async () => {
  const env = environment({ AGENT_NAME: ' voice-starter ' });
  const response = await route(env).POST(
    request({
      room_config: { agents: [{ agent_name: 'different-agent' }] },
    })
  );
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  const data = await response.json();
  assert.equal(data.serverUrl, env.LIVEKIT_URL);
  const decoded = claims(data.participantToken);
  assert.equal(decoded.roomConfig.agents[0].agentName, 'voice-starter');
  assert.equal(decoded.video.room, data.roomName);
  assert.ok(decoded.exp - decoded.nbf <= 900);
  assert.ok(!JSON.stringify(data).includes(env.LIVEKIT_API_SECRET));
});

test('automatic dispatch has no named dispatch and retries get fresh rooms', async () => {
  const endpoint = route(environment());
  const first = await (await endpoint.POST(request())).json();
  const second = await (await endpoint.POST(request())).json();
  assert.notEqual(first.roomName, second.roomName);
  assert.notEqual(claims(first.participantToken).sub, claims(second.participantToken).sub);
  assert.equal(claims(first.participantToken).roomConfig?.agents?.length ?? 0, 0);
});

test('invalid JSON is rejected without raw errors', async () => {
  const response = await route(environment()).POST(
    new Request('http://localhost/api/token', {
      method: 'POST',
      body: '{invalid',
    })
  );
  assert.equal(response.status, 400);
  assert.equal(await response.text(), 'Invalid token request.');
});
