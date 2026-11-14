// Conservative heuristic, not a proof that every possible credential is absent.
// Prints paths only, never matched values. --history scans all reachable Git refs.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const pattern =
  'AKIA[0-9A-Z]{16}|sk-(proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----';
const secret = new RegExp(pattern);
const files = execFileSync('git', ['ls-files', '-z'], { encoding: 'utf8' })
  .split('\0')
  .filter(Boolean);
const findings = [];
for (const file of files) {
  if (/(^|\/)\.env(\.|$)/.test(file) && !file.endsWith('.example')) findings.push(file);
  const content = readFileSync(file);
  if (!content.includes(0) && secret.test(content.toString('utf8'))) findings.push(file);
}
if (process.argv.includes('--history')) {
  const revisions = execFileSync('git', ['rev-list', '--all'], { encoding: 'utf8' })
    .trim()
    .split('\n')
    .filter(Boolean);
  for (const revision of revisions) {
    try {
      const paths = execFileSync('git', ['grep', '-I', '-l', '-E', '-e', pattern, revision, '--'], {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      findings.push(...paths.trim().split('\n').filter(Boolean));
    } catch (error) {
      if (error.status !== 1) throw new Error('Git history scan failed (details withheld).');
    }
    const names = execFileSync('git', ['ls-tree', '-r', '--name-only', revision], {
      encoding: 'utf8',
    }).split('\n');
    findings.push(
      ...names
        .filter((name) => /(^|\/)\.env(\.|$)/.test(name) && !name.endsWith('.example'))
        .map((name) => `${revision}:${name}`)
    );
  }
}
if (findings.length) {
  console.error(
    'Review possible tracked secrets (paths only):\n' + [...new Set(findings)].join('\n')
  );
  process.exitCode = 1;
} else
  console.log(
    'No matching tracked secret patterns or non-example .env files. Heuristic only; review generic credentials separately.'
  );
