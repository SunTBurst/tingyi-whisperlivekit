"""Transactional incremental meetings with a small recoverable JSON manifest."""
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def _json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _db_path(path, manifest=None):
    path=Path(path)
    filename=(manifest or {}).get('storage',{}).get('file') or path.with_suffix('.sqlite3').name
    if not isinstance(filename,str) or Path(filename).name!=filename or '/' in filename or '\\' in filename:
        raise ValueError('会议数据库必须位于记录文件所在目录')
    return path.parent/filename


class MeetingStore:
    def __init__(self,path,metadata=None,*,create=True):
        self.path=Path(path)
        self.db_path=_db_path(self.path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if not create and not self.db_path.is_file(): raise FileNotFoundError(self.db_path)
        self.connection=sqlite3.connect(str(self.db_path),timeout=2)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.execute('PRAGMA busy_timeout=2000')
        if create:
            self.connection.executescript('CREATE TABLE IF NOT EXISTS rows(id TEXT PRIMARY KEY,start REAL NOT NULL,payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,payload TEXT NOT NULL); CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,payload TEXT NOT NULL);')
            self.connection.commit()
        columns={item[1] for item in self.connection.execute('PRAGMA table_info(events)')}
        if 'fingerprint' not in columns:
            self.connection.execute('ALTER TABLE events ADD COLUMN fingerprint TEXT')
            self.connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS event_fingerprint ON events(fingerprint)')
            self.connection.commit()
        found=self.connection.execute("SELECT payload FROM meta WHERE key='manifest'").fetchone()
        self.metadata=json.loads(found[0]) if found else dict(metadata or {})
        if found is None:
            self.metadata.update(schema_version=3,writer_pid=os.getpid())
            try:
                import psutil
                self.metadata['writer_created']=psutil.Process().create_time()
            except ImportError: pass
            with self.connection:
                self.connection.execute("INSERT OR REPLACE INTO meta VALUES('manifest',?)",(_json(self.metadata),))

    def upsert(self,rows,removed=()):
        records=[(str(row['id']),float(row.get('start') or 0),_json(row)) for row in rows]
        with self.connection:
            self.connection.executemany('INSERT INTO rows VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET start=excluded.start,payload=excluded.payload',records)
            self.connection.executemany('DELETE FROM rows WHERE id=?',[(str(value),) for value in removed])

    def event(self,event):
        import hashlib
        fingerprint=event.get('event_id') or hashlib.sha256(_json(event).encode()).hexdigest()
        with self.connection:
            self.connection.execute('INSERT OR IGNORE INTO events(at,payload,fingerprint) VALUES(?,?,?)',(_now(),_json(event),fingerprint))

    def rows(self,*,limit=None,offset=0,reverse=False):
        direction='DESC' if reverse else 'ASC'
        sql=f'SELECT id,payload FROM rows ORDER BY start {direction},id {direction}'
        args=[]
        if limit is not None:
            sql+=' LIMIT ? OFFSET ?'
            args=[int(limit),int(offset)]
        valid=[]
        corrupted=[]
        for row_id,payload in self.connection.execute(sql,args):
            try:
                row=json.loads(payload)
                if not isinstance(row,dict) or str(row.get('id'))!=row_id: raise ValueError('invalid row')
                valid.append(row)
            except (ValueError,TypeError): corrupted.append(row_id)
        if corrupted:
            warning=self.metadata.setdefault('recovery_warnings',{})
            warning['corrupted_row_ids']=sorted(set(warning.get('corrupted_row_ids',[])+corrupted))
            warning['note']='仅恢复可确认数据，损坏条目仍保留在原数据库中'
        return valid

    def count(self):
        return self.connection.execute('SELECT COUNT(*) FROM rows').fetchone()[0]

    def checkpoint(self,extra=None):
        self.metadata.update(extra or {})
        self.metadata.update(updated_at=_now(),storage={'type':'sqlite','file':self.db_path.name,'schema':1},
                             row_count=self.count(),writer_pid=os.getpid())
        try:
            import psutil
            self.metadata['writer_created']=psutil.Process().create_time()
        except ImportError: self.metadata.pop('writer_created',None)
        preview=self.rows(limit=200,reverse=True)
        self.metadata['rows']=list(reversed(preview))
        self.metadata['rows_are_preview']=self.metadata['row_count']>len(preview)
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO meta VALUES('manifest',?)",(_json(self.metadata),))
        temporary=self.path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as stream:
            stream.write(_json(self.metadata)+'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,self.path)
        return self.metadata['updated_at']

    def close(self):
        self.connection.close()


def load_meeting(path,*,include_rows=True):
    path=Path(path)
    recovered=False
    try:
        manifest=json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError,OSError):
        db=path.with_suffix('.sqlite3')
        if not db.is_file(): raise
        with sqlite3.connect(db) as connection:
            item=connection.execute("SELECT payload FROM meta WHERE key='manifest'").fetchone()
        if not item: raise ValueError('记录损坏，数据库中也没有有效检查点')
        manifest=json.loads(item[0])
        recovered=True
    if manifest.get('storage',{}).get('type')!='sqlite': return manifest
    db=_db_path(path,manifest)
    if not db.is_file(): raise FileNotFoundError('会议数据库缺失：'+str(db))
    # An unclean Windows exit may leave WAL shared memory needing SQLite's
    # recovery lock. mode=rw allows that lock without creating a missing DB.
    connection=sqlite3.connect('file:'+db.as_posix()+'?mode=rw',uri=True,timeout=2)
    try:
        stored=connection.execute("SELECT payload FROM meta WHERE key='manifest'").fetchone()
        if stored: manifest=json.loads(stored[0])
        manifest['row_count']=connection.execute('SELECT COUNT(*) FROM rows').fetchone()[0]
        if include_rows:
            valid=[]
            corrupted=[]
            for row_id,payload in connection.execute('SELECT id,payload FROM rows ORDER BY start,id'):
                try:
                    row=json.loads(payload)
                    if not isinstance(row,dict) or str(row.get('id'))!=row_id: raise ValueError('invalid row')
                    valid.append(row)
                except (ValueError,TypeError): corrupted.append(row_id)
            manifest['rows']=valid
            manifest['rows_are_preview']=False
            manifest['events']=[]
            bad_events=[]
            for event_id,payload in connection.execute('SELECT id,payload FROM events ORDER BY id'):
                try: manifest['events'].append(json.loads(payload))
                except (ValueError,TypeError): bad_events.append(event_id)
            if corrupted or bad_events:
                manifest['recovery_warnings']={'corrupted_row_ids':corrupted,'corrupted_event_ids':bad_events,
                                               'note':'仅恢复可确认数据，损坏条目仍保留在原数据库中'}
                manifest['events'].append({'type':'record_corruption','row_ids':corrupted,'event_ids':bad_events,
                                           'note':'这些条目无法解析，原始数据库未被修改'})
                recovered=True
    finally:
        connection.close()
    manifest['recovered']=recovered or manifest.get('status') in ('active','paused','interrupted')
    return manifest


def recoverable_meetings(folder):
    found=[]
    for path in Path(folder).glob('*.json'):
        try:
            document=load_meeting(path,include_rows=False)
            if document.get('status') not in ('active','paused','interrupted'): continue
            alive=False
            try:
                import psutil
                process=psutil.Process(document.get('writer_pid',-1))
                alive=abs(process.create_time()-document.get('writer_created',0))<.01
            except Exception:
                alive=False
            if not alive: found.append((path,document))
        except (ValueError,OSError,sqlite3.Error): continue
    return sorted(found,key=lambda item:str(item[0]),reverse=True)
