# Proposed Upgrades (for later discussion)

This file captures upgrade ideas to discuss and design later. It is a
backlog of intent, not a spec or an implementation plan yet.

---

## Upgrade 1: Proactive Monitoring Agent (auto-trigger instead of manual)

### Problem it solves

Today the system is **reactive**: a case only starts when a human explicitly
asks it to check a product (CLI `run`, or clicking a product in the UI
watchlist). Nobody is watching stock continuously. A product can drift into
stockout risk between the times a human happens to look.

### The idea

Add a background process (a scheduler / watcher) that runs on its own,
continuously or on a schedule, and:

1. **Scans stock proactively** for all (or watched) products/warehouses —
   effectively running the existing risk assessment (`scan_portfolio` /
   `compute_risk`) without waiting for a human.
2. **When it finds an at-risk product, initiates contact with the user**
   (e.g. by email): "AC-001 at DEL-01 is at risk of stockout. Do you want me
   to run the ordering agent?"
3. **On user "yes" → runs the full existing flow** (sourcing, proposal,
   policy, approval, execution) — reusing everything already built.
4. **On user "no"/reject → records the rejection and the reason**, and then
   decides whether a future reminder is warranted.

### The reminder / rejection-reason logic (the interesting part)

When the user declines, capture *why*, and act on it:

- If the reason is **"too early / not needed yet"** → ask a follow-up:
  "When should I remind you again?" and schedule a reminder for that date.
- If the reason is a **hard no for this cycle** → suppress reminders for a
  defined window rather than nagging.
- Different reasons should lead to different follow-up behavior (remind
  later vs. drop vs. escalate). The system should interpret the reason, not
  just store it.

### What this depends on (ties back to gaps already recorded)

- **Agent memory** (Gap: "No Agent Memory") — remembering past rejections,
  their reasons, and scheduled reminder dates is exactly the memory the
  system currently lacks. This upgrade needs a durable store of:
  decisions, reasons, and next-reminder timestamps per product/warehouse.
- **Notification that initiates a conversation** — today email is one-way
  and off by default (Gap: "BLOCKED Communication..."). This needs a
  two-way loop: notify → user replies (yes / no + reason / remind-on-date)
  → system acts. The existing signed single-use approval-token + link
  mechanism (`notifications/tokens.py`, `graph/approval_server.py`) is a
  natural starting point to extend.
- **A scheduler / background runner** — something outside the current
  request-driven model (cron, a loop, or a task queue) that owns the
  "check + decide whether to ping" cadence.

### Open questions to decide later

- Cadence: continuous, hourly, daily? Per warehouse?
- Which products are in scope — all, or an explicit watchlist?
- How is a user's email reply parsed into yes / no / reason / remind-date
  reliably and safely (this is untrusted input → same injection concerns as
  the revision request)?
- How are reminders stored, fired, and cancelled?
- What stops reminder spam / runaway loops (bounds, like the existing
  revision-cycle cap)?

### Status

**Wanted (2026-09-06), not yet built.** Previously "idea only"; the project
owner has since asked for monitoring explicitly. Two things changed with it:

1. **It now depends on Upgrade 4**, not just on agent memory. The
   notify → reply → act loop this needs *is* two-way email, so Upgrade 4 is
   the prerequisite rather than a sibling.
2. **A hard data-residency constraint applies.** See Upgrade 4: any parsing
   of message content must run on a local model, never a hosted one.

Also note the reminder story got cheaper than this section assumed: the
"Needs my decision" queue already computes staleness live when opened
(`portfolio.list_pending_cases` flags anything waiting longer than
`config.data_freshness_hours`). That is a manual check, not a cron, but it
means the scheduler's job is narrower than "invent reminders from scratch".

Still genuinely undecided, and worth settling before code: cadence, whether
scope is all products or an explicit watchlist, and what bounds reminder
volume. The existing revision-cycle cap is the right precedent for the last
one.


---

