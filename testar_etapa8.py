"""Testes isolados do mecanismo de confirmação: python testar_etapa8.py.
Sem acesso ao banco real: fakes verificam commit/rollback por turno.
"""
import importlib.util
import pathlib
import sys
import types

BASE = pathlib.Path(__file__).resolve().parent
sys.modules['app'] = types.ModuleType('app')
sys.modules['app'].__path__ = [str(BASE/'app')]
sys.modules['app.tools'] = types.ModuleType('app.tools')
sys.modules['app.tools'].__path__ = [str(BASE/'app/tools')]
conexao = types.ModuleType('app.tools.conexao')
sys.modules['app.tools.conexao'] = conexao

class FakeConn:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1
    def close(self):
        self.closed = True

instances = []
def get_conn():
    conn = FakeConn()
    instances.append(conn)
    return conn
conexao.get_conn = get_conn
spec = importlib.util.spec_from_file_location('app.escrita_adiada', BASE/'app/escrita_adiada.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

for nome in ('add_transaction', 'update_transaction', 'add_event'):
    token = module.iniciar()
    assert module.conexao_escrita() is module.conexao_escrita(), 'Conexão não compartilhada'
    conn = instances[-1]
    module.registrar(nome, {'marcador': 'ETAPA8-TESTE-' + nome})
    assert conn.commits == 0 and conn.rollbacks == 0, 'Confirmou antes do juiz'
    module.finalizar(False)
    assert conn.rollbacks == 1 and conn.commits == 0 and conn.closed, 'Recusa persistiu'
    module.limpar(token)
    print('[juiz] RECUSADO', nome, '- rollback verificado')

for nome in ('add_transaction', 'update_transaction', 'add_event'):
    token = module.iniciar()
    conn = module.conexao_escrita()
    module.registrar(nome, {'marcador': 'ETAPA8-APROVADO-' + nome})
    module.finalizar(True)
    assert conn.commits == 1 and conn.rollbacks == 0 and conn.closed, 'Aprovado não confirmou uma vez'
    module.limpar(token)
    print('[juiz] APROVADO', nome, '- commit único verificado')

token = module.iniciar()
conn = module.conexao_escrita()
module.marcar_falha()
module.finalizar(True)
assert conn.commits == 0 and conn.rollbacks == 1
module.limpar(token)
print('[juiz] FALHA INTERNA - rollback verificado')

token = module.iniciar()
conn = module.conexao_escrita()
module.limpar(token)
assert conn.commits == 0 and conn.rollbacks == 1
print('[juiz] EXCECAO / QUEDA ANTES DA FINALIZACAO - rollback verificado')
print('8 cenários isolados aprovados')
