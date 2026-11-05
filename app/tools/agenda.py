"""Agenda local no PostgreSQL; escritas confirmadas somente após o juiz."""
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.escrita_adiada import atual, conexao_escrita, marcar_falha, registrar
from app.tools.conexao import get_conn

FUSO = ZoneInfo("America/Sao_Paulo")


def _usuario() -> str:
    turno = atual()
    if turno is None or not turno.user_id:
        raise RuntimeError("Agenda indisponível fora de um turno autenticado")
    return turno.user_id


def _data(valor: str) -> datetime:
    data = datetime.fromisoformat(valor)
    if data.tzinfo is None or data.utcoffset() is None:
        raise ValueError("Informe data e horário ISO 8601 com fuso (ex.: 2026-11-05T14:00:00-03:00).")
    return data.astimezone(FUSO)


def _periodo(inicio: str, fim: str) -> tuple[datetime, datetime]:
    de, ate = _data(inicio), _data(fim)
    if ate <= de:
        raise ValueError("O fim precisa ser posterior ao início.")
    return de, ate


def _conflito(cur, usuario: str, inicio: datetime, fim: datetime, excluir_id=None):
    cur.execute(
        """SELECT id, title, start_time, end_time FROM events
           WHERE user_id = %s AND start_time < %s AND COALESCE(end_time, start_time + INTERVAL '1 minute') > %s
             AND (%s::bigint IS NULL OR id <> %s::bigint)
           ORDER BY start_time LIMIT 1""",
        (usuario, fim, inicio, excluir_id, excluir_id),
    )
    return cur.fetchone()


def _erro(exc: Exception) -> dict:
    # Não exponha erros SQL ou detalhes de conexão ao usuário.
    if isinstance(exc, ValueError):
        return {"status": "error", "message": str(exc)}
    return {"status": "error", "message": "Não foi possível executar a operação na agenda."}


def _travar_usuario(cur, usuario: str):
    """Serializa gravações do mesmo usuário para evitar conflito entre turnos."""
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (usuario,))


class AddEventArgs(BaseModel):
    title: str = Field(..., min_length=1, description="Título do compromisso")
    start_at: str = Field(..., description="Início ISO 8601 com fuso")
    end_at: str = Field(..., description="Fim ISO 8601 com fuso")
    description: Optional[str] = Field(default=None, description="Descrição opcional")


class QueryEventsArgs(BaseModel):
    start_at: str = Field(..., description="Início do intervalo ISO 8601 com fuso")
    end_at: str = Field(..., description="Fim do intervalo ISO 8601 com fuso")


class UpdateEventArgs(BaseModel):
    id: int = Field(..., gt=0, description="ID do compromisso obtido na consulta")
    title: Optional[str] = Field(default=None, min_length=1)
    start_at: Optional[str] = Field(default=None, description="Novo início ISO 8601 com fuso")
    end_at: Optional[str] = Field(default=None, description="Novo fim ISO 8601 com fuso")
    description: Optional[str] = Field(default=None, description="Nova descrição")
    confirmado: bool = Field(default=False, description="O usuário confirmou expressamente a alteração")


class CancelEventArgs(BaseModel):
    id: int = Field(..., gt=0, description="ID obtido após consultar a agenda")
    confirmado: bool = Field(default=False, description="O usuário confirmou expressamente o cancelamento")


