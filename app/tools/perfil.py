from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from qdrant_client import models

from app.perfil import col_perfis, _garantir_indice
from app.vectorstore import COLLECTION_PERFIL_PREFERENCIAS, gerar_embedding, qdrant, garantir_colecao


def _user_id_do_contexto(config: RunnableConfig) -> str | None:
    """Obtém o usuário do contexto da requisição; o modelo não fornece esse valor."""
    return (config.get("configurable") or {}).get("user_id")


@tool
def perfil_estruturado(config: RunnableConfig) -> dict:
    """Consulta os dados estruturados do perfil financeiro do usuário atual."""
    user_id = _user_id_do_contexto(config)
    if not user_id:
        return {"status": "error", "message": "Usuário não identificado no contexto da requisição."}

    _garantir_indice()
    perfil = col_perfis.find_one(
        {"user_id": user_id},
        {"_id": 0, "user_id": 1, "renda_mensal": 1, "objetivo": 1, "tolerancia_risco": 1},
    )

    if not perfil:
        return {
            "status": "not_found",
            "message": "Nenhum perfil cadastrado para este usuário. Oriente o usuário a usar a tela Perfil.",
        }

    return {"status": "ok", "perfil": perfil}


@tool
def buscar_preferencias_perfil(pergunta: str, config: RunnableConfig) -> dict:
    """Busca semanticamente no perfil as preferências relevantes para a pergunta atual."""
    user_id = _user_id_do_contexto(config)
    if not user_id:
        return {"status": "error", "message": "Usuário não identificado no contexto da requisição."}

    _garantir_indice()
    perfil = col_perfis.find_one({"user_id": user_id}, {"_id": 1, "preferencias_versao": 1})
    if not perfil:
        return {
            "status": "not_found",
            "message": "Nenhum perfil cadastrado para este usuário. Oriente o usuário a usar a tela Perfil.",
        }

    garantir_colecao(COLLECTION_PERFIL_PREFERENCIAS, indexar_usuario=True)
    vetor = gerar_embedding(pergunta)
    filtros = [models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
    if perfil.get("preferencias_versao"):
        filtros.append(models.FieldCondition(
            key="versao", match=models.MatchValue(value=perfil["preferencias_versao"])
        ))
    resultados = qdrant.query_points(
        collection_name=COLLECTION_PERFIL_PREFERENCIAS,
        query=vetor,
        query_filter=models.Filter(must=filtros),
        limit=5,
    )

    preferencias = [
        ponto.payload["preferencia"]
        for ponto in resultados.points
        if ponto.payload and ponto.payload.get("preferencia")
    ]

    return {
        "status": "ok",
        "preferencias": preferencias,
    }


TOOLS_PERFIL = [perfil_estruturado, buscar_preferencias_perfil]