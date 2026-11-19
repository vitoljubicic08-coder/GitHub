# Automation services (Phase 2)

Fit for the top niches (cleaning, detailing, trades). Scores 1-5 are estimates; risk 5 = low risk.

| Rank | Service | Fit | Value | Feasibility | Differentiation | Recurring | Low risk | AI needed? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Lead capture and qualification | 87.0 | 5 | 4 | 4 | 4 | 4 | Optional: understanding free text; structured forms work without it |
| 2 | Quote generation (instant price range) | 85.0 | 5 | 4 | 4 | 4 | 3 | No for the price (rules); optional for reading free-text descriptions |
| 3 | Quote and sales follow-ups | 80.0 | 4 | 5 | 3 | 4 | 4 | No |
| 4 | Rebooking reminders for repeat services | 78.0 | 4 | 5 | 3 | 4 | 3 | No |
| 5 | Appointment reminders | 72.0 | 4 | 5 | 1 | 4 | 4 | No |
| 6 | Appointment scheduling (real free slots) | 72.0 | 4 | 4 | 2 | 4 | 4 | No: rules are more reliable |
| 7 | Missed-call text-back | 70.0 | 4 | 3 | 3 | 4 | 3 | No |
| 8 | Customer review requests | 69.0 | 3 | 5 | 2 | 4 | 4 | No |
| 9 | Customer onboarding flows | 66.0 | 3 | 4 | 3 | 3 | 4 | No |
| 10 | Inquiry classification and routing | 66.0 | 3 | 4 | 3 | 3 | 4 | Yes for free text, with a human fallback |
| 11 | Social-media inquiry management (Instagram, WhatsApp, Messenger) | 64.0 | 4 | 2 | 3 | 4 | 2 | Optional |
| 12 | CRM updates | 61.0 | 3 | 3 | 2 | 4 | 4 | No |
| 13 | Invoice and payment reminders | 61.0 | 3 | 4 | 2 | 4 | 2 | No |
| 14 | Automated email replies (drafts for approval) | 60.0 | 3 | 4 | 2 | 3 | 3 | Yes, but drafts reviewed by a human |
| 15 | Website support assistant | 60.0 | 3 | 4 | 2 | 3 | 3 | Optional: retrieval over the FAQ helps with phrasing |
| 16 | Customer feedback collection | 59.0 | 2 | 5 | 2 | 3 | 4 | No |
| 17 | Document processing | 58.0 | 4 | 2 | 2 | 4 | 1 | Yes (OCR + extraction), with human review |
| 18 | Automated business dashboards | 55.0 | 2 | 4 | 2 | 3 | 4 | No |
| 19 | Internal reporting | 55.0 | 2 | 4 | 2 | 3 | 4 | No |
| 20 | Deposits and prepayment links against no-shows | 54.0 | 3 | 3 | 2 | 3 | 2 | No |
| 21 | FAQ assistant | 52.0 | 2 | 5 | 1 | 2 | 4 | Usually no: quick replies and a good FAQ page suffice |
| 22 | Inventory notifications | 51.0 | 2 | 3 | 2 | 3 | 4 | No |

## Details

### Lead capture and qualification

- **Problem it solves:** Inquiries arrive half-complete; owner spends time asking the same questions
- **Who pays:** Quote-based services, real estate
- **Existing products:** Form builders, CRMs
- **Technical feasibility:** High
- **Implementation difficulty:** Medium
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Monthly; optionally per qualified lead
- **Risks and failure modes:** Asking too much and losing the lead
- **Is AI needed?:** Optional: understanding free text; structured forms work without it

### Quote generation (instant price range)

- **Problem it solves:** Every inquiry waits for a manual quote; slow quotes lose jobs
- **Who pays:** Cleaning, detailing, trades
- **Existing products:** Field-service suites (Jobber etc., mostly English)
- **Technical feasibility:** High with price rules
- **Implementation difficulty:** Medium (each business prices differently)
- **Operating cost (estimate):** Low
- **Maintenance:** Price updates
- **Pricing model:** Setup + monthly
- **Risks and failure modes:** A quoted range the business will not honour; must say 'estimate, confirmed after inspection'
- **Is AI needed?:** No for the price (rules); optional for reading free-text descriptions

### Quote and sales follow-ups

- **Problem it solves:** Quotes sent and never chased
- **Who pays:** Quote-based services
- **Existing products:** CRMs, field-service suites
- **Technical feasibility:** High
- **Implementation difficulty:** Low
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Bundle
- **Risks and failure modes:** Too many follow-ups annoy customers; needs consent rules
- **Is AI needed?:** No

