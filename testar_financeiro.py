"""Testes isolados do módulo financeiro com Postgres simulado; sem alterar dados reais."""
import importlib
import sys
import types
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


langchain = types.ModuleType('langchain')
langchain.__path__ = []
tools = types.ModuleType('langchain.tools')

class Tool:
    def __init__(self, func):
        self.func = func
    def invoke(self, arguments):
        return self.func(**arguments)

def tool(name, args_schema):
    return lambda f: Tool(f)

tools.tool = tool
sys.modules['langchain'] = langchain
sys.modules['langchain.tools'] = tools
sys.modules['psycopg2'] = types.ModuleType('psycopg2')


TYPES = {9: 'INCOME', 23: 'EXPENSES', 48: 'TRANSFER'}
CATEGORIES = {77: 'comida', 129: 'outros'}
NOW = datetime.fromisoformat('2026-11-04T13:00:00-03:00')

class DB:
    def __init__(self):
        self.records = []
        self.next_id = 1
        self.commits = 0
        self.rollbacks = 0
    def connect(self):
        return Conn(self)

class Conn:
    def __init__(self, db):
        self.db = db
        self.records = deepcopy(db.records)
        self.next_id = db.next_id
        self.closed = False
    def cursor(self):
        return Cursor(self)
    def commit(self):
        self.db.records = deepcopy(self.records)
        self.db.next_id = self.next_id
        self.db.commits += 1
    def rollback(self):
        self.records = deepcopy(self.db.records)
        self.db.rollbacks += 1
    def close(self):
        self.closed = True

class Cursor:
    def __init__(self, conn):
        self.c = conn
        self.result = []
        self.rowcount = 0
    def close(self):
        pass
    def fetchone(self):
        return self.result[0] if self.result else None
    def fetchall(self):
        return self.result
    def execute(self, sql, params=()):
        norm = ' '.join(sql.upper().split())
        p = tuple(params)
        self.result = []
        self.rowcount = 0
        if norm.startswith('SELECT ID FROM TRANSACTION_TYPES WHERE UPPER(TYPE)'):
            self.result = [(k,) for k,v in TYPES.items() if v.upper() == p[0]][:1]
        elif norm.startswith('SELECT ID FROM TRANSACTION_TYPES WHERE ID'):
            self.result = [(p[0],)] if p[0] in TYPES else []
        elif norm.startswith('SELECT ID FROM CATEGORIES WHERE LOWER(NAME)'):
            self.result = [(k,) for k,v in CATEGORIES.items() if v.lower() == p[0]][:1]
        elif norm.startswith('SELECT ID FROM CATEGORIES WHERE ID'):
            self.result = [(p[0],)] if p[0] in CATEGORIES else []
        elif norm.startswith('INSERT INTO TRANSACTIONS'):
            amount, kind, cat, desc, method, *other = p
            occurred = NOW
            source = other[-1]
            if 'INTERVAL' in norm:
                from datetime import timedelta
                occurred -= timedelta(days=1)
            elif '%S::TIMESTAMPTZ' in norm:
                occurred = datetime.fromisoformat(other[0])
            r = dict(id=self.c.next_id, amount=Decimal(str(amount)), type=kind,
                     category_id=cat, description=desc, payment_method=method,
                     occurred_at=occurred, source_text=source)
            self.c.records.append(r)
            self.c.next_id += 1
            self.result = [(r['id'], occurred)]
            self.rowcount = 1
        elif norm.startswith('SELECT COALESCE(SUM(CASE WHEN UPPER(TT.TYPE)'):
            records = self.c.records
            if '::DATE = %S' in norm:
                records = [r for r in records if str(r['occurred_at'].date()) == p[0]]
            val = sum((r['amount'] * (1 if TYPES[r['type']] == 'INCOME' else -1 if TYPES[r['type']] == 'EXPENSES' else 0)) for r in records)
            self.result = [(val,)]
        elif norm.startswith('SELECT COALESCE(SUM(T.AMOUNT)'):
            records = [r for r in self.c.records if TYPES[r['type']] == 'EXPENSES' and CATEGORIES[r['category_id']] == p[0] and str(r['occurred_at'].date()) == p[1]]
            self.result = [(sum((r['amount'] for r in records), Decimal('0')),)]
        elif norm.startswith('SELECT T.ID FROM TRANSACTIONS T'):
            text, _, date = p
            import fnmatch
            self.result = [(r['id'],) for r in sorted(self.c.records,key=lambda r:r['occurred_at'],reverse=True)
                           if fnmatch.fnmatch((r['source_text'] or '').lower(),text.strip('%').lower()) and str(r['occurred_at'].date()) == date][:1]
        elif norm.startswith('UPDATE TRANSACTIONS SET'):
            col_sql = norm.split(' SET ',1)[1].split(' WHERE ',1)[0]
            fields = [x.split('=')[0].strip().lower() for x in col_sql.split(',')]
            target = p[-1]
            for r in self.c.records:
                if r['id'] == target:
                    for f,v in zip(fields,p):
                        r[f] = Decimal(str(v)) if f == 'amount' else v
                    self.rowcount = 1
                    break
        elif norm.startswith('SELECT T.ID, T.OCCURRED_AT, T.AMOUNT'):
            for r in self.c.records:
                if r['id'] == p[0]:
                    self.result = [(r['id'],r['occurred_at'],r['amount'],TYPES[r['type']],CATEGORIES[r['category_id']],r['description'],r['payment_method'],r['source_text'])]
                    break
        elif norm.startswith('SELECT T.ID, T.AMOUNT, T.TYPE'):
            recs = sorted(self.c.records,key=lambda r:r['occurred_at'],reverse=True)
            self.result = [(r['id'],r['amount'],r['type'],r['category_id'],CATEGORIES[r['category_id']],r['description'],r['payment_method'],r['occurred_at']) for r in recs]
        else:
            raise AssertionError('SQL inesperado no simulador: '+norm[:150])

