# Phone Server

A small self-hosted dashboard for running Python and Node.js apps on an Android phone, inside Termux.

From the dashboard you can:

- **Overview**: see memory, storage, CPU clock speed, temperatures, battery, and the state of every app.
- **Apps**: deploy from a Git repository. The phone clones it, installs `requirements.txt`, starts the
  app, and checks that it answers. After that you can redeploy, start, stop, restart, read live logs,
  see each deploy's output, and edit the start command, port and environment variables.
- **Terminal**: open a shell on the phone in the browser.
- **Settings**: create the phone's SSH key for GitHub, connect Cloudflare so apps can have public
  domains, change the theme, sign out.

You reach it over [Tailscale](https://tailscale.com) at `http://<phone>:8080`, where `<phone>` is the
phone's name on your tailnet, for example `http://my-phone:8080`.

It has been used on a mid-range phone (Snapdragon 680, 6 GB RAM, Android 13) to run a few web apps, a
Postgres database and a small language model at once.

## How it fits together

```
 browser ──Tailscale──▶ :8080  Caddy ─┬─▶ 127.0.0.1:8000   dashboard (Starlette + uvicorn)
                                      │                         │
                                      └─▶ /terminal ─▶ ttyd     ├─▶ PM2 bridge ─▶ PM2 daemon ─▶ your apps (:8100+)
                                         (sign-in checked       └─▶ SQLite, logs, app folders
                                          first)                    in ~/.phone-server
```

| Part | What it does |
|---|---|
| `ps-caddy` | The only thing on the network (port 8080). Before it opens the terminal, it asks the dashboard whether you're signed in. |
| `ps-dashboard` | The API and the UI (`server/`, `static/`). It listens on 127.0.0.1 only. |
| `ps-agent` | Keeps PM2's API loaded (`agent/pm2-agent.js`). Starting the `pm2` command takes 5–15 seconds on a phone. The agent answers in milliseconds. |
| `ps-terminal` | ttyd on a Unix socket, so only Caddy can reach it. |
| Your apps | Each is a PM2 process with its own folder, venv and log under `~/.phone-server/apps/<name>/`. Apps get ports from 8100 to 8199 and listen on all interfaces, so you can open them over Tailscale directly. |

The dashboard uses Starlette rather than FastAPI because FastAPI needs `pydantic-core`, which has to
be compiled with Rust on Termux. The two work the same way.

## Install

On the phone, in Termux (installed from F-Droid):

```sh
pkg install -y git
git clone https://github.com/Safwanmahmoud/phone-server ~/phone-server   # or copy it with scripts/push.sh, below
bash ~/phone-server/scripts/install.sh
cd ~/phone-server && .venv/bin/python -m server.cli set-password
```

`install.sh` installs what's missing (Python, Node.js, git, ttyd, Caddy, cloudflared, PM2) and creates the
virtual environment. It then starts the four services and saves them so PM2 can bring them back.
You can run it again to update.

### From your computer

With an SSH host called `phone` in `~/.ssh/config`:

```sh
scripts/push.sh            # copies this folder to ~/phone-server on the phone and runs install.sh
```

## Keep it running (Android)

Android stops apps in the background. To keep the server up:

1. **Battery:** go to Settings → Apps → Termux → Battery and choose **Unrestricted** (on OPPO:
   *Allow background activity*). Do the same for Tailscale.
2. **Wake lock:** pull down the Termux notification and tap **Acquire wakelock**. `boot.sh` does this
   at start-up.
3. **Start on boot:** install **Termux:Boot** from F-Droid and open it once. `install.sh` already put
   `~/.termux/boot/start-phone-server` in place. It starts `sshd` and restores PM2's processes.
4. **Phantom process killer:** Android 12 and later kill background child processes once there are
   more than 32 across all apps. Every app you deploy adds at least one. Turn this off once from a
   computer with `adb` (USB or wireless debugging):

   ```sh
   adb shell "/system/bin/device_config set_sync_disabled_for_tests persistent"
   adb shell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"
   adb shell settings put global settings_enable_monitor_phantom_procs false
   ```

   On Android 14 and later, Developer options → **Disable child process restrictions** does the same.

   **Without a computer:** run `pkg install android-tools` in Termux, then turn on Developer options →
   **Wireless debugging** (Wi-Fi needed). Tap **Pair device with pairing code** and, while that popup is
   open, run `adb pair <ip>:<pairing-port> <code>`. Then run `adb connect <ip>:<port>` with the port
   shown on the Wireless debugging page, and run the commands above. Turn Wireless debugging off
   afterwards. The settings stay after a reboot. On Android 13 only the two `device_config` lines
   matter. ColorOS refuses the `settings put` line unless **Disable permission monitoring** is on, and
   it isn't needed there.
5. **Battery level on the Overview:** install **Termux:API** from F-Droid, then run `pkg install termux-api`.
6. Keep the phone **plugged in**.

## Deploying an app

The app needs to listen on `0.0.0.0:$PORT`. The dashboard sets `PORT` for it.

A repository with a `package.json` and no Python packaging files is treated as **Node.js**. Anything
else is treated as **Python**.

**Node.js:** the phone runs `npm ci` (or `npm install` without a lockfile), with dev dependencies so
build tools like Vite are there. It runs that again only when the lockfile changes. If there's a `build`
script, it runs `npm run build` on every deploy, with the app's environment variables available. The
app runs with `NODE_ENV=production` unless you set it yourself.

**Python:** requirements come from `requirements.txt`, or from `pyproject.toml`/`setup.py` with
`pip install .`, in a venv for each app. They're reinstalled only when `requirements.txt` changes.

To work out how to start the app, the dashboard checks these in order:

1. A `Procfile` with a `web:` line
2. Node.js: the `start` script (a plain `node server.js` runs directly, anything else through
   `npm start`), then `main`, `server.js` or `index.js`
3. Python: FastAPI, Starlette or Quart in `app/main.py`, `main.py`, `app.py` or `server.py` runs
   `python -m uvicorn <module>:app`. Flask runs `gunicorn` if it's installed, otherwise `flask run`.
   Otherwise `python main.py` or `python app.py`.

You can always set your own start command in the app's Settings.

**Private repositories:** go to Settings → GitHub access → *Create a key for this phone*, and add the key at
<https://github.com/settings/ssh/new>. Then use the `git@github.com:you/repo.git` URL.

**Deploying from the terminal:** `cd ~/phone-server && .venv/bin/python -m server.cli deploy <app>`
runs the same pipeline, prints the log, and shows up in the dashboard's deploy history.

### PostgreSQL

To give apps a database on the phone:

```sh
bash ~/phone-server/scripts/setup-postgres.sh                              # once
cd ~/phone-server && .venv/bin/python -m server.cli create-db <app>        # per app
```

The setup script installs PostgreSQL and runs it under PM2 as `ps-postgres`. The cluster lives in
`~/.phone-server/postgres`, listens on 127.0.0.1:5432 only, and is tuned for a phone: small memory,
and as few background processes as possible.
`create-db` makes a database and login named after the app (dashes become underscores), with a random
password. It sets the app's `DATABASE_URL` without printing the password. Redeploy the app, or press
Save in its Settings, to use the new database. `psql -U postgres` works on the phone without a password.
Postgres runs about 9 processes, so turn off the phantom process killer (above).

### Public domains

Apps can be public at your own domains, over HTTPS, through a free
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/).
`cloudflared` makes only outgoing connections, so nothing is opened on your router. It works on mobile
data and doesn't break when your home IP address changes.

