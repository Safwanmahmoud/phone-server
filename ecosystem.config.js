// PM2 processes that make up the dashboard. Deployed apps get their own
// generated files under ~/.phone-server/apps/<name>/pm2.json.
const path = require('path');

const HOME = process.env.HOME;
const PREFIX = process.env.PREFIX || '/data/data/com.termux/files/usr';
const ROOT = __dirname;
const DATA = process.env.PS_DATA || path.join(HOME, '.phone-server');
const PS_PORT = process.env.PS_PORT || '8080';
const PS_DASHBOARD_PORT = process.env.PS_DASHBOARD_PORT || '8000';

const env = { PS_DATA: DATA, PS_PORT, PS_DASHBOARD_PORT };
const logs = (name) => ({
  out_file: path.join(DATA, 'logs', `${name}.log`),
  error_file: path.join(DATA, 'logs', `${name}.log`),
  merge_logs: true,
  time: true,
});

module.exports = {
  apps: [
    {
      name: 'ps-dashboard',
      cwd: ROOT,
      script: path.join(ROOT, '.venv/bin/python'),
      args: ['-m', 'uvicorn', 'server.main:app', '--host', '127.0.0.1', '--port', PS_DASHBOARD_PORT,
        '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1', '--no-access-log'],
      interpreter: 'none',
      env,
      restart_delay: 2000,
      ...logs('dashboard'),
    },
    {
      name: 'ps-agent',
      cwd: ROOT,
      script: path.join(ROOT, 'agent/pm2-agent.js'),
      env,
      restart_delay: 3000,
      ...logs('agent'),
    },
    {
      name: 'ps-caddy',
      cwd: ROOT,
      script: path.join(PREFIX, 'bin/caddy'),
      args: ['run', '--config', path.join(ROOT, 'Caddyfile'), '--adapter', 'caddyfile'],
      interpreter: 'none',
      env: {
        ...env,
        XDG_DATA_HOME: path.join(DATA, 'caddy', 'data'),
        XDG_CONFIG_HOME: path.join(DATA, 'caddy', 'config'),
      },
      restart_delay: 2000,
      ...logs('caddy'),
    },
    {
      name: 'ps-terminal',
      cwd: HOME,
      script: path.join(ROOT, 'scripts/run-terminal.sh'),
      interpreter: path.join(PREFIX, 'bin/bash'),
      env,
      restart_delay: 2000,
      ...logs('terminal'),
    },
  ],
};
