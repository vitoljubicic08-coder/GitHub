# Configuration

## Business file (`config/*.json`)

There is one JSON file per client. Copy a demo file and edit it. Run `python3 -m quotebook
--config config/your_client.json check-config` after every change: it lists every problem it finds.

| Section | Field | Meaning |
| --- | --- | --- |
| `business` | `id`, `name`, `timezone`, `default_language` | `timezone` is an IANA name (`Europe/Zagreb`); language `hr` or `en` |
| | `address`, `location.hr/en` | Answer to "where are you?" |
| | `owner_contact` | Where owner notifications would go (only written to the dry-run file in this MVP) |
| `measure` | `vehicle_size`, `area_m2` or `none` | What the price depends on |
| `sizes` | per size: `hr`, `en`, `keywords` | Vehicle classes and the words that recognise them (stems, no diacritics needed) |
| `resources` | `id`, `name` | Bays, teams or vans. A booking uses one resource. |
| `hours` | `mon` … `sun`: list of `["08:00","17:00"]` | Several intervals per day are allowed (e.g. a lunch break) |
| `closed_dates` | `["2026-12-24", …]` | Extra closed days. Croatian public holidays are built in. |
| `booking` | `slot_step_minutes` | Start-time grid (30 = 08:00, 08:30, …) |
| | `min_notice_hours`, `horizon_days` | How soon and how far ahead customers can book |
| | `hold_minutes` | How long a chosen time is held while the customer gives details |
| | `buffer_minutes` | Gap kept free before and after every job |
| | `require_owner_confirmation` | `true` (recommended for pilots): requests wait for the owner |
| | `max_suggestions` | How many times to offer |
| `services[]` | `id`, `names.hr/en`, `keywords` | `keywords` are folded stems: `polir` matches *poliranje*, *polirati* |
| | `price.by_size` / `price.per_m2` + `minimum` / `price.fixed`, `range_pct` | The estimate is the base price ± `range_pct`, rounded to €5 |
| | `duration.by_size` / `base_minutes` + `minutes_per_m2` + `max_minutes` / `minutes` | Job length |
| | `resources` | Which bays or teams can do it (default: all) |
| | `needs_measure` | `false` for flat-price services |
| `messaging` | `send_enabled` | **Must stay `false`.** The MVP has no live sender and refuses to start one. |
| | `reminder_hours_before`, `quiet_start`, `quiet_end` | Reminders and follow-ups wait until quiet hours end |
| | `followup_after_hours`, `max_attempts` | One follow-up after a declined or expired request (with consent); retries before giving up |
| `retention` | `conversation_days`, `customer_inactive_days`, `audit_days` | Applied by `python3 -m quotebook purge` |
| `rate_limits` | `per_conversation_per_minute`, `per_ip_per_minute`, `login_per_ip_per_minute` | Over the limit: HTTP 429 |
| `assistant` | `max_unclear` | Unclear messages in a row before handing over (default 2, so the 3rd hands over) |
| | `llm_model`, `llm_timeout_s` | Used only if the AI interpreter is enabled |
| `texts` | `{"hr": {key: text}, "en": {…}}` | Optional overrides of any sentence in `quotebook/i18n.py` |

## Environment variables (secrets and switches)

| Variable | Purpose |
| --- | --- |
| `QB_ADMIN_TOKEN` | Admin password. Use a long random string. If it is unset, the admin page is disabled. |
| `QB_ENABLE_LLM=1` | Turn on the AI interpreter. It also needs `pip install anthropic` and `ANTHROPIC_API_KEY`. It costs money per message, so ask before turning it on for a client. |
| `ANTHROPIC_API_KEY` | Read by the Anthropic SDK. Never put it in a file in the repository. |
| `QB_ALLOW_LIVE_SEND` | Reserved. Setting it makes startup fail on purpose: live sending is not implemented. |

On a server, keep these in a root-owned file with `chmod 600` (see DEPLOY.md), never in the JSON.