### Rebooking reminders for repeat services

- **Problem it solves:** Customers who should come back (e.g. every 3-6 months) forget
- **Who pays:** Cleaning, detailing, servicing
- **Existing products:** Booking-platform marketing features
- **Technical feasibility:** High
- **Implementation difficulty:** Low
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Bundle
- **Risks and failure modes:** Marketing messages need prior consent (ZEK Art. 50)
- **Is AI needed?:** No

### Appointment reminders

- **Problem it solves:** No-shows and late cancellations
- **Who pays:** Appointment businesses
- **Existing products:** Built into every booking platform
- **Technical feasibility:** High
- **Implementation difficulty:** Low
- **Operating cost (estimate):** Email ~0; SMS ~USD 0.14 each to Croatia (Twilio); WhatsApp template fees per message
- **Maintenance:** Low
- **Pricing model:** Included in a bundle
- **Risks and failure modes:** Messaging without consent, wrong time zone, spam complaints
- **Is AI needed?:** No

### Appointment scheduling (real free slots)

- **Problem it solves:** Customers wait for a call back to get a time; owner juggles a paper or phone calendar
- **Who pays:** Any appointment business
- **Existing products:** Fresha, Booksy, Zoyya, Calendly, Google Calendar booking pages
- **Technical feasibility:** High with an own calendar; integrating a client's existing platform depends on its API
- **Implementation difficulty:** Medium (availability rules, no double booking)
- **Operating cost (estimate):** EUR 1-5/client/month hosting
- **Maintenance:** Low once rules are set
- **Pricing model:** Monthly subscription
- **Risks and failure modes:** Double bookings, wrong hours, owner forgets to block time off
- **Is AI needed?:** No: rules are more reliable

### Missed-call text-back

- **Problem it solves:** Calls missed while working turn into lost jobs
- **Who pays:** Trades, detailing, cleaning
- **Existing products:** US tools (e.g. inside field-service suites); few Croatian offers seen
- **Technical feasibility:** Medium: needs call forwarding to a virtual number and an SMS or WhatsApp sender
- **Implementation difficulty:** Medium
- **Operating cost (estimate):** Virtual number plus about USD 0.14 per SMS (Twilio, Croatia)
- **Maintenance:** Medium (telephony)
- **Pricing model:** Monthly
- **Risks and failure modes:** Number porting, carrier rules, cost per SMS
- **Is AI needed?:** No

### Customer review requests

- **Problem it solves:** Few Google reviews despite happy customers
- **Who pays:** Local services
- **Existing products:** Review-management tools
- **Technical feasibility:** High
- **Implementation difficulty:** Low
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Bundle add-on
- **Risks and failure modes:** Review gating and incentives can breach platform rules
- **Is AI needed?:** No

### Customer onboarding flows

- **Problem it solves:** New clients need documents, instructions, forms
- **Who pays:** Agencies, accountants, gyms
- **Existing products:** Form and e-signature tools
- **Technical feasibility:** High
- **Implementation difficulty:** Low to medium
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Setup + monthly
- **Risks and failure modes:** Collecting more data than needed
- **Is AI needed?:** No

### Inquiry classification and routing

- **Problem it solves:** Mixed inbox: complaints, quotes, spam
- **Who pays:** Firms with several staff
- **Existing products:** Helpdesk tools
- **Technical feasibility:** High
- **Implementation difficulty:** Low to medium
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Part of a bundle
- **Risks and failure modes:** Misrouted urgent messages
- **Is AI needed?:** Yes for free text, with a human fallback

### Social-media inquiry management (Instagram, WhatsApp, Messenger)

- **Problem it solves:** Inquiries scattered over DMs, lost in personal inboxes
- **Who pays:** Instagram-driven local businesses
- **Existing products:** Meta Business Suite inbox (free), unified-inbox tools
- **Technical feasibility:** Medium: official Meta APIs need business verification and app review
- **Implementation difficulty:** High (platform approval, policy changes)
- **Operating cost (estimate):** WhatsApp template messages are charged per message
- **Maintenance:** High (API changes)
- **Pricing model:** Monthly
- **Risks and failure modes:** Account restrictions if rules are broken; no unofficial automation
- **Is AI needed?:** Optional

### CRM updates

