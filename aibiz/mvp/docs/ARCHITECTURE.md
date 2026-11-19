# Architecture

## Why this stack

The core job is transactional: never double-book, never claim a booking that does not exist,
never lose a message. That needs a real database with transactions and constraints. That rules
out a chain of no-code steps.

| Option | Reliability for bookings | Running cost | Maintenance | Verdict |
| --- | --- | --- | --- | --- |
| **Python stdlib + SQLite (chosen)** | Transactions, unique keys and triggers enforce no double booking | One small server (€5–10/month, estimate) or the owner's own PC for a pilot | No dependencies to update; one file to back up | Best for 1–20 pilot clients |
| n8n / Make / Zapier workflows | Hard to make atomic; concurrency and retries depend on the platform | n8n cloud €20–50/month (n8n pricing page); Make and Zapier similar or higher | Visual flows break silently when an API changes | Good for glue later (e.g. a Google Sheets export), not for the booking core |
| Supabase / PostgreSQL | Excellent (exclusion constraints, row-level security) | Free tier, then paid | Managed | The upgrade path at SaaS stage (multi-tenant, many clients) |
| Google Calendar as the database | Free/busy checks are not atomic; two customers can take one slot | Free | OAuth per client | Use as a mirror (`.ics` now, two-way sync later), not as the source of truth |
| LLM-only agent (an AI does everything) | Can state things that are not true ("you're booked") | Per-message tokens | Prompt drift | Rejected. AI is optional and only reads text (see below) |

### Configurations

| | Free (demo, pilot on own PC) | Low cost (first paying clients) | Professional (10+ clients) |
| --- | --- | --- | --- |
| Hosting | Laptop or a spare PC, local network only | One small VPS, Caddy for HTTPS | Managed Postgres + app server, staging environment |
| Channel | Website chat link in Instagram bio / Google profile / WhatsApp Business app away message (free, no API) | Same, plus e-mail notifications to the owner | WhatsApp Business Platform (official Cloud API), SMS via Twilio (~$0.14/SMS to Croatia) |
| Calendar | Built-in | Built-in + `.ics` feed into the owner's phone calendar | Two-way Google Calendar sync (official API, client OAuth) |
| AI | Off | Off, or the optional interpreter for free text | Interpreter on, with monitoring of fallbacks |
| Backups | Manual `backup` command | Daily cron + off-site copy | Managed point-in-time recovery |

## Modules

```
quotebook/
  config.py        business JSON (services, prices, hours, resources) + environment secrets
  parser.py        rules-based HR/EN understanding: intent, service, size/area, date, time, contact
  llm.py           optional AI interpreter: fills only gaps, validated, falls back to rules
  pricing.py       estimate ranges from the business's own price rules
  availability.py  free slots: opening hours, Croatian public holidays, closed dates, buffers, blocks
  booking.py       hold -> pending_owner -> confirmed / declined / cancelled / expired / completed
  outbox.py        queued messages: consent, quiet hours, retries with backoff, dead letters
  assistant.py     conversation flow, owner actions, background jobs, retention, GDPR export
  db.py            schema, migrations (with backup), transactions with retry, overlap triggers
  web.py           demo site, chat API, public slot calendar, owner admin (stdlib http.server)
  i18n.py          every customer-facing sentence in Croatian and English
  logs.py          JSON logs with phone numbers and e-mail addresses masked
```

## The 15 required features