@tool("add_event", args_schema=AddEventArgs)
def add_event(title: str, start_at: str, end_at: str, description: Optional[str] = None) -> dict:
    """Prepara um compromisso, recusando sobreposição de horários."""
    try:
        inicio, fim = _periodo(start_at, end_at)
        usuario = _usuario()
        if not title.strip():
            raise ValueError("O título não pode estar vazio.")
        conn = conexao_escrita()
        with conn.cursor() as cur:
            _travar_usuario(cur, usuario)
            conflito = _conflito(cur, usuario, inicio, fim)
            if conflito:
                raise ValueError(f"Conflito com o compromisso {conflito[0]} ({conflito[1]}).")
            cur.execute(
                """INSERT INTO events (user_id, title, start_time, end_time, notes, source_text)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (usuario, title.strip(), inicio, fim, description, title.strip()),
            )
            identificador = cur.fetchone()[0]
        registrar("add_event", {"id": identificador, "title": title.strip(), "start_at": start_at, "end_at": end_at})
        return {"status": "ok", "id": identificador, "title": title.strip(), "start_at": inicio.isoformat(), "end_at": fim.isoformat(), "pending": True}
    except Exception as exc:
        marcar_falha()
        return _erro(exc)


@tool("query_events", args_schema=QueryEventsArgs)
def query_events(start_at: str, end_at: str) -> dict:
    """Lista apenas compromissos do usuário atual no período pedido."""
    try:
        inicio, fim = _periodo(start_at, end_at)
        usuario = _usuario()
    except Exception as exc:
        return _erro(exc)
    
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, start_time, end_time, notes FROM events
                   WHERE user_id = %s AND start_time < %s AND COALESCE(end_time, start_time + INTERVAL '1 minute') > %s
                   ORDER BY start_time, id""",
                (usuario, fim, inicio),
            )
            linhas = cur.fetchall()
        return {"status": "ok", "events": [
            {"id": r[0], "title": r[1], "start_at": r[2].isoformat(),
             "end_at": r[3].isoformat() if r[3] else None, "description": r[4]} for r in linhas
        ]}
    except Exception as exc:
        return _erro(exc)
    finally:
        if conn is not None:
            conn.close()


@tool("update_event", args_schema=UpdateEventArgs)
def update_event(id: int, title: Optional[str] = None, start_at: Optional[str] = None,
                 end_at: Optional[str] = None, description: Optional[str] = None,
                 confirmado: bool = False) -> dict:
    """Altera evento existente somente após confirmação do usuário; aguarda o juiz."""
    if not confirmado:
        return {"status": "confirmation_required", "message": "Confirme a alteração antes de continuar."}
    if all(v is None for v in (title, start_at, end_at, description)):
        return {"status": "error", "message": "Informe o campo que deseja alterar."}
    try:
        usuario = _usuario()
        conn = conexao_escrita()
        with conn.cursor() as cur:
            _travar_usuario(cur, usuario)
            cur.execute("SELECT title, start_time, end_time, notes FROM events WHERE id = %s AND user_id = %s FOR UPDATE", (id, usuario))
            existente = cur.fetchone()
            if not existente:
                raise ValueError("Compromisso não encontrado.")
            titulo = title.strip() if title is not None else existente[0]
            if not titulo:
                raise ValueError("O título não pode estar vazio.")
            inicio = _data(start_at) if start_at is not None else existente[1]
            fim = _data(end_at) if end_at is not None else existente[2]
            if fim is None and start_at is not None:
                raise ValueError("Informe end_at ao alterar o início de um compromisso sem horário de término.")
            if fim is not None and fim <= inicio:
                raise ValueError("O fim precisa ser posterior ao início.")
            # Eventos antigos podem não ter fim: não alteramos esse dado automaticamente.
            conflito = _conflito(cur, usuario, inicio, fim or inicio + timedelta(minutes=1), id)
            if conflito:
                raise ValueError(f"Conflito com o compromisso {conflito[0]} ({conflito[1]}).")
            cur.execute(
                """UPDATE events SET title=%s, start_time=%s, end_time=%s, notes=%s
                   WHERE id=%s AND user_id=%s""",
                (titulo, inicio, fim, description if description is not None else existente[3], id, usuario),
            )
        registrar("update_event", {"id": id, "title": titulo, "start_at": inicio.isoformat(), "end_at": fim.isoformat() if fim else None})
        return {"status": "ok", "id": id, "title": titulo, "pending": True}
    except Exception as exc:
        marcar_falha()
        return _erro(exc)


@tool("cancel_event", args_schema=CancelEventArgs)
def cancel_event(id: int, confirmado: bool = False) -> dict:
    """Cancela um compromisso após confirmação expressa; aguarda o juiz."""
    if not confirmado:
        return {"status": "confirmation_required", "message": "Confirme o cancelamento antes de continuar."}
    try:
        usuario = _usuario()
        conn = conexao_escrita()
        with conn.cursor() as cur:
            _travar_usuario(cur, usuario)
            cur.execute("DELETE FROM events WHERE id=%s AND user_id=%s RETURNING title", (id, usuario))
            linha = cur.fetchone()
            if not linha:
                raise ValueError("Compromisso não encontrado.")
        registrar("cancel_event", {"id": id, "title": linha[0]})
        return {"status": "ok", "id": id, "title": linha[0], "pending": True}
    except Exception as exc:
        marcar_falha()
        return _erro(exc)


TOOLS_AGENDA = [add_event, query_events, update_event, cancel_event]
