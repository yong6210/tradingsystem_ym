"""Atomic local receipts for the continuous paper account; no order routing."""
import hashlib
import json
from pathlib import Path
import sqlite3
from .causal_intents import encode
from .quote_paper_account import transition


class PaperStore:
    def __init__(self,path,binding,initial=None):
        exists=Path(path).exists()
        if not exists and initial is None:raise ValueError('initial paper state required')
        self.db=sqlite3.connect(path)
        try:
            self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA synchronous=FULL')
            if not exists:
                if initial['costs']!=binding['costs'] or initial['risk']!=binding['risk']:
                    raise ValueError('initial account policy differs from binding')
                with self.db:
                    self.db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                    self.db.execute('CREATE TABLE receipts (id TEXT PRIMARY KEY,seq INTEGER UNIQUE,session TEXT,kind TEXT,raw TEXT,sha256 TEXT,clock TEXT,state TEXT,outputs TEXT)')
                    self.db.executemany('INSERT INTO meta VALUES (?,?)',[('binding',encode(binding)),('initial',encode(initial))])
            if self.db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0]!=encode(binding):
                raise ValueError('paper database binding changed')
        except Exception:
            self.db.close();raise

    def state(self):
        row=self.db.execute('SELECT state FROM receipts ORDER BY seq DESC LIMIT 1').fetchone()
        return json.loads(row[0] if row else self.db.execute("SELECT value FROM meta WHERE key='initial'").fetchone()[0])

    def commit(self,request_id,kind,raw,clock,session,*,before_commit=None):
        digest=hashlib.sha256(raw.encode()).hexdigest()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT session,kind,sha256,clock,outputs FROM receipts WHERE id=?',(request_id,)).fetchone()
            if old:
                if old[:4]!=(session,kind,digest,encode(clock)):raise ValueError('conflicting paper request id')
                return json.loads(old[4])
            state,outputs=transition(self.state(),kind,json.loads(raw),clock,session)
            sequence=self.db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM receipts').fetchone()[0]
            self.db.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?)',
                (request_id,sequence,session,kind,raw,digest,encode(clock),encode(state),encode(outputs)))
            if before_commit:before_commit()
        return outputs

    def close(self):self.db.close()
