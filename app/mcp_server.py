"""
Servidor MCP do Assessor — Etapa 5.

Segundo ponto de entrada do projeto, irmão do main.py:
  main.py        → expõe o Assessor por HTTP (cliente: o navegador)
  mcp_server.py  → expõe as tools financeiras por MCP/stdio (cliente: Cursor, Cline, outro agente)

Nada aqui reescreve SQL. Cada tool MCP é uma "casca": declara o contrato
(tipos + descrições para o modelo) e despacha para a @tool LangChain que já
existe em app/tools/financeiro.py, via .invoke().

ATENÇÃO — em stdio, o stdout é o protocolo. Nunca use print() neste arquivo
(nem em nada que ele importe): log vai para sys.stderr.
"""

import sys
from pathlib import Path
from typing import Annotated, Any, Optional

# O cliente MCP (Cursor/Cline) inicia `python app/mcp_server.py` com um cwd

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.tools.financeiro import (
    add_transaction as _add_transaction,
    daily_balance as _daily_balance,
    query_transactions as _query_transactions,
    total_balance as _total_balance,
    update_transaction as _update_transaction,
)

mcp = MCPServer(
    name="assessor-financeiro",
    version="1.0.0",
    instructions=(
        "Ferramentas financeiras do Assessor.AI: consultar lançamentos, ver saldo "
        "(total ou de um dia), registrar e corrigir transações no Postgres. "
        "Valores são sempre positivos; o sinal vem do tipo (INCOME = entrada, "
        "EXPENSES = saída, TRANSFER = transferência). Datas no formato YYYY-MM-DD, "
        "fuso America/Sao_Paulo. Categorias em português (comida, transporte, férias...)."
    ),
)


# o que roda sozinho e o que pede o "Allow". Não é segurança de verdade.
LEITURA = ToolAnnotations(readOnlyHint=True)
ESCRITA = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


# O SQL devolve tuplas; aqui damos nome a cada posição para o cliente externo

_COLUNAS_TRANSACAO = (
    "id", "amount", "type_id", "category_id", "category_name",
    "description", "payment_method", "occurred_at",
)


def _linha_para_dict(linha) -> dict[str, Any]:
    item = dict(zip(_COLUNAS_TRANSACAO, linha))
    if item.get("amount") is not None:
        item["amount"] = float(item["amount"])
    if item.get("occurred_at") is not None:
        item["occurred_at"] = str(item["occurred_at"])
    return item


@mcp.tool(
    name="query_transactions",
    title="Consultar transações",
    description=(
        "Lista transações (até 50) com filtros opcionais de período e categoria. "
        "Sem filtros, devolve as mais recentes primeiro. Use `days` para 'últimos N dias', "
        "ou `start_date` + `end_date` para um intervalo (nesse caso vem em ordem cronológica). "
        "`category` aceita o nome da categoria ou uma palavra-chave (ex.: comida, uber, férias)."
    ),
    annotations=LEITURA,
)
def query_transactions(
    start_date: Annotated[Optional[str], Field(description="Data inicial YYYY-MM-DD (use junto com end_date).")] = None,
    end_date: Annotated[Optional[str], Field(description="Data final YYYY-MM-DD, inclusiva.")] = None,
    days: Annotated[Optional[int], Field(description="Últimos N dias (ex.: 7 para a última semana).")] = None,
    category: Annotated[Optional[str], Field(description="Categoria ou palavra-chave (ex.: comida, transporte, férias).")] = None,
    limit: Annotated[Optional[int], Field(description="Máximo de linhas a devolver (1 a 50).", ge=1, le=50)] = None,
) -> dict[str, Any]:
    resultado = _query_transactions.invoke({
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "category": category,
    })
    if resultado.get("status") != "ok":
        return resultado

    linhas = resultado["transactions"]
    
    
    if limit:
        linhas = linhas[:limit]
    return {
        "status": "ok",
        "total": len(linhas),
        "transactions": [_linha_para_dict(linha) for linha in linhas],
    }


@mcp.tool(
    name="total_balance",
    title="Saldo total",
    description="Saldo de todo o histórico: receitas menos despesas.",
    annotations=LEITURA,
)
def total_balance() -> dict[str, Any]:
    return _total_balance.invoke({})


@mcp.tool(
    name="daily_balance",
    title="Saldo do dia",
    description=(
        "Saldo de um dia (receitas − despesas). Se `category` for informada, "
        "devolve apenas o total gasto naquela categoria no dia."
    ),
    annotations=LEITURA,
)
def daily_balance(
    date: Annotated[str, Field(description="Dia no formato YYYY-MM-DD (America/Sao_Paulo).")],
    category: Annotated[Optional[str], Field(description="Categoria opcional (ex.: comida, transporte).")] = None,
) -> dict[str, Any]:
    return _daily_balance.invoke({"date": date, "category": category})


