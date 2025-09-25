import sys
import pathlib
import time

# ensure parent directory of package is on path
sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))
from WebWork import db

def test_exists_helpers():
    conn = db.connect(':memory:')
    db.init_schema(conn)
    conn.execute("INSERT INTO dedup(url, guid, title_hash) VALUES (?,?,?)", (
        'http://example.com', 'guid1', 'hash1'))
    assert db.exists_url(conn, 'http://example.com')
    assert db.exists_guid(conn, 'guid1')
    assert db.exists_title_hash(conn, 'hash1')
    assert not db.exists_url(conn, 'http://other.com')


def test_migrate_existing_items():
    conn = db.connect(':memory:')
    # simulate old schema with only items table
    conn.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            guid TEXT,
            title TEXT NOT NULL,
            title_hash TEXT,
            content TEXT,
            source TEXT,
            published_at TEXT,
            image_url TEXT,
            added_ts INTEGER DEFAULT (strftime('%s','now'))
        );
        """
    )
    conn.execute("INSERT INTO items (url, guid, title, title_hash) VALUES (?,?,?,?)",
                 ('http://example.com', 'guid1', 'Title', 'hash1'))
    conn.commit()
    # run new schema init which should create dedup and migrate existing rows
    db.init_schema(conn)
    assert db.exists_url(conn, 'http://example.com')
    assert db.exists_guid(conn, 'guid1')
    assert db.exists_title_hash(conn, 'hash1')


def test_prune_old_records():
    conn = db.connect(':memory:')
    db.init_schema(conn)
    now = int(time.time())
    old_ts = now - 90 * 86400
    fresh_ts = now - 5 * 86400

    conn.execute(
        "INSERT INTO items (url, guid, title, title_hash, added_ts) VALUES (?,?,?,?,?)",
        ('http://old.example', 'old-guid', 'Old title', 'hash-old', old_ts),
    )
    conn.execute(
        "INSERT INTO dedup (url, guid, title_hash, added_ts) VALUES (?,?,?,?)",
        ('http://old.example', 'old-guid', 'hash-old', old_ts),
    )
    conn.execute(
        "INSERT INTO items (url, guid, title, title_hash, added_ts) VALUES (?,?,?,?,?)",
        ('http://new.example', 'new-guid', 'New title', 'hash-new', fresh_ts),
    )
    conn.execute(
        "INSERT INTO dedup (url, guid, title_hash, added_ts) VALUES (?,?,?,?)",
        ('http://new.example', 'new-guid', 'hash-new', fresh_ts),
    )
    conn.commit()

    removed = db.prune_old_records(
        conn,
        items_ttl_days=30,
        dedup_ttl_days=30,
        batch_limit=10,
    )
    assert removed == {"items": 1, "dedup": 1}
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dedup").fetchone()[0] == 1

    # TTL disabled should not remove anything
    removed_disabled = db.prune_old_records(
        conn,
        items_ttl_days=0,
        dedup_ttl_days=0,
        batch_limit=10,
    )
    assert removed_disabled == {"items": 0, "dedup": 0}