db = DB()
conexao = types.ModuleType('app.tools.conexao')
conexao.get_conn = db.connect
sys.modules['app.tools.conexao'] = conexao
mod = importlib.import_module('app.escrita_adiada')
financeiro = importlib.import_module('app.tools.financeiro')

def turn(approved, operation):
    token = mod.iniciar(user_id='usuario_teste')
    try:
        result = operation()
        mod.finalizar(approved)
        return result
    finally:
        mod.limpar(token)


r = turn(False, lambda: financeiro.add_transaction.func(30, 'mercado', category_name='comida'))
assert r['status'] == 'ok' and not db.records

r = turn(True, lambda: financeiro.add_transaction.func(30, 'mercado', category_name='comida'))
assert r['status'] == 'ok' and db.records[0]['type'] == 23 and db.records[0]['category_id'] == 77

r = turn(True, lambda: financeiro.add_transaction.func(100, 'salário', type_name='salário'))
assert r['status'] == 'ok' and db.records[1]['type'] == 9

assert financeiro.total_balance.func()['balance'] == 70

assert financeiro.daily_balance.func('2026-11-04')['daily_balance'] == 70

assert financeiro.daily_balance.func('2026-11-04', 'comida')['category_spent'] == 30

assert financeiro.query_transactions.func()['total'] == 2

assert turn(False, lambda: financeiro.update_transaction.func(id=1, amount=10))['status'] == 'ok'
assert db.records[0]['amount'] == 30

assert turn(True, lambda: financeiro.update_transaction.func(id=1, amount=10))['status'] == 'ok'
assert db.records[0]['amount'] == 10

assert turn(True, lambda: financeiro.update_transaction.func(id=1, amount=0, description='Removido pelo usuário'))['status'] == 'ok'
assert db.records[0]['amount'] == 0

assert financeiro.total_balance.func()['balance'] == 100

assert turn(True, lambda: financeiro.add_transaction.func(10, 'teste', category_name='inexistente'))['status']=='error'
assert len(db.records) == 2

assert turn(True, lambda: financeiro.add_transaction.func(10, 'teste', type_name='INVALIDO'))['status']=='error'

assert turn(True, lambda: financeiro.add_transaction.func(-1, 'teste'))['status']=='error'

assert turn(True, lambda: financeiro.add_transaction.func(1, 'teste', occurred_at='04/11/2026'))['status']=='error'

assert financeiro.daily_balance.func('31/02/2026')['status'] == 'error'

assert turn(True, lambda: financeiro.update_transaction.func(id=999, amount=1))['status'] == 'error'

assert turn(True, lambda: financeiro.update_transaction.func(id=1))['status'] == 'error'

before=db.commits
def partial_fail():
    a=financeiro.add_transaction.func(10,'parte boa')
    b=financeiro.add_transaction.func(10,'parte ruim',category_name='nada')
    assert a['status']=='ok' and b['status']=='error'
    return b
assert turn(True,partial_fail)['status']=='error'
assert db.commits == before and len(db.records) == 2
print('PASSOU: 19 cenários simulados de financeiro, tipos dinâmicos e rollback')