- **Problem it solves:** Customer details scattered across phone, WhatsApp, notebooks
- **Who pays:** Growing teams
- **Existing products:** HubSpot free, Pipedrive
- **Technical feasibility:** Medium (depends on the CRM's API)
- **Implementation difficulty:** Medium
- **Operating cost (estimate):** Low
- **Maintenance:** Medium
- **Pricing model:** Setup + monthly
- **Risks and failure modes:** Duplicate or wrong records
- **Is AI needed?:** No

### Invoice and payment reminders

- **Problem it solves:** Late payments
- **Who pays:** B2B services, accountants
- **Existing products:** Invoicing software; e-invoicing services under Fiskalizacija 2.0
- **Technical feasibility:** High
- **Implementation difficulty:** Low
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Monthly
- **Risks and failure modes:** Financial data; reminders to wrong people; collection rules
- **Is AI needed?:** No

### Automated email replies (drafts for approval)

- **Problem it solves:** Slow email replies
- **Who pays:** Office-based businesses
- **Existing products:** Gmail/Outlook AI features
- **Technical feasibility:** High (drafts only)
- **Implementation difficulty:** Low
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Monthly
- **Risks and failure modes:** Sending wrong information if fully automatic
- **Is AI needed?:** Yes, but drafts reviewed by a human

### Website support assistant

- **Problem it solves:** Same questions asked again and again
- **Who pays:** Businesses with website traffic
- **Existing products:** Tidio, Intercom, many AI chat widgets
- **Technical feasibility:** High
- **Implementation difficulty:** Low to medium
- **Operating cost (estimate):** LLM cost under EUR 1/month at small volumes (estimate)
- **Maintenance:** Keep answers current
- **Pricing model:** Monthly
- **Risks and failure modes:** Wrong answers stated confidently; small sites get little traffic
- **Is AI needed?:** Optional: retrieval over the FAQ helps with phrasing

### Customer feedback collection

- **Problem it solves:** No structured feedback
- **Who pays:** Service businesses
- **Existing products:** Survey tools
- **Technical feasibility:** High
- **Implementation difficulty:** Low
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Bundle
- **Risks and failure modes:** Low response rates
- **Is AI needed?:** No

### Document processing

- **Problem it solves:** Manual data entry from invoices and forms
- **Who pays:** Accountants, logistics
- **Existing products:** OCR/IDP vendors, accounting software
- **Technical feasibility:** Medium
- **Implementation difficulty:** High (accuracy)
- **Operating cost (estimate):** Medium
- **Maintenance:** High
- **Pricing model:** Per document
- **Risks and failure modes:** Errors in financial data; sensitive data
- **Is AI needed?:** Yes (OCR + extraction), with human review

### Automated business dashboards

- **Problem it solves:** No overview of bookings and revenue
- **Who pays:** Owners with several data sources
- **Existing products:** Looker Studio, built-in reports
- **Technical feasibility:** High
- **Implementation difficulty:** Low to medium
- **Operating cost (estimate):** Low
- **Maintenance:** Medium
- **Pricing model:** Setup + monthly
- **Risks and failure modes:** Low perceived value for very small firms
- **Is AI needed?:** No

### Internal reporting

- **Problem it solves:** Owner lacks a weekly overview
- **Who pays:** Multi-staff businesses
- **Existing products:** Spreadsheet templates, BI tools
- **Technical feasibility:** High
- **Implementation difficulty:** Low
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Add-on
- **Risks and failure modes:** Nobody reads the report
- **Is AI needed?:** No

### Deposits and prepayment links against no-shows

- **Problem it solves:** No-shows on long or expensive jobs
- **Who pays:** Detailing, beauty
- **Existing products:** Booking platforms with payments
- **Technical feasibility:** Medium (payment provider account per client)
- **Implementation difficulty:** Medium
- **Operating cost (estimate):** Payment fees
- **Maintenance:** Medium
- **Pricing model:** Bundle or per transaction
- **Risks and failure modes:** Refund disputes; handling payments raises the stakes
- **Is AI needed?:** No

### FAQ assistant

- **Problem it solves:** Repetitive questions about hours, prices, location
- **Who pays:** Any small business
- **Existing products:** Free chat widgets, WhatsApp Business quick replies
- **Technical feasibility:** High
- **Implementation difficulty:** Low
- **Operating cost (estimate):** Low
- **Maintenance:** Low
- **Pricing model:** Usually bundled
- **Risks and failure modes:** Little value on its own
- **Is AI needed?:** Usually no: quick replies and a good FAQ page suffice

### Inventory notifications

- **Problem it solves:** Running out of stock
- **Who pays:** Shops, restaurants
- **Existing products:** Inventory and POS software
- **Technical feasibility:** Depends on POS API
- **Implementation difficulty:** Medium
- **Operating cost (estimate):** Low
- **Maintenance:** Medium
- **Pricing model:** Monthly
- **Risks and failure modes:** Bad data in, bad alerts out
- **Is AI needed?:** No