def _executar_escrita_mcp(ferramenta, argumentos: dict[str, Any]) -> dict[str, Any]:
    """Uma chamada MCP autorizada pelo cliente é sua própria transação SQL.

    O juiz LLM existe apenas no /chat. No MCP, o cliente deve obter a
    autorização do usuário antes de chamar uma ferramenta com escrita.
    """
    from app.escrita_adiada import iniciar, atual, finalizar, limpar
    token = iniciar(user_id="usuario_teste")
    try:
        resultado = ferramenta.invoke(argumentos)
        pendente = atual()
        aprovado = (resultado.get("status") == "ok" and not pendente.falhou)
        finalizar(aprovado)
        if not aprovado:
            return resultado if resultado.get("status") != "ok" else {
                "status": "error", "message": "A transação não foi confirmada."
            }
        resultado.pop("pending", None)
        return resultado
    finally:
        limpar(token)


@mcp.tool(
    name="add_transaction",
    title="Registrar transação",
    description=(
        "Registra uma transação na tabela transactions. Informe o valor sempre positivo "
        "e o tipo por nome (INCOME | EXPENSES | TRANSFER). Sem tipo, assume EXPENSES; "
        "sem categoria, assume 'outros'; sem data, usa agora."
    ),
    annotations=ESCRITA,
)
def add_transaction(
    amount: Annotated[float, Field(description="Valor da transação (sempre positivo).", gt=0)],
    source_text: Annotated[str, Field(description="Texto original que originou o lançamento (ex.: 'gastei 30 no mercado').")],
    type_name: Annotated[Optional[str], Field(description="INCOME | EXPENSES | TRANSFER (aceita também: entrada, receita, despesa, gasto, salário).")] = None,
    category_name: Annotated[Optional[str], Field(description="Categoria em pt-BR: comida, besteira, estudo, férias, transporte, moradia, saúde, lazer, contas, investimento, presente, outros.")] = None,
    description: Annotated[Optional[str], Field(description="Descrição curta (opcional).")] = None,
    payment_method: Annotated[Optional[str], Field(description="Forma de pagamento (opcional): pix, cartão, dinheiro...")] = None,
    occurred_at: Annotated[Optional[str], Field(description="'hoje', 'ontem' ou timestamp ISO 8601. Se ausente, usa agora.")] = None,
) -> dict[str, Any]:
    return _executar_escrita_mcp(_add_transaction, {
        "amount": amount,
        "source_text": source_text,
        "type_name": type_name,
        "category_name": category_name,
        "description": description,
        "payment_method": payment_method,
        "occurred_at": occurred_at,
    })


@mcp.tool(
    name="update_transaction",
    title="Atualizar transação",
    description=(
        "Atualiza uma transação existente. Localize por `id` OU por `match_text` + `date_local` "
        "(a mais recente daquele dia cujo texto/descrição contém match_text). "
        "Informe pelo menos um campo a alterar."
    ),
    annotations=ESCRITA,
)
def update_transaction(
    id: Annotated[Optional[int], Field(description="ID da transação. Se ausente, use match_text + date_local.")] = None,
    match_text: Annotated[Optional[str], Field(description="Trecho do texto/descrição para localizar a transação (sem id).")] = None,
    date_local: Annotated[Optional[str], Field(description="Dia YYYY-MM-DD (America/Sao_Paulo) usado junto com match_text.")] = None,
    amount: Annotated[Optional[float], Field(description="Novo valor (zero permitido para remoção lógica).", ge=0)] = None,
    type_name: Annotated[Optional[str], Field(description="Novo tipo: INCOME | EXPENSES | TRANSFER.")] = None,
    category_name: Annotated[Optional[str], Field(description="Nova categoria em pt-BR.")] = None,
    description: Annotated[Optional[str], Field(description="Nova descrição.")] = None,
    payment_method: Annotated[Optional[str], Field(description="Novo meio de pagamento.")] = None,
    occurred_at: Annotated[Optional[str], Field(description="Novo timestamp ISO 8601.")] = None,
) -> dict[str, Any]:
    return _executar_escrita_mcp(_update_transaction, {
        "id": id,
        "match_text": match_text,
        "date_local": date_local,
        "amount": amount,
        "type_name": type_name,
        "category_name": category_name,
        "description": description,
        "payment_method": payment_method,
        "occurred_at": occurred_at,
    })


# BOOT — o cliente MCP é quem inicia este processo; não há uvicorn nem porta.


if __name__ == "__main__":
    from app.config import DATABASE_URL

    if not DATABASE_URL:
        print("[assessor-financeiro] DATABASE_URL ausente no .env", file=sys.stderr)

    mcp.run(transport="stdio")
