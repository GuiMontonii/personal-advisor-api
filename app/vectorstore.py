"""
Cliente Qdrant e função de embedding — centralizados aqui.

Dois consumidores:
  - memory.py   → salva/busca resumos na collection "memoria_resumos"
  - tools/faq.py → busca chunks do PDF na collection "faq_chunks"

O modelo de embedding é o mesmo para ambos (gemini-embedding-2-preview, 768d),
então instanciamos uma vez só.
"""

from qdrant_client import QdrantClient, models
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from app.config import QDRANT_URL, QDRANT_API_KEY, GEMINI_API_KEY

qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

COLLECTION_MEMORIA = "memoria_resumos"
COLLECTION_FAQ     = "faq_chunks"
COLLECTION_PERFIL_PREFERENCIAS = "perfil_preferencias"
EMBEDDING_DIM      = 768

_embeddings = GoogleGenerativeAIEmbeddings(
    model="gemini-embedding-2-preview",
    google_api_key=GEMINI_API_KEY,
)

def gerar_embedding(texto: str) -> list[float]:
    """Gera um vetor de 768 dimensões para o texto informado."""
    return _embeddings.embed_query(texto, output_dimensionality=EMBEDDING_DIM)


def gerar_embeddings_batch(textos: list[str]) -> list[list[float]]:
    """Gera embeddings para uma lista de textos de uma vez (mais eficiente)."""
    return _embeddings.embed_documents(textos, output_dimensionality=EMBEDDING_DIM)

def garantir_colecao(nome: str, indexar_usuario: bool = False) -> None:
    """Cria a collection apenas no momento de uso; não acessa a rede no import."""
    if not qdrant.collection_exists(nome):
        try:
            qdrant.create_collection(
                collection_name=nome,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIM,
                    distance=models.Distance.COSINE,
                ),
            )
        except Exception:
            # Outra requisição/processo pode ter criado a collection em paralelo.
            if not qdrant.collection_exists(nome):
                raise
    if indexar_usuario:
        schema = qdrant.get_collection(nome).payload_schema or {}
        for chave in (["user_id", "versao"] if nome == COLLECTION_PERFIL_PREFERENCIAS else ["user_id"]):
            if chave not in schema:
                qdrant.create_payload_index(
                    collection_name=nome,
                    field_name=chave,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
