"""Private SQLite authority: immutable specs, CAS, approvals and append-only events.

Only a trusted host controller can open this store. Calling Python methods is not
an authentication boundary; transport authorization must derive principals from
OS credentials. No caller-provided owner_id is a principal.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import stat

from .schema import ControlError, canonical, decode, require


class Store:
    def __init__(self, root, *, initialize=False):
        self.root = Path(root)
        require(self.root.is_absolute() and self.root != Path("/")
                and self.root.resolve() == self.root, "private_store_required")
        if initialize:
            self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o700, "private_store_required")
        self.path = self.root / "authority.sqlite3"
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and stat.S_IMODE(info.st_mode) == 0o600, "private_database_required")
        elif initialize:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        else:
            raise ControlError("store_not_initialized")
        if initialize:
            with self.transaction() as db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS documents (
                      kind TEXT NOT NULL, id TEXT NOT NULL, value TEXT NOT NULL,
                      PRIMARY KEY(kind,id));
                    CREATE TABLE IF NOT EXISTS events (
                      seq INTEGER PRIMARY KEY, operation TEXT NOT NULL,
                      phase TEXT NOT NULL, value TEXT NOT NULL);
                    PRAGMA user_version=1;
                """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=0, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            if db.in_transaction:
                db.commit()
        except sqlite3.OperationalError as exc:
            if db.in_transaction:
                db.rollback()
            raise ControlError("authority_busy_or_unavailable") from exc
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def get(db, kind, key):
        row = db.execute("SELECT value FROM documents WHERE kind=? AND id=?", (kind, key)).fetchone()
        require(row is not None, "not_found")
        return decode(row[0])

    @staticmethod
    def get_value(row):
        """Decode a row selected directly from the documents table."""
        return decode(row[0])

    @staticmethod
    def put(db, kind, key, value, *, immutable=False):
        encoded = canonical(value)
        if immutable:
            row = db.execute("SELECT value FROM documents WHERE kind=? AND id=?", (kind, key)).fetchone()
            require(row is None or row[0] == encoded, "immutable_document_conflict")
            db.execute("INSERT OR IGNORE INTO documents VALUES(?,?,?)", (kind, key, encoded))
        else:
            db.execute("INSERT INTO documents VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET value=excluded.value",
                       (kind, key, encoded))

    @staticmethod
    def event(db, operation, phase, value):
        db.execute("INSERT INTO events(operation,phase,value) VALUES(?,?,?)", (operation, phase, canonical(value)))

    def read(self, kind, key):
        with self.transaction() as db:
            return self.get(db, kind, key)