| # | Feature | Where | Tested in |
| --- | --- | --- | --- |
| 1 | Receive customer inquiries | `/api/chat` → `App.handle_message` | `test_web.Public.test_chat_flow_over_http` |
| 2 | Understand simple requests | `parser.parse` (HR/EN dates, times, services, sizes, m², names, phones) | `test_parser` (15 tests) |
| 3 | Check real free times | `availability.day_slots` (hours, holidays, buffers, blocks, notice, horizon) | `test_booking.Availability` |
| 4 | Suggest times | `availability.suggest` (closest to the request, spread out) | `test_suggest_prefers_requested_time_and_spreads` |
| 5 | Book only after confirmation | Hold for 20 min → owner confirms → `confirmed`; texts say "NOT CONFIRMED YET" until then | `test_full_booking_never_claims_confirmed_before_owner`, `test_auto_confirm_mode_says_confirmed_only_when_it_is` |
| 6 | Send confirmations | Outbox `confirmed` message queued when the owner confirms | same tests |
| 7 | Reminders with consent | `outbox.enqueue` refuses reminder/follow-up without consent; quiet hours | `test_outbox.Consent`, `test_no_reminder_without_consent` |
| 8 | Cancel and reschedule | Chat (by conversation or reference + matching phone) and admin; reschedule is one transaction | `test_conversation.Manage`, `test_reschedule_is_atomic` |
| 9 | Escalate uncertain requests | Complaints, "call me", 3 unclear messages, no slots, failed messages → "Needs you" list | `test_conversation.Escalation` |
| 10 | Log actions and errors | `audit` table for every state change; JSON logs with masking | `test_logs_are_masked`, admin page |
| 11 | Prevent double bookings | `BEGIN IMMEDIATE` + overlap check, and DB triggers as a second guard | `test_concurrent_holds_only_one_wins`, `test_database_trigger_blocks_overlaps_from_any_code_path` |
| 12 | Protect customer data | See below | `test_ops.Retention`, `test_web.Admin` |
| 13 | Croatian and English | `i18n.py`, language detection per conversation | `test_english`, `test_parser.Language` |
| 14 | Owner override | Confirm/decline/move/cancel, manual bookings outside hours (never overlapping), block time, pause the assistant | `test_owner_overrides` |
| 15 | Admin interface | `/admin` | `test_web.Admin` |

## Failure scenarios tested

| Scenario | What happens | Test |
| --- | --- | --- |
| Impossible date (31.02.), past date, 25:00 | Customer is asked again; nothing is guessed | `test_bad_dates_and_times_are_questioned` |
| Requested day closed or too short for the job | Says so and offers the nearest free times | `test_sunday_and_too_long_for_saturday` |
| Slot taken between offer and choice | Other bay tried first, then fresh options | `test_slot_taken_between_offer_and_choice` |
| Same message delivered twice | Same reply returned; no second hold | `test_duplicate_message_id_does_not_double_book` |
| 8 customers click the same slot at once | Exactly one hold | `test_concurrent_holds_only_one_wins` |
| Customer goes quiet after picking a time | Hold expires after 20 min; slot is free again | `test_expired_hold_frees_the_slot` |
| Message provider down | Retries with backoff; batch stops after 3 failures; after 6 attempts → dead letter + owner alert | `test_outbox.Delivery` |
| Worker crashes mid-send | Message returns to the queue after 10 min | `test_crash_mid_send_is_recovered` |
| AI API timeout, refusal, invalid JSON, nonsense values | Rules result used; circuit breaker after 3 failures | `test_ops.AIInterpreter` |
| Flood of messages / login guessing | 429 after the per-minute limit | `test_rate_limit_returns_429`, `test_login_brute_force_is_limited` |
| Corrupt backup file | Restore refused | `test_round_trip_and_corrupt_backup_rejected` |
| Database from a newer version | Start refused with instructions | `test_fresh_idempotent_and_newer_schema_refused` |

## Data protection (technical side)

- **Minimal data:** name, mobile number, optional e-mail, the job details and consent flags. No ID
  numbers, no payment data, no health data.
- **Consent stored with a timestamp** and checked before every reminder or follow-up. Marketing
  messages need a separate consent.
- **Retention (`purge`):**
  - conversations deleted after 90 days;
  - customers inactive for 2 years anonymised, unless they have a future booking;
  - audit log trimmed after 2 years.
- **Access requests:** `export-customer PHONE` prints everything held on one customer.
- **AI:** off by default. When on, phone numbers and e-mails are removed before text is sent, and
  only validated fields are kept.
- **Secrets only in environment variables:** the admin token and API key are never in the JSON or
  the repository. The admin login uses a constant-time comparison.
- **Web protections:**
  - HttpOnly + SameSite=Strict cookie (Secure behind HTTPS);
  - CSRF token on every admin form;
  - strict Content-Security-Policy;
  - all output HTML-escaped;
  - request size limits.
- **Logs** mask phone numbers and e-mail addresses.
- **One SQLite file per client** makes isolation simple; back it up encrypted if stored off-site.

The legal side (controller/processor roles, DPA, privacy notice) is in the business report, not here.

## Known limits

- The rules parser handles common phrasing. Unusual messages are handed to the owner, not guessed.
  It has not yet met real customers' messages; the pilot will show where it needs more words.
- Sessions and rate limits live in memory, so a restart logs the owner out. Run one process per client.
- No live message channel is implemented; adding one needs the client's own approved account
  (e.g. Meta business verification for WhatsApp) and your explicit approval.
