# Quotebook MVP: inquiry → estimate → booking assistant

A working demonstration of the flagship offer for quote-based service businesses (car detailing,
cleaning, small trades). A customer writes in Croatian or English. The assistant asks the few
questions it needs, gives an **estimated price range** from the business's own rules and offers
**real free times**. It then sends the request to the owner, who confirms with one tap.

**What this is:**

- Python standard library and SQLite only. Python 3.9+ works, including the one on a Mac.
- No accounts and no paid services.
- Simulated data only. The two demo businesses in `config/` are fictional.
- **Nothing is ever sent.** The only message sender writes to `var/outbox_dryrun.jsonl`, and live
  sending is refused in code (`outbox.make_sender`).

## Run the demo

```bash
cd aibiz/mvp
./run_demo.sh                              # detailing studio; prints an admin token
./run_demo.sh config/demo_cleaning.json    # the cleaning company instead
```

Then open:

- **Customer chat:** http://127.0.0.1:8000/
- **Owner admin:** http://127.0.0.1:8000/admin, using the token printed at start.

Step by step:

```bash
python3 -m quotebook check-config
python3 -m quotebook init                  # create or upgrade the database (backs up first)
python3 -m quotebook seed                  # simulated customers and bookings
QB_ADMIN_TOKEN=choose-a-long-token python3 -m quotebook serve --port 8000
python3 -m quotebook jobs --loop 60        # second terminal: reminders, follow-ups, outbox (dry run)
```

## Tests

```bash
cd aibiz/mvp && python3 -m unittest discover -s tests -t .
```

There are 89 tests, passing on Python 3.11 and 3.13. They cover:

- the parser, prices, availability (holidays, buffers, DST) and booking states;
- double booking, including 8 threads racing for one slot and database triggers;
- conversations, duplicate messages, wrong dates and times, and taken slots;
- escalation, cancel and reschedule;
- consent, quiet hours, retries with backoff, provider outage, dead letters and crash recovery;
- HTTP integration: admin login, CSRF, rate limits, input limits and escaping;
- migrations, backup and restore, retention and GDPR export;
- the AI fallback with a fake client, and the CLI.

## What is and is not built

| Built and tested | Not built (yet) |
| --- | --- |
| Website chat (HR/EN), free-slot calendar page, JSON API | WhatsApp, Instagram, SMS or e-mail sending (needs the client's own approved accounts) |
| Price ranges from per-business rules | Google Calendar two-way sync (only one-way `.ics` export) |
| Hold, owner confirmation, cancel, reschedule | Online payments or deposits |
| Reminders and follow-ups only with consent, quiet hours | Several businesses in one installation (one config per process) |
| Owner admin: confirm, decline, move, manual booking, block time, pause, escalations, outbox, audit log | Per-user owner accounts (one shared admin token) |
| Optional AI interpreter with validation and fallback | Live test of the AI step against the real API (no key, no spending) |

## Documentation

| Document | What it covers |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Stack choice, the 15 required features mapped to code and tests, data protection, known limits |
| [docs/CONFIG.md](docs/CONFIG.md) | Every configuration field and environment variable |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Pilot deployment, backups, monitoring, upgrade and **rollback** |
| [docs/EXAMPLE_CONVERSATIONS.md](docs/EXAMPLE_CONVERSATIONS.md) | Real runs of the code (regenerate with `python3 -m quotebook transcripts`) |
