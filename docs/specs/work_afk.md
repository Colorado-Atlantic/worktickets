# /work-afk — Autonomous Containerized Work

**Status**: Draft
**Created**: 2026-03-31
**Related**: `/work` skill, `/breakdown` skill, `/review` skill

## Problem

The `/work` skill runs autonomously but inside the user's active session and working directory. This creates two issues:

1. **No isolation** — the agent operates on the same filesystem, git state, and credentials as the user. Running with `bypassPermissions` means a bad command can affect the host.
2. **Stale sessions** — long-running containers or sessions accumulate state and can drift.

AFK-tagged tickets from `/breakdown` have clear acceptance criteria and are designed for autonomous pickup, but there's no safe, hands-off way to execute them.

## Solution

A `/work-afk` skill that acts as a **host-side dispatcher**, launching ephemeral Docker containers to work on AFK-ready tickets. Each container clones the repo, implements the ticket, opens a PR, and shuts down. No stale state, no host risk.

## Design

### Trigger

- **Manual**: `/work-afk` — auto-picks the top AFK-ready ticket
- **Manual with override**: `/work-afk 247` — works on a specific ticket
- **Serial execution**: one container at a time initially. Path to parallel (up to ~5) requires no architecture changes — just launch more containers.

### Schema Changes

Two new columns on the `tickets` table:

```sql
ALTER TABLE tickets ADD COLUMN work_mode TEXT DEFAULT NULL;
-- Values: 'AFK', 'HITL', or NULL (untagged)

ALTER TABLE tickets ADD COLUMN acceptance_criteria TEXT DEFAULT '';
-- Explicit done-state separate from description/notes
```

- `/breakdown` sets `work_mode` and `acceptance_criteria` at ticket creation time
- Existing `[AFK]` notes tags can be backfilled into the new column

### Dispatch Logic

The dispatcher runs on the host and selects tickets through a series of gates:

1. `work_mode = 'AFK'`
2. `status = 'open'`
3. `depends_on` all completed (or empty)
4. **Readiness validation** — one of:
   - Has `parent_id` + `spec_path` (came from a breakdown/spec — planning was done upstream)
   - Has non-empty `acceptance_criteria` (standalone ticket with explicit done markers)
5. Rank candidates by `priority` → `sort_order`
6. Standalone AFK tickets with no parent/spec and no acceptance criteria → skip

### Container Image

Lightweight image stripped from the existing devcontainer. Keeps only what's needed for autonomous code work:

**Include**:
- Python 3.12
- SQLite3
- git + GitHub CLI
- Claude Code CLI
- pytest + test dependencies
- Node.js (for Claude Code)

**Exclude** (compared to current devcontainer):
- WeasyPrint and its system deps
- Playwright and Chromium
- Any GUI/browser tooling

**No credentials mounted**:
- No Google Sheets API credentials (no `credentials/` mount)
- No SSH keys (no production server access)
- GH_TOKEN only (for push + PR creation)

**Mounted**:
- Tickets DB (`~/.tickets/tickets.db`) — read/write for status updates and notes
- Claude auth (`~/.claude`) — for API access

### Container Lifecycle

1. Dispatcher selects a ticket
2. `docker run` with the lightweight image
3. Inside the container:
   a. Clone the repo from GitHub (fresh, no shared state with host)
   b. Generate empty DBs with schema only (tests use conftest fixtures)
   c. Read ticket details and spec content (if `spec_path` exists)
   d. Run `claude -p` with the AFK work prompt + ticket context
4. On exit (success or failure), container is removed

### Agent Behavior Inside Container

The container runs a stripped-down version of the `/work` skill with key differences:

- **No user checkpoints** — all "stop and ask" gates are removed
- **Phase 3 confidence self-check** — instead of asking the user, the agent evaluates:
  - Do I understand the acceptance criteria?
  - Does my plan cover all of them?
  - Are there unresolved design decisions?
  - Does the ticket touch more scope than expected?
  - **High confidence** → proceed to implementation
  - **Low confidence** → stop, update notes with findings, exit

- **TDD flow** — same red-green-refactor loop as `/work`
- **Smoke tests** — must pass before PR creation
- **Max turns** — start high (~50), log actual turn count for tuning

### Outcomes

| Result | Ticket Status | Action |
|--------|--------------|--------|
| Success (PR opened) | `review` | Notes updated with PR link, ready for `/review` |
| Low confidence at planning | `open` | Notes updated with findings and concerns |
| Failure during implementation | `in_progress` | Notes updated with what went wrong |

### Context Injection

The dispatcher pre-packages context for the agent prompt:

- Ticket: title, description, acceptance_criteria, notes
- Spec content (read from `spec_path` if present)
- Sibling tickets (if `parent_id` exists — what's done, what's next)
- Project CLAUDE.md (codebase conventions, gotchas)

The agent does NOT get:
- Google Sheets API access
- Production server access
- `/audit` skill
- Interactive skills (`/interview`, `/ticket`, `/review`)

### Turn Logging

Each container run logs:
- Ticket ID
- Start/end time
- Turns used
- Outcome (success/low-confidence/failure)
- PR number (if created)

This data informs future tuning of max turns and helps identify ticket patterns that succeed vs fail autonomously.

## Future Considerations

- **Parallel containers** (up to ~5): no architecture change, just launch N containers. Review queue becomes the bottleneck.
- **Scheduled dispatch**: cron trigger instead of manual. Only after trust is established.
- **Cost tracking**: per-ticket API cost logging.
- **Auto-retry**: if a ticket fails on a transient issue, retry once before giving up.
- **Reference data snapshots**: if tickets need rate/location context, mount read-only SQLite snapshots.

## Out of Scope

- Auto-merge (always goes through `/review`)
- Production deployment
- Google Sheets integration
- Playwright/browser testing inside containers
