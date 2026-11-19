# AI automation business: research, MVP and go-to-market kit

This folder holds everything for the "AI automation business from zero" project. The written
report, including the private prospect list, lives in a separate private document. This folder
has the reproducible parts.

**Recommendation in one line:** sell an **inquiry → estimate → owner-confirmed booking** assistant
to Zagreb car-detailing studios and small cleaning companies. Validate with one paid pilot (€149)
before building anything more. See `validation/VALIDATION_PLAN.md` for the go / pivot / stop gates.

| Folder | What is in it | Run |
| --- | --- | --- |
| `research/` | 15-niche weighted ranking with a weight-sensitivity check; 22 automation services scored | `python3 research/niches.py`, `python3 research/services.py` |
| `mvp/` | **Quotebook**, the working demo: chat assistant (HR/EN), estimates, real free slots, owner admin, consent-aware outbox (dry run only), 89 tests | `cd mvp && ./run_demo.sh`; tests: `python3 -m unittest discover -s tests -t .` |
| `finance/` | Pricing tiers, delivery cost, 12-month scenarios (0–30 clients), €500–5,000 MRR feasibility | `python3 finance/model.py` |
| `validation/` | Hypotheses, funnel targets, decision gates, pilot design, prospect-list template | — |
| `sales/` | Outreach kit (HR/EN), one-page proposal, demo script, onboarding, feedback and referral process, CRM template | — |
| `plan/` | 90-day week-by-week roadmap; website and brand plan (build after Gate 1) | — |

## Ground rules this project follows

- **Simulated data only** in code and tests. The demo businesses are fictional.
- **Nothing is sent to anyone.** The only message sender writes to a local file, and live sending
  is refused in code.
- **No real outreach, deployment, account creation or spending** without the owner's explicit
  approval.
- **Facts about real businesses** stay in the private report, not in this public repository.
- **Estimates are labelled as estimates.** Official figures cite their source in the code
  comments (`finance/model.py`).
