"""Uma transação PostgreSQL por turno: só o juiz permite o commit."""
from contextvars import ContextVar
from dataclasses import dataclass, field
from app.tools.conexao import get_conn

@dataclass
class EscritaPendente:
    conexao: object = None
    operacoes: list = field(default_factory=list)
    falhou: bool = False
    user_id: str = ""

_turno = ContextVar("escrita_pendente", default=None)

def iniciar(user_id: str = ""):
    return _turno.set(EscritaPendente(user_id=user_id))

def atual():
    return _turno.get()

def conexao_escrita():
    turno = atual()
    if turno is None:
        raise RuntimeError("Escrita proibida fora de um turno supervisionado pelo juiz")
    if turno.conexao is None:
        turno.conexao = get_conn()
    return turno.conexao

def registrar(nome, dados):
    turno = atual()
    if turno is None:
        raise RuntimeError("Turno não iniciado")
    turno.operacoes.append({"tool": nome, "resultado": dados})

def marcar_falha():
    turno = atual()
    if turno:
        turno.falhou = True

def finalizar(aprovado):
    turno = atual()
    if not turno or turno.conexao is None:
        return
    try:
        if aprovado and not turno.falhou:
            turno.conexao.commit()
        else:
            turno.conexao.rollback()
    except Exception:
        try:
            turno.conexao.rollback()
        finally:
            raise
    finally:
        turno.conexao.close()
        turno.conexao = None

def limpar(token):
    turno = atual()
    if turno and turno.conexao is not None:
        try:
            turno.conexao.rollback()
        finally:
            turno.conexao.close()
            turno.conexao = None
    _turno.reset(token)