1. Add your domain to a free Cloudflare account (**Add a domain**, Free plan).
2. At your registrar, replace the nameservers with the two that Cloudflare shows. On Namecheap: **Domain
   List → Manage → Nameservers → Custom DNS**. Cloudflare copies your existing DNS records when you add the
   domain, so email and other records keep working.
3. Create an API token at **Cloudflare → My Profile → API Tokens → Create Token → Custom token**, with
   *Account · Cloudflare Tunnel · Edit*, *Zone · DNS · Edit* and *Zone · Zone · Read*, for all zones.
4. In the dashboard, paste it in **Settings → Public access**. Add the domain at Cloudflare first: the
   dashboard finds your account through it. You don't have to wait for the nameservers. The dashboard creates a tunnel called
   `phone-server` and runs `cloudflared` under PM2 as `ps-tunnel`.
5. In an app's **Settings** tab, add its domains under **Public domains**, one per line. Add both
   `example.com` and `www.example.com` if you want both. Saving creates the DNS records and sends that
   hostname to the app's port.

If a name already points somewhere else at Cloudflare, the dashboard asks before replacing it. Removing a
domain, or deleting the app, removes only the records the dashboard made. Changing an app's port moves its
domains too.

**Only the domains listed on apps are public.** Cloudflare answers any other name with a 404, and the
dashboard, the terminal and the database are never reachable through the tunnel. The API token is kept in
`~/.phone-server/cloudflare.json` (readable only by Termux).

On Android, `cloudflared` logs `Failed to fetch features` and `Failed to initialize DNS local resolver`,
because Android has no `/etc/resolv.conf`. These are harmless: it finds Cloudflare through a built-in
fallback and connects normally.

**Packages that need Rust** (`pydantic-core`, and so FastAPI; `cryptography`; `orjson`): run
`pkg install rust` first. Expect the first install to take a long time on a phone.

## Security

- One password, set on the phone with `server.cli set-password`. It's stored as PBKDF2-SHA256 with
  600,000 iterations in `~/.phone-server/password.json`. Changing it signs everyone out.
- The session is a signed cookie. Sign-in allows 5 wrong passwords per 10 minutes per address.
- Every request that changes something must carry `X-Requested-With: phone-server`. That stops other
  websites from posting to the dashboard in your browser.
- The terminal is a full shell as the Termux user, so treat the dashboard password like an SSH key.
- The dashboard is plain HTTP. Tailscale encrypts the traffic between your devices, but on your
  home Wi-Fi (`192.168.x.x:8080`) it is not encrypted.

## Layout

```
server/            dashboard (Starlette)
  main.py          routes, sign-in check, exception handlers
  deploy.py        clone/fetch → pip or npm (+ build) → detect start command → PM2 → health check
  pm2.py           talks to the PM2 bridge, or the pm2 command if the bridge is down
  apps.py          validation and API errors
  tunnel.py        Cloudflare Tunnel: API token, cloudflared under PM2, app domains and DNS records
  system.py        memory, storage, CPU clock, temperatures, battery
  db.py            SQLite: apps and deployments
  auth.py, cli.py  password and sign-in
agent/             PM2 bridge (Node)
static/            UI: one HTML page, one script, one stylesheet, no build step
scripts/           install.sh (phone), push.sh (computer), boot.sh, run-terminal.sh
Caddyfile, ecosystem.config.js
```

Data lives in `~/.phone-server` (`PS_DATA`): `phone-server.db`, `apps/<name>/{repo,venv,logs,pm2.json}`,
`logs/` for the dashboard's own services, `password.json`, and `secret.key`.

## License

[MIT](LICENSE)
