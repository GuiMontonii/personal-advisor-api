import uuid
from datetime import datetime, timezone

from pymongo import MongoClient

from app.config import MONGODB_URI
from app.vectorstore import (
    COLLECTION_PERFIL_PREFERENCIAS,
    gerar_embeddings_batch,
    qdrant,
    garantir_colecao,
)
from qdrant_client import models

_mongo = MongoClient(MONGODB_URI)
db = _mongo["assessor"]
col_perfis = db["perfis"]

_indice_criado = False


def _garantir_indice() -> None:
    global _indice_criado
    if not _indice_criado:
        col_perfis.create_index("user_id", unique=True)
        _indice_criado = True


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _dividir_preferencias(texto: str) -> list[str]:
    """Divide o texto livre em frases, ignorando partes vazias."""
    partes = []
    atual = ""

    for trecho in texto.replace("\n", ";").split(";"):
        trecho = trecho.strip()
        if trecho:
            partes.append(trecho)

    if not partes and texto.strip():
        partes.append(texto.strip())

    return partes


def salvar_perfil(
    user_id: str,
    renda_mensal: float,
    objetivo: str,
    tolerancia_risco: str,
    preferencias: str,
) -> dict:
    """Grava o perfil estruturado no MongoDB e substitui as preferências no Qdrant."""
    agora = _agora()

    versao = uuid.uuid4().hex
    documento = {
        "user_id": user_id,
        "preferencias_versao": versao,
        "renda_mensal": renda_mensal,
        "objetivo": objetivo,
        "tolerancia_risco": tolerancia_risco,
        "atualizado_em": agora,
    }

    _garantir_indice()
    # Não apagar as preferências antigas até gerar com sucesso todas as novas.
    frases = _dividir_preferencias(preferencias)
    vetores = gerar_embeddings_batch(frases) if frases else []
    garantir_colecao(COLLECTION_PERFIL_PREFERENCIAS, indexar_usuario=True)

    filtro = models.Filter(must=[
        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
    ])
    antigos_ids = []
    cursor = None
    while True:
        antigos, cursor = qdrant.scroll(
            collection_name=COLLECTION_PERFIL_PREFERENCIAS,
            scroll_filter=filtro, offset=cursor, limit=100,
            with_payload=False, with_vectors=False,
        )
        antigos_ids.extend(p.id for p in antigos)
        if cursor is None:
            break

    pontos = [
        models.PointStruct(id=str(uuid.uuid4()), vector=vetor,
                           payload={"user_id": user_id, "preferencia": frase, "versao": versao})
        for frase, vetor in zip(frases, vetores)
    ]
    if pontos:
        qdrant.upsert(collection_name=COLLECTION_PERFIL_PREFERENCIAS,
                      points=pontos, wait=True)

    try:
        col_perfis.update_one(
            {"user_id": user_id},
            {"$set": documento, "$setOnInsert": {"criado_em": agora}},
            upsert=True,
        )
    except Exception:
        if pontos:
            qdrant.delete(
                collection_name=COLLECTION_PERFIL_PREFERENCIAS,
                points_selector=models.PointIdsList(points=[p.id for p in pontos]),
                wait=True,
            )
        raise

    if antigos_ids:
        try:
            for i in range(0, len(antigos_ids), 100):
                qdrant.delete(
                    collection_name=COLLECTION_PERFIL_PREFERENCIAS,
                    points_selector=models.PointIdsList(points=antigos_ids[i:i + 100]),
                    wait=True,
                )
        except Exception:
            # A versão no Mongo impede a leitura dos pontos antigos,
            
            import logging
            logging.getLogger(__name__).exception("Falha ao limpar preferências obsoletas")

    return {
        "user_id": user_id,
        "renda_mensal": renda_mensal,
        "objetivo": objetivo,
        "tolerancia_risco": tolerancia_risco,
        "preferencias": preferencias,
    }