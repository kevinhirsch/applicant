// workspace/tests/visual/boot.js
//
// Boots the front-door for a visual run, hermetically: a FRESH SQLite
// data dir, a fixed admin login, and ENGINE_URL pointed at an unreachable
// port (the engine-offline states are the pinned baselines; see surfaces.js).
// Lifted from the CLAUDE.md local-boot recipe (setup.py → uvicorn) so the
// harness runs the same server a playtest does.
//
// SAFETY: the harness only wipes workspace/data when the dir is absent or
// carries the `.visual-harness` marker a previous harness boot left — it will
// refuse to touch a data dir that belongs to a real dev instance.

'use strict';

const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');

const WORKSPACE_DIR = path.resolve(__dirname, '..', '..');
const DATA_DIR = path.join(WORKSPACE_DIR, 'data');
const MARKER = path.join(DATA_DIR, '.visual-harness');

const ADMIN_USER = 'admin';
const ADMIN_PASSWORD = 'visual-harness-1234';

// Python launcher: `uv run --project <repo-root> python` resolves the repo
// env (workspace deps are installed there per CLAUDE.md) even though the cwd
// is workspace/ (whose own pyproject.toml has no project table); override
// with VISUAL_PY="python3" etc.
function _pyLauncher() {
  const raw = process.env.VISUAL_PY
    || `uv run --project ${path.resolve(WORKSPACE_DIR, '..')} python`;
  const parts = raw.split(/\s+/).filter(Boolean);
  return { cmd: parts[0], args: parts.slice(1) };
}

function _freshDataDir() {
  if (fs.existsSync(DATA_DIR)) {
    if (!fs.existsSync(MARKER)) {
      throw new Error(
        `${DATA_DIR} exists and has no ${path.basename(MARKER)} marker — it looks like a real ` +
        'dev instance. Move it aside (or run against it with --base URL) instead of letting ' +
        'the harness wipe it.'
      );
    }
    fs.rmSync(DATA_DIR, { recursive: true, force: true });
  }
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(MARKER, 'created by workspace/tests/visual — safe to delete\n');
}

function _env(port) {
  return {
    ...process.env,
    DATABASE_URL: `sqlite:///${path.join(DATA_DIR, 'app.db')}`,
    // Unreachable on purpose: surfaces pin their honest offline/gated states.
    ENGINE_URL: process.env.VISUAL_ENGINE_URL || 'http://127.0.0.1:1',
    APPLICANT_ADMIN_USER: ADMIN_USER,
    APPLICANT_ADMIN_PASSWORD: ADMIN_PASSWORD,
    PORT: String(port),
  };
}

function _waitHTTP(url, timeoutMs = 90000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) return resolve();
        retry();
      });
      req.on('error', retry);
      req.setTimeout(2000, () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) return reject(new Error(`front-door not up after ${timeoutMs}ms at ${url}`));
      setTimeout(tick, 500);
    };
    tick();
  });
}

function _assertPortFree(port) {
  // Two concurrent harness instances would share one server and wipe each
  // other's data dir mid-walk — every capture after that is garbage. Refuse
  // to boot when something already listens on the port.
  return new Promise((resolve, reject) => {
    const req = http.get(`http://127.0.0.1:${port}/`, (res) => {
      res.resume();
      reject(new Error(`port ${port} is already serving — another harness instance (or a dev server) is up; stop it or pass --port/--base`));
    });
    req.on('error', () => resolve());
    req.setTimeout(1500, () => { req.destroy(); resolve(); });
  });
}

/**
 * Boot a fresh front-door on `port`. Returns { base, user, password, stop() }.
 */
async function bootFrontDoor(port, log = console.error) {
  const { cmd, args } = _pyLauncher();
  await _assertPortFree(port);
  _freshDataDir();

  log(`[boot] setup.py (fresh SQLite in ${DATA_DIR}) ...`);
  const setup = spawnSync(cmd, [...args, 'setup.py'], {
    cwd: WORKSPACE_DIR, env: _env(port), encoding: 'utf8', timeout: 180000,
  });
  if (setup.status !== 0) {
    throw new Error(`setup.py failed (${setup.status}):\n${(setup.stderr || setup.stdout || '').slice(-2000)}`);
  }

  log(`[boot] uvicorn app:app on 127.0.0.1:${port} ...`);
  const server = spawn(cmd, [...args, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', String(port)], {
    cwd: WORKSPACE_DIR, env: _env(port), stdio: ['ignore', 'pipe', 'pipe'],
  });
  let serverLog = '';
  const capture = (buf) => { serverLog = (serverLog + buf.toString()).slice(-8000); };
  server.stdout.on('data', capture);
  server.stderr.on('data', capture);
  // A mid-walk server death must fail LOUD with the server's own last words —
  // otherwise it surfaces only as an opaque "socket hang up" on the next
  // login and the actual crash is lost.
  let stopping = false;
  server.on('exit', (code, signal) => {
    if (stopping) return;
    log(`[boot] uvicorn DIED mid-run (code=${code} signal=${signal}) — last server output:\n${serverLog.slice(-3000)}`);
  });
  const died = new Promise((_, rej) => server.on('exit', (code) => rej(new Error(`uvicorn exited (${code}):\n${serverLog.slice(-2000)}`))));

  await Promise.race([_waitHTTP(`http://127.0.0.1:${port}/login`), died]);
  log('[boot] front-door is up');

  return {
    base: `http://127.0.0.1:${port}`,
    user: ADMIN_USER,
    password: ADMIN_PASSWORD,
    stop: () => new Promise((resolve) => {
      stopping = true;
      server.removeAllListeners('exit');
      server.on('exit', () => resolve());
      server.kill('SIGTERM');
      setTimeout(() => { try { server.kill('SIGKILL'); } catch (_) { /* gone */ } resolve(); }, 5000);
    }),
  };
}

module.exports = { bootFrontDoor, ADMIN_USER, ADMIN_PASSWORD, WORKSPACE_DIR };
