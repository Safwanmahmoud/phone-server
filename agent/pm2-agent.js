// Keeps PM2's API loaded and connected so the dashboard doesn't pay Node + PM2's
// start-up cost (often 5–15 seconds on a phone) for every status check.
//
// Protocol: connect to the Unix socket, send one JSON line {"op": "...", ...},
// get one JSON line back: {"ok": true, "result": ...} or {"ok": false, "error": "..."}.
'use strict';

const fs = require('fs');
const net = require('net');
const path = require('path');

const PREFIX = process.env.PREFIX || '/data/data/com.termux/files/usr';
const DATA = process.env.PS_DATA || path.join(process.env.HOME, '.phone-server');
const SOCK = path.join(DATA, 'pm2-agent.sock');

// Processes started through this API inherit our environment, so drop
// everything PM2 and the shell that started us added (same list as config.py).
const KEEP = new Set(['HOME', 'PATH', 'PREFIX', 'TMPDIR', 'LANG', 'LC_ALL', 'TERM', 'SHELL', 'USER',
  'LD_PRELOAD', 'LD_LIBRARY_PATH', 'PM2_HOME', 'BOOTCLASSPATH', 'DEX2OATBOOTCLASSPATH',
  'SYSTEMSERVERCLASSPATH', 'EXTERNAL_STORAGE', 'ASEC_MOUNTPOINT']);
for (const key of Object.keys(process.env)) {
  if (!KEEP.has(key) && !key.startsWith('ANDROID_') && !key.startsWith('TERMUX')) delete process.env[key];
}

const pm2 = require(path.join(PREFIX, 'lib/node_modules/pm2'));

const call = (method, ...args) => new Promise((resolve, reject) => {
  pm2[method](...args, (err, res) => (err ? reject(err) : resolve(res)));
});

const errorText = (e) => {
  if (Array.isArray(e)) return e.map(errorText).join('; ');
  return (e && (e.message || e.msg)) || String(e);
};

const ops = {
  list: async () => (await call('list')).map((p) => ({
    name: p.name,
    pid: p.pid,
    monit: p.monit,
    pm2_env: {
      status: p.pm2_env && p.pm2_env.status,
      pm_uptime: p.pm2_env && p.pm2_env.pm_uptime,
      restart_time: p.pm2_env && p.pm2_env.restart_time,
    },
  })),
  start: async ({ file }) => { await call('start', file); return true; },
  stop: async ({ name }) => { await call('stop', name); return true; },
  restart: async ({ name }) => { await call('restart', name); return true; },
  delete: async ({ name }) => { await call('delete', name); return true; },
  save: async () => { await call('dump', true); return true; },
};

pm2.connect((err) => {
  if (err) {
    console.error('Could not connect to PM2:', errorText(err));
    process.exit(1);
  }
  try { fs.unlinkSync(SOCK); } catch { /* not there */ }

  const server = net.createServer((conn) => {
    let buf = '';
    conn.setEncoding('utf8');
    conn.on('error', () => {});
    conn.on('data', async (chunk) => {
      buf += chunk;
      const nl = buf.indexOf('\n');
      if (nl < 0) return;
      const line = buf.slice(0, nl);
      buf = '';
      let reply;
      try {
        const req = JSON.parse(line);
        const op = ops[req.op];
        if (!op) throw new Error(`unknown op: ${req.op}`);
        reply = { ok: true, result: await op(req) };
      } catch (e) {
        reply = { ok: false, error: errorText(e) };
      }
      conn.end(`${JSON.stringify(reply)}\n`);
    });
  });

  server.listen(SOCK, () => {
    fs.chmodSync(SOCK, 0o600);
    console.log(`PM2 agent ready on ${SOCK}`);
  });
});

const shutdown = () => {
  try { fs.unlinkSync(SOCK); } catch { /* gone */ }
  pm2.disconnect();
  process.exit(0);
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
