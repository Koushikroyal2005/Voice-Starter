// Real Python serializer/handler corpus; deterministic test IO, no providers.
import { execFileSync } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const backend = path.join(root, 'backend');
const python = path.join(
  backend,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'
);
const raw = execFileSync(python, ['tests/export_workbench_fixtures.py'], {
  cwd: backend,
  env: { ...process.env, PYTHONPATH: backend, PYTHONUTF8: '1' },
  encoding: 'utf8',
  timeout: 60000,
});
const output = JSON.stringify(JSON.parse(raw), null, 2) + '\n';
const target = path.join(root, 'contracts/voice-workbench/v1/fixtures.json');
if (process.argv.includes('--check')) {
  if ((await readFile(target, 'utf8')) !== output)
    throw new Error('Python workbench fixtures drifted.');
} else await writeFile(target, output);
process.stdout.write('Python workbench fixture agreement verified.\n');
