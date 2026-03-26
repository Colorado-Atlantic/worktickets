# worktickets

SQLite-backed ticket tracking system designed for Claude Code skills integration.

## Setup

```bash
# Default DB location: ~/.tickets/tickets.db
# Override with env var:
export TICKET_DB_PATH=/path/to/tickets.db
```

## Usage

### From Claude Code skills (sqlite3 CLI)

```bash
# List open tickets
sqlite3 ~/.tickets/tickets.db "SELECT id, title, priority, status FROM tickets WHERE status NOT IN ('completed','cancelled') ORDER BY priority, sort_order"

# Create a ticket
sqlite3 ~/.tickets/tickets.db "INSERT INTO tickets (title, description, priority, status, category, created_at, updated_at) VALUES ('title', 'desc', 'P2', 'open', 'feature', datetime('now'), datetime('now'))"

# Update status
sqlite3 ~/.tickets/tickets.db "UPDATE tickets SET status='in_progress', updated_at=datetime('now') WHERE id=N"

# Append to notes
sqlite3 ~/.tickets/tickets.db "UPDATE tickets SET notes=notes || char(10) || '[2026-03-26] note here', updated_at=datetime('now') WHERE id=N"
```

### From Python

```python
from ticket_store import TicketStore, get_ticket_store

store = get_ticket_store()
store.create_item({'title': 'New feature', 'priority': 'P1'})
items = store.list_items(status='open')
```

## Schema

| Column | Type | Default | Notes |
|--------|------|---------|-------|
| id | INTEGER | auto | Primary key |
| title | TEXT | required | |
| description | TEXT | '' | |
| priority | TEXT | 'P2' | P1, P2, P3 |
| status | TEXT | 'open' | open, in_progress, review, live_testing, tabled, completed, cancelled |
| category | TEXT | 'feature' | bug, discovery, enhancement, feature, infrastructure |
| branch | TEXT | '' | Git branch name |
| depends_on | TEXT | '' | Comma-separated ticket IDs |
| parent_id | INTEGER | NULL | FK to parent ticket |
| spec_path | TEXT | '' | Path to spec document |
| sort_order | INTEGER | 0 | For manual ordering |
| notes | TEXT | '' | Append-only log |
| created_at | DATETIME | now | |
| updated_at | DATETIME | now | |

## Tests

```bash
python -m pytest -v
```