## Upgrade 2: Auto-Redraft on Fixable Policy Failures (bounded, fail-closed)

### Problem it solves

Today, when `review_policy` returns a `BLOCKED` verdict (including the
code-forced over-budget block), the case fails closed and ends — see
`submission/graph/nodes.py` `review_policy` → `_fail(...)` →
`finalize_blocked`. There is no loop that hands the failure reason back to
the agents so they can produce a *different* proposal that would pass. A
recoverable situation (e.g. the chosen vendor is slightly over budget) is
treated the same as an unrecoverable one.

### The idea

When policy review fails, feed the **specific reason** back into the
reasoning step and let the agent re-draft — the same "reason in, new attempt
out" pattern that already exists for human revisions. Loop back to
`recommend_vendor` (which then re-drafts and re-reviews) with the concern
text attached, so the strategist can pick a cheaper/faster/different
eligible option.

### The critical distinction: fixable vs. unfixable

An auto-redraft must **not** fire on every failure. It should only loop when
a different valid proposal could plausibly satisfy the policy:

- **Fixable → loop back (bounded):**
  - Over budget (pick a cheaper eligible vendor, or reduce quantity toward
    MOQ while still covering the target).
  - A policy concern that a different eligible option would resolve.
- **Unfixable → fail closed (as today):**
  - Missing / insufficient / stale evidence.
  - No eligible vendor options.
  - SKU not actually at risk.
  - Anything where re-drafting would just reproduce the same block.

### Hard constraints (must preserve)

1. **Bounded.** Reuse the existing cap idea (`max_revision_cycles = 1`, or a
   dedicated auto-redraft cap). After the bound is hit, fail closed. No
   unbounded loops.
2. **Budget stays authoritative in code.** The over-budget verdict is still
   computed and enforced by `review_policy`'s override, never by the LLM.
   Auto-redraft may search for a cheaper option; it may **not** wave through
   an over-budget order. "LLM budget judgment is not authoritative" holds.
3. **Do not let the agent "creatively" bypass a real limit.** The loop
   changes *which eligible option* is proposed; it cannot invent options,
   change computed numbers, or set aside a rule.

### What already exists to build on

- **Human REVISE loop** — a human rejection with a comment already routes
  back to `recommend_vendor`, bounded by `max_revision_cycles` (see
  `route_after_decision`, `handle_decision`, `render_approver_feedback`).
  The auto-redraft is essentially the same loop triggered by a policy block
  instead of a human, with a machine-generated reason instead of a comment.
- **Over-budget EXCEPTION tier** — within `over_budget_exception_tolerance`
  (5%), the verdict already softens to `EXCEPTION` (flagged, human still
  decides) rather than a hard block. Auto-redraft would sit alongside this,
  not replace it.

### Open questions to decide later

- How is a policy concern classified as fixable vs. unfixable — an explicit
  reason code on the verdict, rather than parsing free text?
- Loop target: back to `recommend_vendor` (re-pick + re-draft + re-review)
  vs. a narrower re-draft. Re-pick is cleaner given the existing edges.
- Separate cap for auto-redraft vs. sharing the human revision cap?
- What is surfaced to the human if every redraft attempt still fails — the
  best rejected proposal plus the reason, or just BLOCKED?

### Status

Idea only. To be discussed and designed before any implementation.


---

## Upgrade 3: Vendor Ordering Integration (send the order to the supplier)

### Problem it solves

Today "placing the order" only writes a row to the local `purchase_requests`
table (`tools/execution.py` → `create_purchase_request`). The supplier is
never contacted — no email, no API, no outbound integration. The loop is not
closed: an approved order exists only inside our own database. (See the
matching gap entry "No Purchase Order Is Actually Sent to the Vendor" in
GAP_NEEDS_INFORMATION.md.)

### The idea

After a proposal is human-approved, revalidated, and written as a purchase
request, actually notify the vendor (email first; a vendor API later) with a
formal, templated purchase order.

### The critical trust / security design (must be settled first)

