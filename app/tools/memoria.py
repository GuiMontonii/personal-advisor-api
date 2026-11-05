"""
Tool de memória de longo prazo — consulta conversas ANTERIORES do usuário.

Migração de tool_mongodb.py (raiz) para dentro de app/tools/.
"""

from datetime import datetime

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from app.memory import recuperar_historico

def _data_br(valor) -> str:
    """dd/mm/aaaa para datetime ou texto ISO. Antes, o caminho do Qdrant entregava texto e o
    f"{valor:%d/%m/%Y}" levantava ValueError: a busca semântica de histórico quebrava."""
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor)
        except ValueError:
            return valor
    try:
        return f"{valor:%d/%m/%Y}"
    except (TypeError, ValueError):
        return str(valor)


@tool
def buscar_historico(busca: str, config: RunnableConfig) -> str:
    """Consulta conversas ANTERIORES do usuário (sessões já encerradas).

    Use SOMENTE quando a resposta depende de algo dito numa conversa passada
    — preferências, decisões ou planos que o usuário mencionou antes.
    NÃO use para dados que estão no banco (gastos, saldos, eventos): para isso
    já existem as tools de consulta específicas como query_transactions,
    total_balance, daily_balance.

    Args:
        busca: assunto a procurar nos resumos das conversas anteriores.
    """
    configuravel = (config or {}).get("configurable", {})
    user_id      = configuravel.get("user_id") or configuravel.get("thread_id")

    if not user_id:
        return "Não foi possível identificar o usuário para buscar o histórico."

    historico = recuperar_historico(user_id, busca=busca, limite=3)

    if not historico:
        return "Nenhuma conversa anterior relevante encontrada."

    return "\n\n".join(
        f"[{_data_br(h['iniciada_em'])}] {h['resumo']}" for h in historico
    )


TOOLS_MEMORIA = [buscar_historico]