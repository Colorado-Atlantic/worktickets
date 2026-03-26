"""
Tests for TicketStore — CRUD, filtering, parent-child, migration.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import pytest

from ticket_store import (
    TicketStore, get_ticket_store,
    VALID_STATUSES, VALID_PRIORITIES, VALID_CATEGORIES,
)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def store(temp_db):
    return TicketStore(db_path=temp_db)


@pytest.fixture
def sample_ticket():
    return {
        'title': 'Add widget feature',
        'description': 'Build a widget that does things',
        'priority': 'P2',
        'status': 'open',
        'category': 'feature',
    }


# ── Create ────────────────────────────────────────────────────────

class TestCreate:
    def test_create_returns_id(self, store, sample_ticket):
        item = store.create_item(sample_ticket)
        assert item['id'] > 0
        assert item['title'] == 'Add widget feature'

    def test_create_defaults(self, store):
        item = store.create_item({'title': 'Minimal ticket'})
        assert item['priority'] == 'P2'
        assert item['status'] == 'open'
        assert item['category'] == 'feature'

    def test_create_invalid_status_raises(self, store):
        with pytest.raises(ValueError, match='Invalid status'):
            store.create_item({'title': 'Bad', 'status': 'nope'})

    def test_create_invalid_priority_raises(self, store):
        with pytest.raises(ValueError, match='Invalid priority'):
            store.create_item({'title': 'Bad', 'priority': 'P0'})

    def test_create_invalid_category_raises(self, store):
        with pytest.raises(ValueError, match='Invalid category'):
            store.create_item({'title': 'Bad', 'category': 'magic'})

    def test_sort_order_auto_increments(self, store):
        a = store.create_item({'title': 'First', 'priority': 'P1'})
        b = store.create_item({'title': 'Second', 'priority': 'P1'})
        assert b['sort_order'] == a['sort_order'] + 1


# ── Read ──────────────────────────────────────────────────────────

class TestRead:
    def test_get_item(self, store, sample_ticket):
        created = store.create_item(sample_ticket)
        fetched = store.get_item(created['id'])
        assert fetched['title'] == sample_ticket['title']

    def test_get_missing_returns_none(self, store):
        assert store.get_item(9999) is None

    def test_list_all(self, store):
        store.create_item({'title': 'A'})
        store.create_item({'title': 'B'})
        items = store.list_items()
        assert len(items) == 2

    def test_list_filter_by_status(self, store):
        store.create_item({'title': 'Open', 'status': 'open'})
        store.create_item({'title': 'Done', 'status': 'completed'})
        items = store.list_items(status='open')
        assert len(items) == 1
        assert items[0]['title'] == 'Open'

    def test_list_filter_by_priority(self, store):
        store.create_item({'title': 'Urgent', 'priority': 'P1'})
        store.create_item({'title': 'Normal', 'priority': 'P2'})
        items = store.list_items(priority='P1')
        assert len(items) == 1

    def test_list_search(self, store):
        store.create_item({'title': 'Fix login bug'})
        store.create_item({'title': 'Add dashboard'})
        items = store.list_items(search='login')
        assert len(items) == 1
        assert items[0]['title'] == 'Fix login bug'

    def test_list_order_by_priority(self, store):
        store.create_item({'title': 'Low', 'priority': 'P3'})
        store.create_item({'title': 'High', 'priority': 'P1'})
        items = store.list_items()
        assert items[0]['priority'] == 'P1'

    def test_get_counts(self, store):
        store.create_item({'title': 'A', 'status': 'open', 'priority': 'P1'})
        store.create_item({'title': 'B', 'status': 'completed', 'priority': 'P2'})
        store.create_item({'title': 'C', 'status': 'open', 'priority': 'P2'})
        counts = store.get_counts()
        assert counts['total'] == 3
        assert counts['by_status']['open'] == 2
        assert counts['by_status']['completed'] == 1
        assert counts['by_priority']['P1'] == 1  # excludes completed


# ── Update ────────────────────────────────────────────────────────

class TestUpdate:
    def test_update_fields(self, store, sample_ticket):
        item = store.create_item(sample_ticket)
        updated = store.update_item(item['id'], {'status': 'in_progress'})
        assert updated['status'] == 'in_progress'

    def test_update_missing_returns_none(self, store):
        assert store.update_item(9999, {'status': 'open'}) is None

    def test_update_invalid_status_raises(self, store, sample_ticket):
        item = store.create_item(sample_ticket)
        with pytest.raises(ValueError):
            store.update_item(item['id'], {'status': 'bad'})

    def test_update_ignores_unknown_fields(self, store, sample_ticket):
        item = store.create_item(sample_ticket)
        updated = store.update_item(item['id'], {'title': 'New', 'fake_field': 'ignored'})
        assert updated['title'] == 'New'


# ── Delete ────────────────────────────────────────────────────────

class TestDelete:
    def test_delete_existing(self, store, sample_ticket):
        item = store.create_item(sample_ticket)
        assert store.delete_item(item['id']) is True
        assert store.get_item(item['id']) is None

    def test_delete_missing(self, store):
        assert store.delete_item(9999) is False


# ── Parent-Child ──────────────────────────────────────────────────

class TestParentChild:
    def test_create_with_parent(self, store):
        parent = store.create_item({'title': 'Epic'})
        child = store.create_item({'title': 'Task', 'parent_id': parent['id']})
        assert child['parent_id'] == parent['id']

    def test_get_children(self, store):
        parent = store.create_item({'title': 'Epic'})
        store.create_item({'title': 'Task 1', 'parent_id': parent['id']})
        store.create_item({'title': 'Task 2', 'parent_id': parent['id']})
        store.create_item({'title': 'Unrelated'})
        children = store.get_children(parent['id'])
        assert len(children) == 2


# ── Reorder ───────────────────────────────────────────────────────

class TestReorder:
    def test_reorder(self, store):
        a = store.create_item({'title': 'A'})
        b = store.create_item({'title': 'B'})
        store.reorder_items([
            {'id': a['id'], 'sort_order': 10},
            {'id': b['id'], 'sort_order': 5},
        ])
        items = store.list_items()
        assert items[0]['title'] == 'B'  # sort_order 5 first


# ── DB Path Resolution ────────────────────────────────────────────

class TestDbPath:
    def test_explicit_path(self, temp_db):
        store = TicketStore(db_path=temp_db)
        assert str(store.db_path) == temp_db

    def test_env_var_override(self, temp_db, monkeypatch):
        monkeypatch.setenv('TICKET_DB_PATH', temp_db)
        store = TicketStore()
        assert str(store.db_path) == temp_db

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, 'sub', 'dir', 'tickets.db')
            store = TicketStore(db_path=nested)
            store.create_item({'title': 'Test'})
            assert os.path.exists(nested)


# ── Migration from backlog_items ──────────────────────────────────

class TestMigration:
    def test_migrates_backlog_items_to_tickets(self, temp_db):
        """If a DB has backlog_items but no tickets, data is migrated."""
        # Create a DB with the old schema
        conn = sqlite3.connect(temp_db)
        conn.execute('''
            CREATE TABLE backlog_items (
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute("INSERT INTO backlog_items (title) VALUES ('Old ticket')")
        conn.execute("INSERT INTO backlog_items (title) VALUES ('Another old one')")
        conn.commit()
        conn.close()

        # Opening with TicketStore should migrate
        store = TicketStore(db_path=temp_db)
        items = store.list_items()
        assert len(items) == 2
        assert items[0]['title'] in ('Old ticket', 'Another old one')

    def test_no_duplicate_migration(self, temp_db):
        """If tickets table already has data, don't re-migrate."""
        conn = sqlite3.connect(temp_db)
        conn.execute('''
            CREATE TABLE backlog_items (
                id INTEGER PRIMARY KEY, title TEXT, description TEXT DEFAULT '',
                priority TEXT DEFAULT 'P2', status TEXT DEFAULT 'open',
                category TEXT DEFAULT 'feature', branch TEXT DEFAULT '',
                depends_on TEXT DEFAULT '', parent_id INTEGER,
                spec_path TEXT DEFAULT '', sort_order INTEGER DEFAULT 0,
                notes TEXT DEFAULT '', created_at DATETIME, updated_at DATETIME
            )
        ''')
        conn.execute("INSERT INTO backlog_items (id, title) VALUES (1, 'Old')")
        conn.execute('''
            CREATE TABLE tickets (
                id INTEGER PRIMARY KEY, title TEXT, description TEXT DEFAULT '',
                priority TEXT DEFAULT 'P2', status TEXT DEFAULT 'open',
                category TEXT DEFAULT 'feature', branch TEXT DEFAULT '',
                depends_on TEXT DEFAULT '', parent_id INTEGER,
                spec_path TEXT DEFAULT '', sort_order INTEGER DEFAULT 0,
                notes TEXT DEFAULT '', created_at DATETIME, updated_at DATETIME
            )
        ''')
        conn.execute("INSERT INTO tickets (id, title) VALUES (1, 'Already migrated')")
        conn.commit()
        conn.close()

        store = TicketStore(db_path=temp_db)
        items = store.list_items()
        assert len(items) == 1
        assert items[0]['title'] == 'Already migrated'
