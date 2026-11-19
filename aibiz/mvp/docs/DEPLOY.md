# Deployment, backups and rollback

> **Approval first.** Deploying publicly, connecting a client's accounts or turning on any paid
> service needs your explicit approval and the client's written agreement (including a data
> processing agreement). Until then, run it locally.

## 1. Local demo (no server)

Run `./run_demo.sh` on the MacBook, then show the chat and the admin page side by side. This is
all a sales demo needs.

## 2. Pilot on one small server (after approval)

These instructions are for Ubuntu 24.04 with Caddy. Adapt the paths to your server. They have
**not** been run on a real server from this repository yet; do a dry run on a throwaway server first.

```bash
# as root on the server
adduser --system --group quotebook
mkdir -p /opt/quotebook && cd /opt/quotebook
git clone <repo-url> app && cd app && git checkout <release-tag>
mkdir -p /var/lib/quotebook && chown quotebook: /var/lib/quotebook
install -m 600 -o root -g root /dev/null /etc/quotebook.env
echo "QB_ADMIN_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> /etc/quotebook.env
cp aibiz/mvp/config/demo_detailing.json /etc/quotebook-client.json   # then edit for the client
```

`/etc/systemd/system/quotebook.service`:

```ini
[Unit]
Description=Quotebook assistant
After=network.target

[Service]
User=quotebook
WorkingDirectory=/opt/quotebook/app/aibiz/mvp
EnvironmentFile=/etc/quotebook.env
ExecStartPre=/usr/bin/python3 -m quotebook --config /etc/quotebook-client.json --db /var/lib/quotebook/q.sqlite3 --var /var/lib/quotebook init
ExecStart=/usr/bin/python3 -m quotebook --config /etc/quotebook-client.json --db /var/lib/quotebook/q.sqlite3 --var /var/lib/quotebook serve --host 127.0.0.1 --port 8000 --trust-proxy --secure-cookies
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/quotebook

[Install]
WantedBy=multi-user.target
```

Add a second unit, `quotebook-jobs.service`, with the same settings and
`ExecStart=... jobs --loop 60`.

`/etc/caddy/Caddyfile` (Caddy obtains the HTTPS certificate itself):

```
booking.example-client.hr {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
systemctl daemon-reload && systemctl enable --now quotebook quotebook-jobs caddy
curl -s https://booking.example-client.hr/healthz     # {"ok": true, ...}
```

## 3. Backups

```bash
# /etc/cron.d/quotebook-backup: daily at 03:15, keep 30 days
15 3 * * * quotebook cd /opt/quotebook/app/aibiz/mvp && python3 -m quotebook --db /var/lib/quotebook/q.sqlite3 --var /var/lib/quotebook backup && find /var/lib/quotebook/backups -name '*.sqlite3' -mtime +30 -delete
```

Copy the backup folder off the server. Encrypt it first, because it contains customer contact
details. Test a restore once a month on your laptop with `python3 -m quotebook --db test.sqlite3
restore <file>`.

## 4. Monitoring

- **Health check:** an uptime checker calls `/healthz` every 5 minutes. A free tier is enough.
- **Escalations:** the admin page's "Needs you" list includes failed messages. Look at it daily
  during a pilot.
- **Logs:** `journalctl -u quotebook -u quotebook-jobs`. Logs are JSON, with phone numbers and
  e-mails masked.

## 5. Upgrading

1. Stop the service: `systemctl stop quotebook quotebook-jobs`.
2. Update the code: `cd /opt/quotebook/app && git fetch && git checkout <new-tag>`.
3. Run the tests: `cd aibiz/mvp && python3 -m unittest discover -s tests -t .`
4. Start the service: `systemctl start quotebook quotebook-jobs`. `init` runs first and migrates
   the database. Before changing the schema it saves a backup as
   `/var/lib/quotebook/backups/pre-migrate-v<old>-<time>.sqlite3`.
5. Check it: `curl /healthz`, then make one test booking on a blocked day and cancel it.

## 6. Rollback

Use this when an upgrade misbehaves:

1. Stop the service: `systemctl stop quotebook quotebook-jobs`.
2. Go back to the previous code: `cd /opt/quotebook/app && git checkout <previous-tag>`.
3. Restore the database, but **only if the upgrade changed the schema**. A newer schema makes the
   old code refuse to start with "database schema vN is newer than this code":

   ```bash
   cd aibiz/mvp && python3 -m quotebook --db /var/lib/quotebook/q.sqlite3 restore /var/lib/quotebook/backups/pre-migrate-v<old>-<time>.sqlite3
   ```

   Bookings made between the upgrade and the rollback are in the newer database only. Export them
   from the admin page or the `.ics` file first, and re-enter them by hand.
4. Start the service: `systemctl start quotebook quotebook-jobs`, then check `/healthz` and the
   admin page.
5. Tell the client what happened and whether any customer needs a call.

To stop the assistant immediately without any rollback, press **"Pauziraj asistenta"** in the
admin page. Every new inquiry then goes to the owner.
