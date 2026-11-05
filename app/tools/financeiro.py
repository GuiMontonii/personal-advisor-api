import psycopg2 
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Optional, List 
from langchain.tools import tool 
from pydantic import BaseModel, Field 
from app.tools.conexao import get_conn
from app.escrita_adiada import conexao_escrita, registrar, marcar_falha
from app.config import DATABASE_URL

DATABASE_URL = DATABASE_URL
FUSO = ZoneInfo("America/Sao_Paulo")


class AddTransactionArgs(BaseModel):
    amount: float = Field(..., description="Valor da transação (use positivo).") 
    source_text: str = Field(..., description="Texto original do usuário.") 
    occurred_at: Optional[str] = Field(
        default=None,
        description="Timestamp ISO 8601; se ausente, usa NOW() no banco."
    )
    type_id: Optional[int] = Field(default=None, description="ID em transaction_types (1=INCOME, 2=EXPENSES, 3=TRANSFER).")
    type_name: Optional[str] = Field(default=None, description="Nome do tipo: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="ID cadastrado na tabela categories (prefira category_name).")
    category_name: Optional[str] = Field(default=None, description="Nome da categoria em pt-BR (ex: comida, transporte). Alternativa ao category_id.")
    description: Optional[str] = Field(default=None, description="Descrição (opcional).")
    payment_method: Optional[str] = Field(default=None, description="Forma de pagamento (opcional).")

class QueryTransactionsArgs(BaseModel):
    start_date: Optional[str] = Field(default=None, description="Data inicial no formato YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="Data final no formato YYYY-MM-DD")
    days: Optional[int] = Field(default=None, gt=0, description="Quantidade de dias para buscar (ex: 7 para última semana)")
    category: Optional[str] = Field(default=None, description="Categoria ou palavra-chave da transação (ex: comida, transporte)")

class TotalBalanceArgs(BaseModel):
    """Sem parâmetros necessários"""
    pass

class DailyBalanceArgs(BaseModel):
    date: str = Field(..., description="Data no formato YYYY-MM-DD")
    category: Optional[str] = Field(default=None, description="Categoria opcional (ex: comida, transporte)")

TYPE_ALIASES = { 
    "INCOME": "INCOME", "ENTRADA": "INCOME", "RECEITA": "INCOME", "SALÁRIO": "INCOME", "SALARIO": "INCOME",
    "EXPENSE": "EXPENSES", "EXPENSES": "EXPENSES", "DESPESA": "EXPENSES", "GASTO": "EXPENSES", "SAÍDA": "EXPENSES", "SAIDA": "EXPENSES",
    "TRANSFER": "TRANSFER", "TRANSFERÊNCIA": "TRANSFER", "TRANSFÊRENCIA": "TRANSFER", "TRANSFERENCIA": "TRANSFER", 
}

TYPE_CATEGORIES = {
      
    "COMIDA": "comida", "ALIMENTO": "comida", "ALIMENTOS": "comida",
    "RESTAURANTE": "comida", "LANCHONETE": "comida", "FAST FOOD": "comida",
    "MC DONALDS": "comida", "MCDONALD'S": "comida", "BURGER KING": "comida",
    "PIZZA": "comida", "HAMBURGUER": "comida", "LANCHE": "comida",
    "ALMOÇO": "comida", "JANTAR": "comida", "CAFÉ": "comida",
    "ARROZ": "comida", "FEIJÃO": "comida", "COMPRAS MERCADO": "comida",
    "SUPERMERCADO": "comida", "IFOOD": "comida",

    
    "BESTEIRA": "besteira", "DOCE": "besteira", "DOCES": "besteira",
    "CHOCOLATE": "besteira", "BALAS": "besteira", "BALA": "besteira",
    "SORVETE": "besteira", "SNACK": "besteira", "SALGADINHO": "besteira",
    "REFRIGERANTE": "besteira", "COCA": "besteira",

    
    "ESTUDO": "estudo", "ESCOLA": "estudo", "FACULDADE": "estudo",
    "CURSO": "estudo", "CURSOS": "estudo", "LIVRO": "estudo",
    "LIVROS": "estudo", "MATERIAL": "estudo", "CADERNO": "estudo",
    "CANETA": "estudo", "APOSTILA": "estudo", "EDUCAÇÃO": "estudo",

    
    "FERIAS": "férias", "FÉRIAS": "férias", "VIAGEM": "férias",
    "HOTEL": "férias", "PASSAGEM": "férias", "AVIÃO": "férias",
    "AEROPORTO": "férias", "RESORT": "férias", "TURISMO": "férias",

    
    "TRANSPORTE": "transporte", "UBER": "transporte", "99": "transporte",
    "TAXI": "transporte", "ÔNIBUS": "transporte", "METRO": "transporte",
    "GASOLINA": "transporte", "COMBUSTIVEL": "transporte",
    "PEDAGIO": "transporte", "ESTACIONAMENTO": "transporte",

    
    "MORADIA": "moradia", "ALUGUEL": "moradia", "CONDOMINIO": "moradia",
    "CASA": "moradia", "APARTAMENTO": "moradia", "REFORMA": "moradia",
    "MÓVEIS": "moradia", "MOVEIS": "moradia",

    
    "SAUDE": "saúde", "SAÚDE": "saúde", "MEDICO": "saúde",
    "CONSULTA": "saúde", "HOSPITAL": "saúde", "REMEDIO": "saúde",
    "REMÉDIO": "saúde", "FARMACIA": "saúde", "PLANO DE SAUDE": "saúde",
    "DENTISTA": "saúde",

    
    "LAZER": "lazer", "CINEMA": "lazer", "FILME": "lazer",
    "NETFLIX": "lazer", "SPOTIFY": "lazer", "JOGO": "lazer",
    "GAMES": "lazer", "SHOW": "lazer", "FESTA": "lazer",
    "BALADA": "lazer",

    
    "CONTAS": "contas", "BOLETO": "contas", "LUZ": "contas",
    "ÁGUA": "contas", "AGUA": "contas", "INTERNET": "contas",
    "WIFI": "contas", "ENERGIA": "contas", "TELEFONE": "contas",

    
    "INVESTIMENTO": "investimento", "INVESTIR": "investimento",
    "AÇÃO": "investimento", "ACOES": "investimento", "AÇÕES": "investimento",
    "CRIPTO": "investimento", "BITCOIN": "investimento",
    "RENDA FIXA": "investimento", "TESOURO DIRETO": "investimento",

    
    "PRESENTE": "presente", "PRESENTEAR": "presente",
    "ANIVERSARIO": "presente", "ANIVERSÁRIO": "presente",
    "NATAL": "presente", "SURPRESA": "presente",

    
    "OUTROS": "outros", "DIVERSOS": "outros", "VARIOS": "outros"
}


def _resolve_type_id(cur, type_id: Optional[int], type_name: Optional[str]) -> Optional[int]:
    if type_name:
        nome = TYPE_ALIASES.get(type_name.strip().upper(), type_name.strip().upper())
        cur.execute("SELECT id FROM transaction_types WHERE UPPER(type)=%s ORDER BY id LIMIT 1", (nome,))
        row = cur.fetchone()
        return row[0] if row else None
    if type_id is not None:
        cur.execute("SELECT id FROM transaction_types WHERE id=%s", (type_id,))
        row = cur.fetchone()
        return row[0] if row else None
    return _resolve_type_id(cur, None, "EXPENSES")


def _resolve_type_categories(cur, category_id: Optional[int], category_name: Optional[str]) -> Optional[int]:
    if category_name:
        nome = category_name.strip().upper()
        nome = TYPE_CATEGORIES.get(nome, nome)
        cur.execute("SELECT id FROM categories WHERE LOWER(name)=%s ORDER BY id LIMIT 1", (nome.lower(),))
        row = cur.fetchone()
        return row[0] if row else None
    if category_id is not None:
        cur.execute("SELECT id FROM categories WHERE id=%s", (category_id,))
        row = cur.fetchone()
        return row[0] if row else None
    return _resolve_type_categories(cur, None, "outros")


def _validar_data_local(valor: str) -> str:
    return date.fromisoformat(valor).isoformat()


def _validar_data_hora(valor: str) -> str:
    data = datetime.fromisoformat(valor)
    if data.utcoffset() is None:
        raise ValueError("Informe data e hora com fuso horário ISO 8601 (ex.: 2026-11-04T14:00:00-03:00).")
    return data.isoformat()


def _local_date_filter_sql(field: str = "occurred_at") -> str:
    """
    Retorna um trecho SQL para filtragem por dia local em America/Sao_Paulo.
    Ex.: (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s::date
    """
    return f"(({field} AT TIME ZONE 'America/Sao_Paulo')::date = %s::date)"    


@tool("add_transaction", args_schema=AddTransactionArgs) 
def add_transaction( 
    amount: float, 
    source_text: str,
    occurred_at: Optional[str] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
) -> dict:
    """Insere uma transação financeira no banco de dados Postgres.""" 
    conn = None
    cur = None
    try:
        if not math.isfinite(amount) or amount <= 0 or not source_text.strip():
            raise ValueError("Informe valor positivo e texto de origem da transação.")
        conn = conexao_escrita()
        cur = conn.cursor()
        resolved_type_id = _resolve_type_id(cur, type_id, type_name) 
        resolved_category_id = _resolve_type_categories(cur, category_id, category_name)

        if not resolved_type_id:
            marcar_falha()
            return {"status": "error", "message": "Tipo inválido (use type_id ou type_name: INCOME/EXPENSES/TRANSFER)."}
        
        if not resolved_category_id:
            marcar_falha()
            return {"status": "error", "message": "Categoria inválida ou categoria 'outros' não cadastrada."}

        if isinstance(occurred_at, str):
            occurred_at = occurred_at.strip()
            if occurred_at.lower() in ("hoje", "ontem"):
                occurred_at = occurred_at.lower()

        if occurred_at == "ontem":
            cur.execute("""
                INSERT INTO transactions
                (amount, type, category_id, description, payment_method, occurred_at, source_text)
                VALUES
                (%s, %s, %s, %s, %s, NOW() - INTERVAL '1 day', %s)
                RETURNING id, occurred_at;
            """, (amount, resolved_type_id, resolved_category_id, description, payment_method, source_text))

        elif occurred_at == "hoje" or not occurred_at:
            cur.execute("""
                INSERT INTO transactions
                (amount, type, category_id, description, payment_method, occurred_at, source_text)
                VALUES
                (%s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id, occurred_at;
            """, (amount, resolved_type_id, resolved_category_id, description, payment_method, source_text))

        else:
            occurred_at = _validar_data_hora(occurred_at)
            cur.execute("""
                INSERT INTO transactions
                (amount, type, category_id, description, payment_method, occurred_at, source_text)
                VALUES
                (%s, %s, %s, %s, %s, %s::timestamptz, %s)
                RETURNING id, occurred_at;
            """, (amount, resolved_type_id, resolved_category_id, description, payment_method, occurred_at, source_text))

        new_id, occurred = cur.fetchone() 
        registrar("add_transaction", {"id": new_id, "amount": amount}) 
        return {"status": "ok", "id": new_id, "occurred_at": str(occurred)}

    except Exception as e: 
        marcar_falha()
        if conn is not None:
            conn.rollback() 
        return {"status": "error", "message": str(e) if isinstance(e, ValueError) else "Não foi possível concluir a operação financeira."}
    
    finally: 
        try:
            if cur is not None:
                cur.close()
            

        except Exception:
            pass    

def _linha_serializavel(r) -> tuple:
    """Preserva ordem original, serializa NUMERIC/datetime para API e cliente MCP."""
    return (
        r[0], float(r[1]) if r[1] is not None else None, r[2], r[3], r[4], r[5], r[6],
        r[7].astimezone(FUSO).isoformat() if hasattr(r[7], "astimezone") else r[7],
    )

@tool("query_transactions", args_schema=QueryTransactionsArgs)
def query_transactions(start_date: Optional[str] = None, end_date: Optional[str] = None, days: Optional[int] = None, category: Optional[str] = None) -> dict:
    """Consulta transações com filtros de data, período ou categoria."""

    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        query = """
            SELECT 
                t.id,
                t.amount,
                t.type,
                t.category_id,
                c.name AS category_name,
                t.description,
                t.payment_method,
                t.occurred_at
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE 1=1
        """

        params = []

        order_by = "DESC"
        if days is not None:
            if days <= 0:
                raise ValueError("days precisa ser maior que zero.")
            query += " AND t.occurred_at >= NOW() - (%s * INTERVAL '1 day')"
            params.append(days)
        else:
            if start_date:
                query += " AND (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date >= %s::date"
                params.append(_validar_data_local(start_date))
            if end_date:
                query += " AND (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date <= %s::date"
                params.append(_validar_data_local(end_date))
            if start_date and end_date:
                if start_date > end_date:
                    raise ValueError("A data inicial deve ser anterior ou igual à data final.")
                order_by = "ASC"

        if category:
            nome = category.strip().upper()
            
            if nome in TYPE_CATEGORIES:
                nome = TYPE_CATEGORIES[nome]
            
            query += " AND LOWER(c.name) = %s"
            params.append(nome.lower())

        query += f" ORDER BY t.occurred_at {order_by} LIMIT 50"

        cur.execute(query, tuple(params))
        rows = cur.fetchall()

        return {
            "status": "ok",
            "total": len(rows),
            "transactions": [_linha_serializavel(r) for r in rows]
        }

    except Exception as e:
        if conn is not None:
            conn.rollback()
        return {"status": "error", "message": str(e) if isinstance(e, ValueError) else "Não foi possível concluir a operação financeira."}

    finally:
        try:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()
        except Exception:
            pass

@tool("total_balance", args_schema=TotalBalanceArgs)
def total_balance() -> dict:
    """Retorna o saldo total (entradas - saídas)."""
    
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN UPPER(tt.type) = 'INCOME' THEN t.amount ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN UPPER(tt.type) = 'EXPENSES' THEN t.amount ELSE 0 END), 0)
            FROM transactions t JOIN transaction_types tt ON tt.id = t.type;
        """)

        balance = cur.fetchone()[0]

        return {
            "status": "ok",
            "balance": float(balance)
        }

    except Exception as e:
        if conn is not None:
            conn.rollback()
        return {"status": "error", "message": str(e) if isinstance(e, ValueError) else "Não foi possível concluir a operação financeira."}

    finally:
        try:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

        except Exception:
            pass     

@tool("daily_balance", args_schema=DailyBalanceArgs)
def daily_balance(date: str, category: Optional[str] = None) -> dict:
    """Retorna o saldo do dia (entradas - saídas) ou o total gasto por uma categoria específica."""
    
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        date = _validar_data_local(date)
        if category:
            nome = category.strip().upper()

            if nome in TYPE_CATEGORIES:
                nome = TYPE_CATEGORIES[nome]

            cur.execute("""
                SELECT COALESCE(SUM(t.amount), 0)
                FROM transactions t
                JOIN categories c ON c.id = t.category_id
                JOIN transaction_types tt ON tt.id = t.type
                WHERE UPPER(tt.type) = 'EXPENSES'
                AND LOWER(c.name) = %s
                AND (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s;
            """, (nome.lower(), date))

            total_categoria = cur.fetchone()[0]

            return {
                "status": "ok",
                "date": date,
                "category": category,
                "category_spent": float(total_categoria)
            }

        else:
            cur.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN UPPER(tt.type) = 'INCOME' THEN t.amount ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN UPPER(tt.type) = 'EXPENSES' THEN t.amount ELSE 0 END), 0)
                FROM transactions t JOIN transaction_types tt ON tt.id = t.type
                WHERE (t.occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s;
            """, (date,))

            saldo_diario = cur.fetchone()[0]

            return {
                "status": "ok",
                "date": date,
                "daily_balance": float(saldo_diario)
            }

    except Exception as e:
        if conn is not None:
            conn.rollback()
        return {"status": "error", "message": str(e) if isinstance(e, ValueError) else "Não foi possível concluir a operação financeira."}

    finally:
        try:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()
        except Exception:
            pass

