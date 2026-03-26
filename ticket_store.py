"""
Ticket Store — SQLite storage for ticket/task tracking.

Stores tickets with priority, status, category, branch tracking,
parent-child relationships, and notes. Designed for Claude Code
skills integration via sqlite3 CLI.
"""

import os
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
from contextlib import contextmanager


VALID_STATUSES = ('open', 'in_progress', 'review', 'live_testing', 'tabled', 'completed', 'cancelled')
VALID_PRIORITIES = ('P1', 'P2', 'P3')
VALID_CATEGORIES = ('bug', 'discovery', 'enhancement', 'feature', 'infrastructure')

# Default DB location — user-scoped, project-independent
DEFAULT_DB_PATH = Path.home() / '.tickets' / 'tickets.db'


class TicketStore:
    """
    Stores and retrieves tickets from SQLite database.

    Single table design — keeps it simple for a solo dev workflow.
    """

    def __init__(self, db_path: str = None):
        """
        Initialize the ticket store.

        Args:
            db_path: Path to SQLite database.
                     Resolves in order: explicit arg > TICKET_DB_PATH env var > ~/.tickets/tickets.db
        """
        if db_path is None:
            db_path = os.environ.get('TICKET_DB_PATH', str(DEFAULT_DB_PATH))

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema and run migrations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    priority TEXT DEFAULT 'P2',
                    status TEXT DEFAULT 'open',
                    category TEXT DEFAULT 'feature',
                    branch TEXT DEFAULT '',
                    depends_on TEXT DEFAULT '',
                    parent_id INTEGER DEFAULT NULL,
                    spec_path TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0,
                    notes TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_id) REFERENCES tickets(id) ON DELETE SET NULL
                )
            ''')

            # Migrate from backlog_items if that table exists (one-time migration)
            tables = {row[0] for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if 'backlog_items' in tables and 'tickets' in tables:
                # Check if tickets table is empty and backlog_items has data
                ticket_count = cursor.execute('SELECT COUNT(*) FROM tickets').fetchone()[0]
                backlog_count = cursor.execute('SELECT COUNT(*) FROM backlog_items').fetchone()[0]
                if ticket_count == 0 and backlog_count > 0:
                    # Select only columns that exist in tickets table
                    tickets_cols = [row[1] for row in cursor.execute('PRAGMA table_info(tickets)').fetchall()]
                    backlog_cols = {row[1] for row in cursor.execute('PRAGMA table_info(backlog_items)').fetchall()}
                    shared_cols = [c for c in tickets_cols if c in backlog_cols]
                    cols = ', '.join(shared_cols)
                    cursor.execute(f'INSERT INTO tickets ({cols}) SELECT {cols} FROM backlog_items')

            # Migrate existing databases: add columns if missing
            existing_cols = {row[1] for row in cursor.execute('PRAGMA table_info(tickets)').fetchall()}
            if 'parent_id' not in existing_cols:
                cursor.execute('ALTER TABLE tickets ADD COLUMN parent_id INTEGER DEFAULT NULL REFERENCES tickets(id) ON DELETE SET NULL')
            if 'spec_path' not in existing_cols:
                cursor.execute("ALTER TABLE tickets ADD COLUMN spec_path TEXT DEFAULT ''")

            # Indexes for common queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_sort ON tickets(priority, sort_order)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tickets_parent ON tickets(parent_id)')

    # ── Create ────────────────────────────────────────────────────────

    def create_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new ticket.

        Args:
            data: Dict with item fields (title required, rest optional)

        Returns:
            Dict with created item including id
        """
        status = data.get('status', 'open')
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {', '.join(VALID_STATUSES)}")
        priority = data.get('priority', 'P2')
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority '{priority}'. Must be one of: {', '.join(VALID_PRIORITIES)}")
        category = data.get('category', 'feature')
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category '{category}'. Must be one of: {', '.join(VALID_CATEGORIES)}")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                'SELECT COALESCE(MAX(sort_order), 0) + 1 as next_order '
                'FROM tickets WHERE priority = ?',
                (priority,)
            )
            next_order = cursor.fetchone()['next_order']

            cursor.execute('''
                INSERT INTO tickets
                (title, description, priority, status, category, branch,
                 depends_on, parent_id, spec_path, sort_order, notes,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.get('title', ''),
                data.get('description', ''),
                priority,
                data.get('status', 'open'),
                data.get('category', 'feature'),
                data.get('branch', ''),
                data.get('depends_on', ''),
                data.get('parent_id'),
                data.get('spec_path', ''),
                data.get('sort_order', next_order),
                data.get('notes', ''),
                now,
                now,
            ))

            item_id = cursor.lastrowid
            return self.get_item(item_id, conn=conn)

    # ── Read ──────────────────────────────────────────────────────────

    def get_item(self, item_id: int, conn=None) -> Optional[Dict[str, Any]]:
        """Get a single ticket by ID."""
        def _fetch(c):
            cursor = c.cursor()
            cursor.execute('SELECT * FROM tickets WHERE id = ?', (item_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

        if conn:
            return _fetch(conn)

        with self._get_connection() as conn:
            return _fetch(conn)

    def list_items(self, status: str = None, priority: str = None,
                   category: str = None, search: str = None,
                   order_by: str = 'priority_sort') -> List[Dict[str, Any]]:
        """
        List tickets with optional filters.

        Args:
            status: Filter by status
            priority: Filter by priority (P1, P2, P3)
            category: Filter by category
            search: Search in title, description, and notes
            order_by: Sort order - 'priority_sort' (default), 'created_at', 'updated_at'
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            conditions = []
            params = []

            if status:
                conditions.append('status = ?')
                params.append(status)
            if priority:
                conditions.append('priority = ?')
                params.append(priority)
            if category:
                conditions.append('category = ?')
                params.append(category)
            if search:
                conditions.append('(title LIKE ? OR description LIKE ? OR notes LIKE ?)')
                search_term = f'%{search}%'
                params.extend([search_term, search_term, search_term])

            where_clause = ''
            if conditions:
                where_clause = 'WHERE ' + ' AND '.join(conditions)

            if order_by == 'created_at':
                order_clause = 'ORDER BY created_at DESC'
            elif order_by == 'updated_at':
                order_clause = 'ORDER BY updated_at DESC'
            else:
                order_clause = 'ORDER BY priority ASC, sort_order ASC, created_at ASC'

            query = f'SELECT * FROM tickets {where_clause} {order_clause}'
            cursor.execute(query, params)

            return [dict(row) for row in cursor.fetchall()]

    def get_children(self, parent_id: int) -> List[Dict[str, Any]]:
        """Get all child tickets for a given parent item."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM tickets WHERE parent_id = ? ORDER BY sort_order ASC',
                (parent_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_counts(self) -> Dict[str, Any]:
        """Get summary counts by status and priority."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT status, COUNT(*) as count
                FROM tickets GROUP BY status
            ''')
            by_status = {row['status']: row['count'] for row in cursor.fetchall()}

            cursor.execute('''
                SELECT priority, COUNT(*) as count
                FROM tickets
                WHERE status NOT IN ('completed', 'cancelled')
                GROUP BY priority
            ''')
            by_priority = {row['priority']: row['count'] for row in cursor.fetchall()}

            cursor.execute('SELECT COUNT(*) as total FROM tickets')
            total = cursor.fetchone()['total']

            return {
                'total': total,
                'by_status': by_status,
                'by_priority': by_priority,
            }

    # ── Update ────────────────────────────────────────────────────────

    def update_item(self, item_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Update a ticket.

        Args:
            item_id: Item ID to update
            data: Dict with fields to update

        Returns:
            Updated item dict, or None if not found
        """
        allowed_fields = {
            'title', 'description', 'priority', 'status', 'category',
            'branch', 'depends_on', 'parent_id', 'spec_path', 'sort_order',
            'notes'
        }

        if 'status' in data and data['status'] not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{data['status']}'. Must be one of: {', '.join(VALID_STATUSES)}")
        if 'priority' in data and data['priority'] not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority '{data['priority']}'. Must be one of: {', '.join(VALID_PRIORITIES)}")
        if 'category' in data and data['category'] not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category '{data['category']}'. Must be one of: {', '.join(VALID_CATEGORIES)}")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT id FROM tickets WHERE id = ?', (item_id,))
            if not cursor.fetchone():
                return None

            updates = []
            params = []
            for field, value in data.items():
                if field in allowed_fields:
                    updates.append(f'{field} = ?')
                    params.append(value)

            if not updates:
                return self.get_item(item_id, conn=conn)

            updates.append('updated_at = ?')
            params.append(datetime.now().isoformat())
            params.append(item_id)

            query = f'UPDATE tickets SET {", ".join(updates)} WHERE id = ?'
            cursor.execute(query, params)

            return self.get_item(item_id, conn=conn)

    # ── Delete ────────────────────────────────────────────────────────

    def delete_item(self, item_id: int) -> bool:
        """Delete a ticket. Returns True if deleted, False if not found."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tickets WHERE id = ?', (item_id,))
            return cursor.rowcount > 0

    def reorder_items(self, item_orders: List[Dict[str, int]]) -> bool:
        """Update sort_order for multiple items at once."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            for item in item_orders:
                cursor.execute(
                    'UPDATE tickets SET sort_order = ?, updated_at = ? WHERE id = ?',
                    (item['sort_order'], now, item['id'])
                )

            return True


# Singleton instance
_store = None


def get_ticket_store() -> TicketStore:
    """Get or create the singleton ticket store instance."""
    global _store
    if _store is None:
        _store = TicketStore()
    return _store
