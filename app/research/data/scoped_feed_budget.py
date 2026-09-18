"""A capture namespace sharing its supervisor's one lock and reservation pool."""
from .durable_capture_log import JournalError
from .reserved_feed_storage import ReservedStorageBudget


class ScopedFeedBudget(ReservedStorageBudget):
    """No second byte allowance or lock. Closing a view never closes its owner."""
    def __init__(self, owner, root):
        self.owner = owner
        self.root = owner.path(root)
        if self.root == owner.root:
            raise JournalError('capture namespace must be below supervisor')
        self.contract = owner.contract

    @property
    def failed(self): return self.owner.failed

    @failed.setter
    def failed(self, value): self.owner.failed = value

    @property
    def closed(self): return self.owner.closed

    def path(self, path):
        path = self.owner.path(path)
        if not path.is_relative_to(self.root): raise JournalError('outside capture namespace')
        return path

    def check(self, growth): return self.owner.check(growth)
    def mutation(self): return self.owner.mutation()
    def reconcile(self): return self.owner.reconcile()
    def reserve(self, key, amount): return self.owner.reserve(key, amount)
    def release(self, key): return self.owner.release(key)
    def spend(self, key): return self.owner.spend(key)
    def snapshot(self): return self.owner.snapshot()
    def _refresh(self, path): return self.owner._refresh(self.path(path))
    def append(self, stream, data):
        self.path(stream.name)
        return self.owner.append(stream, data)
    def atomic_json(self, path, value, hook=lambda stage: None):
        return self.owner.atomic_json(self.path(path), value, hook)
    def close(self): pass
