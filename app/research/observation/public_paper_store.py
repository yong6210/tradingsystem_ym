"""Atomic public response + query + derived paper account journal."""
import hashlib
import json
from pathlib import Path
import sqlite3

from .causal_intents import encode
from .public_paper import transition


class PublicPaperStore:
    def __init__(self,path,binding,initial=None):
        exists = Path(path).exists()
        if not exists and initial is None:
            raise ValueError('initial public paper state required')
        self.db = sqlite3.connect(path)
        try:
            self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.execute('PRAGMA synchronous=FULL')
            if not exists:
                account = initial['account']
                if account['costs']!=binding['costs'] or account['risk']!=binding['risk']:
                    raise ValueError('account/binding policy differs')
                with self.db:
                    self.db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                    self.db.execute('CREATE TABLE receipts (id TEXT PRIMARY KEY,seq INTEGER UNIQUE,session TEXT,kind TEXT,raw TEXT,sha256 TEXT,clock TEXT,query TEXT,state TEXT,outputs TEXT)')
                    self.db.executemany('INSERT INTO meta VALUES (?,?)',
                        [('binding',encode(binding)),('initial',encode(initial))])
            if self.db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0]!=encode(binding):
                raise ValueError('public paper binding changed')
        except Exception:
            self.db.close()
            raise

    def state(self):
        row = self.db.execute('SELECT state FROM receipts ORDER BY seq DESC LIMIT 1').fetchone()
        raw = row[0] if row else self.db.execute("SELECT value FROM meta WHERE key='initial'").fetchone()[0]
        return json.loads(raw)

    def commit(self,request_id,kind,raw,clock,session,query=None,*,before_commit=None):
        sha = hashlib.sha256(raw.encode()).hexdigest()
        query = query or {}
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT session,kind,sha256,clock,query,outputs FROM receipts WHERE id=?',
                                  (request_id,)).fetchone()
            if old:
                if old[:5]!=(session,kind,sha,encode(clock),encode(query)):
                    raise ValueError('conflicting public request id')
                return json.loads(old[5])
            # Malformed JSON is also a committed diagnostic; raw bytes live in
            # the transport archive. None fails the typed channel validator.
            try:body = json.loads(raw)
            except json.JSONDecodeError:body = None
            state,outputs = transition(self.state(),kind,body,clock,session,query)
            seq = self.db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM receipts').fetchone()[0]
            self.db.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?,?)',
                (request_id,seq,session,kind,raw,sha,encode(clock),encode(query),encode(state),encode(outputs)))
            if before_commit:before_commit()
        return outputs

    def close(self):
        self.db.close()
