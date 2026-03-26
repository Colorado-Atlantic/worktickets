# worktickets

Standalone ticket tracking system. SQLite-backed, designed for Claude Code skills.

## Key Files
- `ticket_store.py` — TicketStore class, singleton via `get_ticket_store()`
- `tests/test_ticket_store.py` — 28 tests covering CRUD, filtering, parent-child, migration

## DB Location
- Default: `~/.tickets/tickets.db`
- Override: `TICKET_DB_PATH` env var
- Table name: `tickets`

## Valid Values
- **Statuses**: open, in_progress, review, live_testing, tabled, completed, cancelled
- **Priorities**: P1, P2, P3
- **Categories**: bug, discovery, enhancement, feature, infrastructure

## Skills Integration
Skills in other repos use `sqlite3` CLI to read/write directly:
```bash
sqlite3 ~/.tickets/tickets.db "SELECT ..."
```
No Python import needed — the DB is the interface.

## Migration
If a DB contains a `backlog_items` table but no `tickets` data, TicketStore auto-migrates on first open.