This is an outbound commercial action to a third party, so it needs a
designed trust model before any code:

1. **Trusted vendor contact source.** Vendor email/endpoint must come from a
   controlled, maintained record (e.g. a `vendors` contact field owned by
   ops), never from untrusted evidence text or anything an agent produced.
   Define who maintains it and how a wrong/spoofed address is prevented.
2. **Strictly templated content.** The vendor message is built only from
   validated proposal fields (sku, quantity, unit_price, total_cost, vendor,
   expected_arrival). No agent free-text ever reaches the vendor — this
   blocks prompt-injection or malicious content from being forwarded to a
   third party.
3. **Authorization gate.** Only a proposal that is human-approved,
   revalidated, and idempotently written may trigger a send. No agent path
   can reach the vendor send directly (same boundary as
   `create_purchase_request`).
4. **Send idempotency.** The vendor send must be idempotent (keyed like the
   purchase request) so a retry or double-approval can never place two orders
   with the supplier.
5. **Channel protection / anti-spoofing.** Ensure the vendor address cannot
   be tampered with in transit, the outbound email is authenticated
   (SPF/DKIM/DMARC on the sending domain), and any ordering endpoint cannot
   be abused or replayed.

### What already exists to build on

- The internal notification path (`notifications/email.py`) and the
  deterministic-node-only write boundary (`create_purchase_request`) are the
  right shape to extend — a vendor send would sit right after a successful
  `execute_purchase`, behind the same "only after approval + revalidation"
  gate.
- The idempotency-key pattern (`proposal_hash:approver`) already used for the
  DB write is a natural basis for send-once-to-vendor.

### Open questions to decide later

- Email only, or a vendor API/EDI integration for larger vendors?
- Where the authoritative vendor contact record lives and who owns it.
- What acknowledgement (if any) is expected back from the vendor, and whether
  the case tracks a "sent / acknowledged / fulfilled" lifecycle beyond
  `PENDING`.
- How a send failure is retried and surfaced (vs. the DB write, which already
  has a write_failed path).

### Status

Idea only. To be discussed and designed before any implementation. Depends on
the trust model above being settled first.


---

## Upgrade 4: Two-Way Email — Read Replies, With Parsing Kept On-Premise

### Problem it solves

Email is one-way. `notifications/email.py` sends approval requests, blocked
notices and outcome mails; nothing ever reads a reply. An approver who
answers the email, or a supplier who replies "confirmed, shipping Tuesday",
is talking to a mailbox nobody opens.

This blocks three things at once:

- **Approval by reply** rather than only by clicking a signed link.
- **Order confirmation** — a supplier reply is the natural way `PENDING`
  becomes `CONFIRMED`, which is currently unreachable (see
  `GAP_NEEDS_INFORMATION.md`). That in turn feeds `confirmed_inbound` and
  gives the missing reorder guard.
- **Upgrade 1's conversation loop** — "shall I order this?" → "not yet,
  remind me in a fortnight" needs an inbound path to exist.

### The privacy constraint that shapes the whole design

**Business correspondence must not be sent to a third-party LLM.** Project
owner's explicit requirement (2026-09-06), and it is the right call: these
messages carry supplier identities, negotiated unit prices, order volumes,
warehouse locations and commercial terms. The current agents run against
hosted models (Vertex by default, optionally OpenAI or AI Studio — see
`config.py`), and routing inbound mail through any of those would mean
handing a vendor's pricing and the company's purchasing patterns to an
external provider on every reply.

So parsing runs **locally or not at all**:

- **Preferred: no model at all for the security-critical part.** See the
  authorization design below — a correctly designed reply handler does not
  need an LLM to decide *what to do*. Deterministic matching on a signed
  reference plus a small intent allowlist covers approve / reject / confirm /
  decline. This is cheaper, faster, fully auditable, and has no data-egress
  question to answer.
