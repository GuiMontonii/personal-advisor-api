"""Testes locais de integração simulada agenda + commit adiado (sem Postgres)."""
import importlib
import sys
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


langchain = types.ModuleType('langchain')
langchain.__path__ = []
langchain_tools = types.ModuleType('langchain.tools')
class ToolWrapper:
    def __init__(self, fn):
        self.func = fn
    def invoke(self, data):
        return self.func(**data)
def tool(name, args_schema):
    return lambda fn: ToolWrapper(fn)
langchain_tools.tool = tool
sys.modules['langchain'] = langchain
sys.modules['langchain.tools'] = langchain_tools

conexao = types.ModuleType('app.tools.conexao')
sys.modules['app.tools.conexao'] = conexao

class DB:
    def __init__(self):
        self.rows = {}
        self.next_id = 1
        self.commits = 0
        self.rollbacks = 0
        self.close_count = 0
    def connect(self):
        return Connection(self)

class Connection:
    def __init__(self, db):
        self.db = db
        self.records = {k: list(v) for k,v in db.rows.items()}
        self.next_id = db.next_id
        self.closed = False
    def cursor(self):
        return Cursor(self)
    def commit(self):
        self.db.rows = {k: list(v) for k,v in self.records.items()}
        self.db.next_id = self.next_id
        self.db.commits += 1
    def rollback(self):
        self.db.rollbacks += 1
    def close(self):
        assert not self.closed
        self.closed = True
        self.db.close_count += 1

class Cursor:
    def __init__(self, conn):
        self.c = conn
        self.result = []
    def __enter__(self):return self
    def __exit__(self, *args):return False
    def execute(self, sql, args=()):
        normalized = ' '.join(sql.split()).upper()
        rows = self.c.records
        self.result = []
        if 'PG_ADVISORY_XACT_LOCK' in normalized:return
        if normalized.startswith('SELECT ID, TITLE, START_TIME, END_TIME FROM EVENTS'):
            user, end, start, *excl = args
            exclude = excl[0] if excl else None
            self.result = [(id, r[1], r[2], r[3]) for id,r in rows.items() if r[0] == user and r[2]<end and (r[3] or (r[2] + __import__('datetime').timedelta(minutes=1)))>start and id != exclude][:1]
        elif normalized.startswith('INSERT INTO EVENTS'):
            id = self.c.next_id
            self.c.next_id += 1
            rows[id] = list(args)
            self.result = [(id,)]
        elif normalized.startswith('SELECT ID, TITLE, START_TIME, END_TIME, NOTES FROM EVENTS'):
            user,end,start = args
            self.result = [(id,r[1],r[2],r[3],r[4]) for id,r in rows.items() if r[0] == user and r[2]<end and (r[3] or (r[2] + __import__('datetime').timedelta(minutes=1)))>start]
        elif normalized.startswith('SELECT TITLE, START_TIME, END_TIME, NOTES FROM EVENTS'):
            id,user = args
            if id in rows and rows[id][0] == user:self.result = [tuple(rows[id][1:5])]
        elif normalized.startswith('UPDATE EVENTS'):
            title,start,end,desc,id,user = args
            assert rows[id][0] == user
            rows[id] = [user,title,start,end,desc,rows[id][5]]
        elif normalized.startswith('DELETE FROM EVENTS'):
            id,user = args
            if id in rows and rows[id][0] == user:
                self.result = [(rows[id][1],)]
                del rows[id]
        else:
            raise AssertionError('SQL não reconhecido: ' + normalized[:100])
    def fetchone(self):return self.result[0] if self.result else None
    def fetchall(self):return self.result

db = DB()
conexao.get_conn = db.connect
m = importlib.import_module('app.escrita_adiada')
a = importlib.import_module('app.tools.agenda')
START = '2026-11-06T14:00:00-03:00'
END = '2026-11-06T15:00:00-03:00'


def turn(user, approved, action):
    token = m.iniciar(user_id=user)
    try:
        result = action()
        m.finalizar(approved)
        return result
    finally:
        m.limpar(token)


r = turn('ana', False, lambda: a.add_event.func('Reunião', START, END))
assert r['status'] == 'ok' and not db.rows

r = turn('ana', True, lambda: a.add_event.func('Reunião', START, END))
assert r['status'] == 'ok' and len(db.rows) == 1
id = r['id']

assert len(turn('ana', True, lambda: a.query_events.func(START,END))['events']) == 1
assert len(turn('bia', True, lambda: a.query_events.func(START,END))['events']) == 0

assert turn('ana', True, lambda: a.add_event.func('Conflito', START, END))['status'] == 'error'
assert len(db.rows)==1

assert turn('ana', True, lambda: a.add_event.func('Inválido','2026-11-06T14:00',END))['status']=='error'

assert turn('ana', True, lambda: a.update_event.func(id,title='Novo'))['status']=='confirmation_required'
assert db.rows[id][1]=='Reunião'

assert turn('ana', False, lambda: a.update_event.func(id,title='Novo',confirmado=True))['status']=='ok'
assert db.rows[id][1]=='Reunião'

assert turn('ana', True, lambda: a.update_event.func(id,title='Novo',confirmado=True))['status']=='ok'
assert db.rows[id][1]=='Novo'

assert turn('bia', True, lambda: a.update_event.func(id,title='Ataque',confirmado=True))['status']=='error'
assert turn('bia', True, lambda: a.cancel_event.func(id,confirmado=True))['status']=='error'
assert id in db.rows

assert turn('ana', True, lambda: a.cancel_event.func(id))['status']=='confirmation_required'
assert id in db.rows

assert turn('ana', False, lambda: a.cancel_event.func(id,confirmado=True))['status']=='ok'
assert id in db.rows

assert turn('ana', True, lambda: a.cancel_event.func(id,confirmado=True))['status']=='ok'
assert id not in db.rows

before = db.commits
def partial_failure():
    first = a.add_event.func('A',START,END)
    second = a.add_event.func('B',START,END)
    assert first['status']=='ok' and second['status']=='error'
    return second
turn('ana', True, partial_failure)
assert not db.rows and db.commits==before
print('PASSOU: 14 cenários da agenda simulada, isolamento por usuário e rollback do turno')


token = m.iniciar(user_id='ana')
try:
    c = m.conexao_escrita()
    with c.cursor() as cur:
        cur.execute('INSERT INTO events (user_id, title, start_time, end_time, notes, source_text) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
                    ('ana','Legado',datetime.fromisoformat(START), None, 'sem fim','Legado'))
    m.finalizar(True)
finally:
    m.limpar(token)
legacy = next(k for k,r in db.rows.items() if r[1]=='Legado')
assert turn('ana', True, lambda: a.query_events.func(START,END))['events'][0]['end_at'] is None
assert turn('ana', True, lambda: a.update_event.func(legacy,title='Legado editado',confirmado=True))['status']=='ok'
assert db.rows[legacy][3] is None
assert turn('ana',True,lambda: a.update_event.func(legacy,start_at=START,confirmado=True))['status']=='error'
assert turn('ana', True, lambda: a.cancel_event.func(legacy,confirmado=True))['status']=='ok'
print('PASSOU: 4 cenários de compatibilidade com eventos legados sem término')
