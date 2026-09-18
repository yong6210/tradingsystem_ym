"""Read-only locked journal snapshot with one full validation before replay.

Uses the frozen record/hash validators. A cooperative writer cannot alter the
snapshot while it is consumed. Uncooperative external edits remain unsupported.
"""
import hashlib
from pathlib import Path

from .durable_capture_log import (
    JournalError, load_state, scan_records, lock_directory, encoded, file_hash,
)


class VerifiedJournalView:
    def __init__(self, directory, *, summarize_payload=False):
        self.directory = Path(directory)
        self.summarize_payload = summarize_payload
        self.lock = None
        self.used = False
        self.payload_bytes = 0
        self.payload_sha256 = None

    def __enter__(self):
        if self.lock is not None or self.used:
            raise JournalError('snapshot cannot be reopened')
        self.lock = lock_directory(self.directory)
        try:
            self.meta, self.cp = load_state(self.directory)
            digest = hashlib.sha256()
            # Finish this entire pass, including the terminal checkpoint check,
            # before any record is made available to the replay consumer.
            for row in scan_records(self.directory, self.meta, self.cp):
                if self.summarize_payload:
                    line = encoded(row['payload'])
                    self.payload_bytes += len(line)
                    digest.update(line)
            self.payload_sha256 = digest.hexdigest() if self.summarize_payload else None
            known = {entry['name']:entry['bytes'] for entry in self.cp['segments']}
            tails = []
            for path in sorted(self.directory.glob('segment-*.jsonl')):
                if path.is_symlink():
                    raise JournalError('symlink segment refused')
                offset = known.get(path.name, 0)
                size = path.stat().st_size
                if size > offset:
                    tails.append(dict(name=path.name, offset=offset, bytes=size-offset,
                                      sha256=file_hash(path, start=offset)))
            self.recovery = dict(last_sequence=self.cp['last_sequence'],
                last_record_sha256=self.cp['last_record_sha256'], committed_segments=len(self.cp['segments']),
                uncommitted_suffixes=tails,
                pending_checkpoint_files=sorted(p.name for p in self.directory.glob('.checkpoint.json.*.tmp')),
                live_market_state_restored=False)
            return self
        except BaseException:
            self.close()
            raise

    def records(self):
        if self.lock is None or self.used:
            raise JournalError('snapshot closed or already consumed')
        self.used = True
        for row in scan_records(self.directory, self.meta, self.cp):
            if self.lock is None:
                raise JournalError('snapshot closed during consumption')
            yield row

    def close(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None
        self.used = True

    def __exit__(self, *args):
        self.close()