- **Local model only where free text genuinely needs interpreting** —
  e.g. turning "not yet, try me after the Diwali rush" into a remind-on date,
  or summarising a supplier's caveat. Run it on-machine (Ollama or
  llama.cpp with a small instruct model); no message body crosses the network.
- **Never the hosted agents.** `agents/real.py` and `agents/wiring.py` must
  not be reachable from the reply path. Worth an explicit boundary comment,
  the same way `create_purchase_request` documents that no LLM may call it.

A local model is a meaningfully different engineering commitment from the
current setup (a bundled runtime, model weights, and a much weaker model than
the agents use), which is a reason to keep it off the authorization path and
confine it to advisory extraction.

### Authorization: the token decides, the text only supplies detail

Inbound email is untrusted input, and unlike the vendor-notes field it is
untrusted input that is *asking for an action*. The rule:

> A reply's signed reference authorizes the action. The message body may only
> contribute a comment, a date, or a free-text note — never the decision
> itself, and never the identity of the actor.

Concretely:

1. Outbound mail carries a signed, single-use reference. `notifications/
   tokens.py` already issues exactly this (signed `jti`, TTL from
   `config.approval_token_ttl_minutes`, single-use enforced via the
   `used_tokens` store) for the approve/reject links — reuse it rather than
   inventing a second scheme. Carry it in a `Reply-To` subaddress
   (`inventra+<token>@…`) or a message reference, not in the visible body
   where it can be forwarded or quoted.
2. Inbound handling resolves the token first. No valid token → the message is
   logged and discarded. Never fall back to matching on sender address, case
   id in the subject line, or anything else guessable or spoofable.
3. Intent comes from a short allowlist matched against the reply, and an
   ambiguous match is a *clarification*, not a guess. Silently interpreting
   "no problem" as approval is the failure mode to design against.
4. Everything already-enforced stays enforced: an approval arriving by reply
   goes through the same `revalidate` → hash/stock/offer/budget re-check as
   one arriving from the UI. Reply parsing decides *that a decision was
   made*, never *that it is safe to act on*.
5. Quoted history is stripped before matching, so a reply quoting an earlier
   "APPROVED" cannot re-trigger it.

### The fetch problem, and why there is no daemon

Reading replies needs something to check the mailbox, but a background poller
is exactly what was scoped out. Options, honestly:

- **Explicit fetch (recommended).** A `check-replies` command plus a button
  in the UI. No daemon, and consistent with how `list_pending_cases` already
  computes staleness on open rather than on a schedule. Someone can put it
  behind an external cron if they want, which keeps the scheduling decision
  outside this codebase.
- **IMAP IDLE long-poll.** Genuinely a background process; only worth it once
  Upgrade 1 lands, since that needs a runner anyway.
- **Inbound webhook** (Postmark, SendGrid). Lowest latency, but needs a
  publicly reachable endpoint and moves mail handling to a third party —
  which reopens the data-residency question this upgrade exists to close.

### Prerequisite

The email-testability gap must be closed first (env-driven SMTP host/port,
optional TLS/auth — see `GAP_NEEDS_INFORMATION.md`). Building a reply parser
while every test send burns the Gmail daily quota is not workable; a local
Mailpit/MailHog sink makes the whole loop inspectable offline.

### Open questions to decide later

- Which mailbox, and does it need to be separate from the sending address?
- Subaddressing (`user+tag@`) vs. a dedicated inbound address — does the
  chosen provider preserve the tag?
- Do supplier replies and approver replies share one handler, or is the trust
  boundary different enough to warrant two (the vendor path is already
  separated at file level for exactly this reason — see
  `notifications/vendor_email.py`)?
- What happens to a reply that arrives after the case has moved on: discard,
  or surface as "this arrived too late"?
- Is a local model wanted at all in v1, or is deterministic parsing plus an
  "I did not understand that" reply sufficient to start?

### Status

Wanted (2026-09-06). Design above is settled on the authorization model and
the no-hosted-LLM constraint; the fetch mechanism and whether v1 includes a
local model are still open.
