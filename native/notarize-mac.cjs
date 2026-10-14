// Release-only approval of an existing signed installer; no rebuild required.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
function run(command, args, capture = false) {
  const result = spawnSync(command, args, { encoding: 'utf8', stdio: capture ? 'pipe' : 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} failed (${result.status}). ${capture ? result.stderr : ''}`);
  return capture ? JSON.parse(result.stdout) : undefined;
}
function main() {
  if (process.argv[2] !== 'Release') throw new Error('Explicit Release configuration required');
  if (process.platform !== 'darwin') throw new Error('Apple approval must run on macOS');
  const profile = process.env.SHAS_NOTARY_PROFILE;
  if (!profile) throw new Error('SHAS_NOTARY_PROFILE must name the existing saved Keychain profile');
  const image = path.resolve(process.env.SHAS_MAC_INSTALLER || path.join(root, 'release/Shas-Master-Native-macOS-arm64.dmg'));
  const record = `${image}.notarization.json`;
  const auth = ['--keychain-profile', profile];
  if (process.env.SHAS_NOTARY_KEYCHAIN) auth.push('--keychain', process.env.SHAS_NOTARY_KEYCHAIN);
  const stat = fs.statSync(image);
  let state;
  if (fs.existsSync(record)) {
    state = JSON.parse(fs.readFileSync(record, 'utf8'));
    if (state.image !== image) throw new Error('Saved submission belongs to another installer');
    if (!state.id) throw new Error('An upload was interrupted before its tracking number was saved. Check notarytool history before another submission.');
    if (state.bytes !== stat.size || state.modified !== stat.mtimeMs) {
      throw new Error('Installer changed since submission; preserve the saved record and resolve the old submission first');
    }
  } else {
    run('codesign', ['--verify', '--strict', image]);
    // Exclusive creation prevents a concurrent or interrupted invocation uploading twice.
    state = { image, bytes: stat.size, modified: stat.mtimeMs, started: new Date().toISOString() };
    fs.writeFileSync(record, JSON.stringify(state, null, 2), { flag: 'wx', mode: 0o600 });
    const submission = run('xcrun', ['notarytool', 'submit', image, ...auth, '--no-wait', '--output-format', 'json'], true);
    if (!submission.id) throw new Error('Apple returned no tracking number; check submission history');
    state.id = submission.id;
    fs.writeFileSync(record, JSON.stringify(state, null, 2));
  }
  console.log(`Apple submission: ${state.id}`);
  const result = run('xcrun', ['notarytool', 'info', state.id, ...auth, '--output-format', 'json'], true);
  console.log(`Apple status: ${result.status}`);
  if (result.status === 'In Progress') {
    console.log('Processing continues at Apple. Run this same command again to check this submission.');
    process.exitCode = 2;
    return;
  }
  if (result.status !== 'Accepted') throw new Error(`Apple did not approve the installer. Retrieve its report with notarytool log ${state.id}.`);
  state.accepted = true;
  fs.writeFileSync(record, JSON.stringify(state, null, 2));
  run('xcrun', ['stapler', 'staple', image]);
  const stapled = fs.statSync(image);
  state.bytes = stapled.size;
  state.modified = stapled.mtimeMs;
  fs.writeFileSync(record, JSON.stringify(state, null, 2));
  run('xcrun', ['stapler', 'validate', image]);
  run('codesign', ['--verify', '--strict', image]);
  run('spctl', ['--assess', '--type', 'open', '--context', 'context:primary-signature', '--verbose=2', image]);
  console.log('Apple approval attached and installer assessment passed.');
}
try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
