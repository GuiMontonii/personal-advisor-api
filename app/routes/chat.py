import logging
from fastapi import APIRouter, HTTPException
from app.schemas import ChatRequest, ChatResponse 
from app.graph import executar_fluxo_assessor

router = APIRouter(tags=["chat"])

@router.post("/chat", response_model=ChatResponse)
def conversar(requisicao: ChatRequest) -> ChatResponse:
    """Uma mensagem do usuário, uma resposta do assessor."""
    try:
        resposta, agentes = executar_fluxo_assessor(
            requisicao.pergunta, requisicao.session_id, requisicao.user_id,
            retornar_agentes=True,
        )
        return ChatResponse(resposta=resposta, agentes_chamados=agentes)
    except Exception:
        logging.getLogger(__name__).exception("Falha no fluxo do assessor")
        raise HTTPException(status_code=503, detail="Não foi possível processar a mensagem agora. Tente novamente.")