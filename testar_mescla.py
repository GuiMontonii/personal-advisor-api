"""Regressões da mescla sem internet, sem credenciais, sem banco real."""
from __future__ import annotations
import importlib.util
import re
import sys
import types
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
contador = 0

def check(cond, descricao):
    global contador
    assert cond, descricao
    contador += 1


class LLM:
    texto = "STATUS: APROVADO\nRESPOSTA:\nTudo certo."
    def invoke(self, prompt): return types.SimpleNamespace(text=self.texto)

llm = LLM()
sys.modules["app.llms"] = types.SimpleNamespace(llm_rapido=llm)
from app.guardrail import anonimizar_entrada, guardrail_entrada, guardrail_saida

for texto in ("2026-11-04T14:00:00-03:00", "2026-11-04", "2026-11-04 às 11:00"):
    t, m = anonimizar_entrada(texto)
    check(t == texto and m == {}, "Uma data ISO não pode ser um número de conta")

for dado, nome in (("1234567890123456", "CARTAO"), ("12345678000190", "CNPJ"),
                   ("123.456.789-09", "CPF"), ("12345-6", "CONTA"),
                   ("(11) 98765-4321", "TELEFONE")):
    t, mapa = anonimizar_entrada(f"Dado: {dado}")
    check(dado not in t and len(mapa) == 1 and nome in t, f"Anonimização {nome}")

llm.texto = "STATUS: APROVADO\nRESPOSTA:\nCartão 1234567890123456, CNPJ 12345678000190, hoje 2026-11-04."
r = guardrail_saida("ok", {}, pergunta="teste")
check(r["aprovado"] and "123456" not in r["conteudo"] and "2026-11-04" in r["conteudo"], "O revisor não pode reintroduzir PII")
llm.texto = "NÃO ESTÁ NO PROTOCOLO"
r = guardrail_saida("Operação foi registrada", {}, pergunta="lançar")
check(not r["aprovado"], "Falha de protocolo do juiz não confirma transação")
llm.texto = "CATEGORIA: TEXTO_INESPERADO"
check(guardrail_entrada("olá")["bloqueado"], "Categoria de segurança desconhecida precisa falhar fechada")

from app.prompts import contexto_temporal
from app.roteamento import interpretar_roteador, com_contexto_temporal, MENSAGEM_PADRAO
ctx = contexto_temporal()
check("America/Sao_Paulo" in ctx and "ISO 8601" in ctx, "Contexto temporal deve ter fuso fixo")
check(bool(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", ctx)), "Contexto temporal deve conter data ISO")
for resposta, esperado in (("ROUTE=financeiro", "financeiro"), ("ROUTE=[agenda]", "agenda"),
                           ("Certo!\nRoute: FAQ", "faq")):
    check(interpretar_roteador(resposta)[0] == esperado, f"Rota {esperado}")
check(interpretar_roteador("ROUTE=fora_escopo")[1] == MENSAGEM_PADRAO, "Rota inválida precisa resposta compreensível")
check(interpretar_roteador("ROUTE=[financeiro|agenda|faq]")[1] == MENSAGEM_PADRAO, "Não confundir lista de opções com rota válida")
check(interpretar_roteador("Olá! Sim, posso ajudar.")[1] == "Olá! Sim, posso ajudar.", "Respostas diretas mantidas")

class Message:
    def __init__(self, tipo, texto): self.type, self.text = tipo, texto
    def model_copy(self, update): return Message(self.type, update["content"])
orig = [Message("human", "anterior"), Message("ai", "ok"), Message("human", "hoje")]
copy = com_contexto_temporal(orig, "CTX")
check(copy[-1].text == "CTX\n\nhoje" and orig[-1].text == "hoje", "Não alterar checkpoint original")
check(copy[0].text == "anterior", "Não alterar mensagens humanas antigas")


from datetime import datetime
source = (BASE / "app/tools/memoria.py").read_text(encoding="utf-8")
import ast
node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_data_br")
part = ast.get_source_segment(source, node)
namespace = {"datetime": datetime}
exec(part, namespace)
_data_br = namespace["_data_br"]
check(_data_br("2026-11-04T13:30:00+00:00") == "04/11/2026", "Data Qdrant string")
check(_data_br(datetime(2026, 11, 4)) == "04/11/2026", "Data Mongo datetime")
check(_data_br("sem data") == "sem data", "Data inesperada não deve derrubar fluxo")

sql = (BASE / "dbAssessorIA.sql").read_text(encoding="utf-8")
check(sql.strip().startswith("-- AssessorIA") and "BEGIN;" in sql and sql.rstrip().endswith("COMMIT;"), "SQL transacional")
check(not re.search(r"(?im)^\s*(DROP|TRUNCATE|DELETE)\s+",sql), "Não apaga dados")
check("ALTER TABLE events RENAME COLUMN start_at TO start_time" in sql, "Compatibilidade SQL com outra agenda")
check("ALTER TABLE events RENAME COLUMN end_at TO end_time" in sql, "Compatibilidade SQL com outra agenda")
check("ALTER TABLE events RENAME COLUMN description TO notes" in sql, "Compatibilidade SQL com outra agenda")
check("WHERE NOT EXISTS" in sql, "Seeds repetíveis")
check("ALTER COLUMN type SET DEFAULT" in sql, "Tipo default consultado por nome")
check("idx_events_user_period" in sql, "Índice da agenda")
check("start_time" in (BASE / "app/tools/agenda.py").read_text(), "SQL de agenda preservado")

chat = (BASE / "app/routes/chat.py").read_text()
graph = (BASE / "app/graph.py").read_text()
check("retornar_agentes=True" in chat and "retornar_agentes: bool = False" in graph, "Contrato do frontend preservado")
check("_registrar_recusa_no_historico" in graph and "salvar_turno(" in graph, "Rollback não registra operação realizada")
check("com_contexto_temporal" in graph and "contexto_temporal()" in graph, "Contexto atualizado em execução")
check(".env" in (BASE / ".gitignore").read_text() and not (BASE / ".env").exists(), "ZIP não leva credenciais")
check((BASE / ".cursor/mcp.json").is_file(), "Configuração MCP preservada")
print(f"PASSOU: {contador} verificações de regressão da mescla")