class UpdateTransactionArgs(BaseModel):
    id: Optional[int] = Field(
        default=None,
        description="ID da transação a atualizar. Se ausente, será feita uma busca por (match_text + date_local)."
    )
    match_text: Optional[str] = Field(
        default=None,
        description="Texto para localizar transação quando id não for informado (busca em source_text/description)."
    )
    date_local: Optional[str] = Field(
        default=None,
        description="Data local (YYYY-MM-DD) em America/Sao_Paulo; usado em conjunto com match_text quando id ausente."
    )
    amount: Optional[float] = Field(default=None, ge=0, description="Novo valor (zero permitido para marcar remoção lógica).")
    type_id: Optional[int] = Field(default=None, description="Novo type_id (1/2/3).")
    type_name: Optional[str] = Field(default=None, description="Novo type_name: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="Nova categoria (id).")
    category_name: Optional[str] = Field(default=None, description="Nova categoria (nome).")
    description: Optional[str] = Field(default=None, description="Nova descrição.")
    payment_method: Optional[str] = Field(default=None, description="Novo meio de pagamento.")
    occurred_at: Optional[str] = Field(default=None, description="Novo timestamp ISO 8601.")

@tool("update_transaction", args_schema=UpdateTransactionArgs)
def update_transaction(
    id: Optional[int] = None,
    match_text: Optional[str] = None,
    date_local: Optional[str] = None,
    amount: Optional[float] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> dict:
    """
    Atualiza uma transação existente.
    Estratégias:
      - Se 'id' for informado: atualiza diretamente por ID.
      - Caso contrário: localiza a transação mais recente que combine (match_text em source_text/description)
        E (date_local em America/Sao_Paulo), então atualiza.
    Retorna: status, rows_affected, id, e o registro atualizado.
    """
    if all(v is None for v in (amount, type_id, type_name, category_id, category_name, description, payment_method, occurred_at)):
        marcar_falha()
        return {"status": "error", "message": "Nada para atualizar: forneça pelo menos um campo (amount, type, category, description, payment_method, occurred_at)."}

    conn = None
    cur = None
    try:
        if amount is not None and (not math.isfinite(amount) or amount < 0):
            raise ValueError("O valor não pode ser negativo.")
        if date_local is not None:
            date_local = _validar_data_local(date_local)
        if occurred_at is not None:
            occurred_at = _validar_data_hora(occurred_at)
        conn = conexao_escrita()
        cur = conn.cursor()
        
        target_id = id
        if target_id is None:
            if not match_text or not date_local:
                marcar_falha()
                return {"status": "error", "message": "Sem 'id': informe match_text E date_local para localizar o registro."}

            
            cur.execute(
                f"""
                SELECT t.id
                FROM transactions t
                WHERE (POSITION(LOWER(%s) IN LOWER(t.source_text)) > 0
                   OR POSITION(LOWER(%s) IN LOWER(COALESCE(t.description, ''))) > 0)
                  AND {_local_date_filter_sql("t.occurred_at")}
                ORDER BY t.occurred_at DESC
                LIMIT 1;
                """,
                (match_text, match_text, date_local)
            )
            row = cur.fetchone()
            if not row:
                marcar_falha()
                return {"status": "error", "message": "Nenhuma transação encontrada para os filtros fornecidos."}
            target_id = row[0]

        
        resolved_type_id = _resolve_type_id(cur, type_id, type_name) if (type_id or type_name) else None
        resolved_category_id = (
            _resolve_type_categories(cur, category_id, category_name if category_id is None else None)
            if category_id is not None or category_name is not None else None
        )

        if (type_name is not None or type_id is not None) and resolved_type_id is None:
            raise ValueError("Tipo de transação inválido.")
        if (category_name is not None or category_id is not None) and resolved_category_id is None:
            raise ValueError("Categoria inválida.")

        
        sets = []
        params: List[object] = []
        if amount is not None:
            sets.append("amount = %s")
            params.append(amount)

        if resolved_type_id is not None:
            sets.append("type = %s")
            params.append(resolved_type_id)

        if resolved_category_id is not None:
            sets.append("category_id = %s")
            params.append(resolved_category_id)

        if description is not None:
            sets.append("description = %s")
            params.append(description)

        if payment_method is not None:
            sets.append("payment_method = %s")
            params.append(payment_method)
            
        if occurred_at is not None:
            sets.append("occurred_at = %s::timestamptz")
            params.append(occurred_at)

        if not sets:
            marcar_falha()
            return {"status": "error", "message": "Nenhum campo válido para atualizar."}

        params.append(target_id)

        cur.execute(
            f"UPDATE transactions SET {', '.join(sets)} WHERE id = %s;",
            params
        )
        rows_affected = cur.rowcount
        if rows_affected == 0:
            marcar_falha()
            return {"status": "error", "message": "Transação não encontrada."}
        

        cur.execute(
            """
            SELECT
              t.id, t.occurred_at, t.amount, tt.type AS type_name,
              c.name AS category_name, t.description, t.payment_method, t.source_text
            FROM transactions t
            JOIN transaction_types tt ON tt.id = t.type
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = %s;
            """,
            (target_id,)
        )
        r = cur.fetchone()
        updated = None
        if r:
            updated = {
                "id": r[0],
                "occurred_at": str(r[1]),
                "amount": float(r[2]),
                "type": r[3],
                "category": r[4],
                "description": r[5],
                "payment_method": r[6],
                "source_text": r[7],
            }

        registrar("update_transaction", {"id": target_id, "rows_affected": rows_affected, "updated": updated})
        return {
            "status": "ok",
            "rows_affected": rows_affected,
            "id": target_id,
            "updated": updated
        }

    except Exception as e:
        marcar_falha()
        if conn is not None:
            conn.rollback()
        return {"status": "error", "message": str(e) if isinstance(e, ValueError) else "Não foi possível concluir a operação financeira."}
    finally:
        try:
            cur.close()
            
        except Exception:
            pass


TOOLS = [add_transaction, query_transactions, total_balance, daily_balance, update_transaction]