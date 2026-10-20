"""A request-local, immutable SQL view shared safely by retrieval threads."""

from contextlib import contextmanager
from threading import RLock

from remind.store import SQLAlchemyMemoryStore


class ReadSnapshotStore(SQLAlchemyMemoryStore):
    def __init__(self, source, connection):
        self.engine = source.engine
        self.db_url = source.db_url
        self._vec_backend = source._vec_backend
        self._vec_dimensions = source._vec_dimensions
        self._fts_backend = source._fts_backend
        self.connection = connection
        self.lock = RLock()

    @contextmanager
    def _connect(self):
        with self.lock:
            yield self.connection

    @contextmanager
    def transaction(self):
        raise RuntimeError("Read snapshots cannot be mutated")
        yield
