"""
As rotas do ciclo de vida da sessão.

O navegador decide quando uma conversa acaba. O botão "nova sessão" chama
POST /sessions/{id}/encerrar antes de sortear um novo UUID.

Sem este encerramento explícito, nenhuma sessão ganha resumo, e como
buscar_historico() só enxerga sessões COM resumo, a memória de longo prazo
(TOOLS_MEMORIA) fica permanentemente vazia.
"""

from fastapi import APIRouter

from app.memory import encerrar_sessao, iniciar_sessao
from app.schemas import SessionResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/{session_id}/iniciar", response_model=SessionResponse)
def iniciar(session_id: str) -> SessionResponse:
    """Abre uma sessão explicitamente (opcional — salvar_mensagem() já abre sozinha)."""
    iniciar_sessao(session_id)
    return SessionResponse(session_id=session_id, resumo=None)


@router.post("/{session_id}/encerrar", response_model=SessionResponse)
def encerrar(session_id: str) -> SessionResponse:
    """Encerra a sessão: gera o resumo via LLM e grava no documento."""
    resumo = encerrar_sessao(session_id)
    return SessionResponse(session_id=session_id, resumo=resumo or None)