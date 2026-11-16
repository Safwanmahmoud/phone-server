// PostgreSQL for apps on this phone. Set up with scripts/setup-postgres.sh.
// Kept apart from ecosystem.config.js so updating the dashboard never restarts the database.
const path = require('path');

const PREFIX = process.env.PREFIX || '/data/data/com.termux/files/usr';
const DATA = process.env.PS_DATA || path.join(process.env.HOME, '.phone-server');

module.exports = {
  apps: [
    {
      name: 'ps-postgres',
      cwd: DATA,
      script: path.join(PREFIX, 'bin/postgres'),
      args: ['-D', path.join(DATA, 'postgres')],
      interpreter: 'none',
      kill_timeout: 20000, // SIGINT is a fast shutdown; give it time to finish
      restart_delay: 3000,
      out_file: path.join(DATA, 'logs', 'postgres.log'),
      error_file: path.join(DATA, 'logs', 'postgres.log'),
      merge_logs: true,
      time: true,
    },
  ],
};
