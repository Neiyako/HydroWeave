from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import fetch_month as fm  # noqa: E402


def test_requeue_recovers_only_expired_running_and_failed(tmp_path):
    db_path = tmp_path / 'manifest.db'
    now = datetime.now(UTC)
    expired = (now - timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')
    future = (now + timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, state TEXT, worker_id TEXT, "
            "started_at TEXT, finished_at TEXT, heartbeat_at TEXT, lease_expires_at TEXT, "
            "last_transition_at TEXT, scheduled_at TEXT, last_error TEXT)")
        rows = [
            ('failed', 'FAILED', future),
            ('expired-running', 'RUNNING', expired),
            ('active-running', 'RUNNING', future),
        ]
        db.executemany(
            "INSERT INTO tasks VALUES (?, ?, 'worker', 'start', 'finish', 'heartbeat', ?, "
            "'transition', 'scheduled', 'error')", rows)
        db.commit()

    fm._requeue_transient(db_path, ['failed', 'expired-running', 'active-running'])

    with sqlite3.connect(db_path) as db:
        states = dict(db.execute("SELECT task_id,state FROM tasks"))
    assert states['failed'] == 'QUEUED'
    assert states['expired-running'] == 'QUEUED'
    assert states['active-running'] == 'RUNNING'

    fm._requeue_transient(db_path, ['active-running'], force_running=True)
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT state FROM tasks WHERE task_id='active-running'").fetchone()[0] == 'QUEUED'
