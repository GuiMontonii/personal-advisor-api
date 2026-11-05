"""
Script de ingestão do FAQ no Qdrant.

Lê o PDF, faz split em chunks, gera embeddings e insere na collection
"faq_chunks" do Qdrant. Deve ser executado UMA VEZ (ou sempre que o PDF mudar):

    python -m app.ingest_faq

Ele limpa a collection antes de reinserir, então é seguro rodar várias vezes.
"""

import uuid
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models

from app.config import FAQ_PDF_PATH
from app.vectorstore import qdrant, gerar_embeddings_batch, COLLECTION_FAQ, garantir_colecao

CHUNK_SIZE    = 700
CHUNK_OVERLAP = 150
BATCH_SIZE    = 50


def ingerir_faq() -> int:
    """Indexa o PDF do FAQ no Qdrant. Retorna o número de chunks inseridos."""
    print(f"[ingest] Carregando PDF: {FAQ_PDF_PATH}")
    loader = PyPDFLoader(str(FAQ_PDF_PATH))
    docs = loader.load()
    print(f"[ingest] {len(docs)} página(s) carregada(s)")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)
    print(f"[ingest] {len(chunks)} chunk(s) gerado(s)")

    
    garantir_colecao(COLLECTION_FAQ)
    # Gerar e inserir novas versões antes de apagar as antigas, evitando
    # deixar o FAQ vazio se o provedor de embeddings estiver indisponível.
    textos = [chunk.page_content for chunk in chunks]
    novos_pontos = []
    for i in range(0, len(textos), BATCH_SIZE):
        lote_textos = textos[i : i + BATCH_SIZE]
        lote_chunks = chunks[i : i + BATCH_SIZE]
        print(f"[ingest] Gerando embeddings para chunk {i+1}–{i+len(lote_textos)}...")
        vetores = gerar_embeddings_batch(lote_textos)
        novos_pontos.extend(
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector=vetor,
                payload={
                    "page_content": chunk.page_content,
                    "page_number": chunk.metadata.get("page", 0),
                    "source": str(chunk.metadata.get("source", "")),
                },
            )
            for vetor, chunk in zip(vetores, lote_chunks)
        )

    antigos_ids = []
    cursor = None
    while True:
        antigos, cursor = qdrant.scroll(
            collection_name=COLLECTION_FAQ,
            limit=100,
            offset=cursor,
            with_payload=False,
            with_vectors=False,
        )
        antigos_ids.extend(point.id for point in antigos)
        if cursor is None:
            break

    novos_ids = []
    try:
        for i in range(0, len(novos_pontos), BATCH_SIZE):
            lote = novos_pontos[i:i + BATCH_SIZE]
            qdrant.upsert(collection_name=COLLECTION_FAQ, points=lote, wait=True)
            novos_ids.extend(point.id for point in lote)
    except Exception:
        if novos_ids:
            qdrant.delete(collection_name=COLLECTION_FAQ,
                          points_selector=models.PointIdsList(points=novos_ids), wait=True)
        raise
    if antigos_ids:
        for i in range(0, len(antigos_ids), 100):
            qdrant.delete(collection_name=COLLECTION_FAQ,
                          points_selector=models.PointIdsList(points=antigos_ids[i:i + 100]), wait=True)

    print(f"[ingest] Concluído! {len(chunks)} chunk(s) indexado(s) no Qdrant.")
    return len(chunks)


if __name__ == "__main__":
    ingerir_faq()