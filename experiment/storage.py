"""SQLite is the authoritative append-only attempt/observation log (FULL durability)."""
import fcntl
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .common import canonical, digest, now, require

@contextmanager
def process_lock(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'collector.lock').open('a') as f:
        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Another collector/reconciler holds this split lock') from None
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)

class Store:
    def __init__(self, path, readonly=False):
        path = Path(path)
        if not readonly: path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(f'file:{path}?mode=ro' if readonly else path, uri=readonly)
        self.db.row_factory = sqlite3.Row
        if not readonly:
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, scientific_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observations (
                    scientific_id TEXT PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS unique_event ON events(scientific_id, attempt, kind);
                CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'append-only events'); END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'append-only events'); END;
                CREATE TRIGGER IF NOT EXISTS observations_no_update BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
                CREATE TRIGGER IF NOT EXISTS observations_no_delete BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
            ''')

    def close(self): self.db.close()

    def events(self):
        return [dict(sequence=r['sequence'], scientific_id=r['scientific_id'], attempt=r['attempt'],
                     kind=r['kind'], **json.loads(r['payload'])) for r in self.db.execute('SELECT * FROM events ORDER BY sequence')]

    def observations(self):
        result = {}
        for row in self.db.execute('SELECT * FROM observations ORDER BY scientific_id'):
            data = json.loads(row['payload'])
            require(digest(data) == row['sha256'], 'Observation hash mismatch')
            require(data['scientific_id'] == row['scientific_id'], 'Observation identity mismatch')
            result[row['scientific_id']] = data
        return result

    def _event(self, sid, attempt, kind, payload):
        self.db.execute('INSERT INTO events(scientific_id,attempt,kind,payload) VALUES(?,?,?,?)',
                        (sid, attempt, kind, canonical(payload)))

    def start(self, sid, attempt, payload):
        require(self.db.execute('SELECT 1 FROM observations WHERE scientific_id=?', (sid,)).fetchone() is None,
                'Refusing regeneration of committed observation')
        with self.db: self._event(sid, attempt, 'start', payload)

    def fail(self, sid, attempt, payload):
        with self.db: self._event(sid, attempt, 'finish', payload)

    def commit(self, observation):
        sid, attempt = observation['scientific_id'], observation['attempt']
        # Observation and terminal attempt event are one transaction. No dual-file crash window.
        with self.db:
            self.db.execute('INSERT INTO observations VALUES(?,?,?)', (sid, canonical(observation), digest(observation)))
            self._event(sid, attempt, 'finish', {'at': now(), 'status': observation['status'], 'terminal': True,
                'latency_seconds': observation['latency_seconds'], 'observation_sha256': digest(observation)})

    def recover_inflight(self):
        events = self.events()
        finished = {(e['scientific_id'], e['attempt']) for e in events if e['kind'] == 'finish'}
        for e in events:
            if e['kind'] == 'start' and (e['scientific_id'], e['attempt']) not in finished:
                # We cannot know whether the remote server generated a response before a crash.
                # Preserve uncertainty; never auto-regenerate this scientific ID.
                self.fail(e['scientific_id'], e['attempt'], {'at': now(), 'status': 'uncertain_interruption',
                    'terminal': True, 'retryable': False, 'latency_seconds': None})

    def fingerprint(self):
        return digest({'events': self.events(), 'observations': self.observations()})
