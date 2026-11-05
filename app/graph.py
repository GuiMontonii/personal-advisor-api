import operator
import re
from typing import Annotated
from langgraph.graph import StateGraph, MessagesState, END
from langchain_core.messages import RemoveMessage
from langchain_core.runnables import RunnableConfig
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from app.tools.financeiro import TOOLS
from app.tools.agenda import TOOLS_AGENDA
from app.tools.faq import FAQ_TOOLS
from app.tools.memoria import TOOLS_MEMORIA
from app.tools.perfil import TOOLS_PERFIL
from app.llms import llm_especialista, llm_rapido
from app.guardrail import guardrail_entrada, guardrail_saida, anonimizar_entrada, desanonimizar_saida
from app.memory import salvar_turno
from app.observabilidade import abrir_turno, fechar_turno, status_do_estado
from app.escrita_adiada import iniciar, atual, finalizar, limpar
from app.roteamento import interpretar_roteador, com_contexto_temporal

from app.prompts import (
    contexto_temporal,
    ROUTER_PROMPT_COMPLETO,
    FINANCEIRO_PROMPT_COMPLETO,
    AGENDA_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO,
    FAQ_PROMPT_COMPLETO,
)


router_app = create_agent(
    model=llm_rapido,
    tools=TOOLS_MEMORIA,
    system_prompt=ROUTER_PROMPT_COMPLETO,
)

financeiro_app = create_agent(
    model=llm_especialista,
    tools=TOOLS + TOOLS_MEMORIA + TOOLS_PERFIL,
    system_prompt=FINANCEIRO_PROMPT_COMPLETO,
)

agenda_app = create_agent(
    model=llm_especialista,
    tools=TOOLS_AGENDA + TOOLS_MEMORIA,
    system_prompt=AGENDA_PROMPT_COMPLETO,
)

orquestrador_app = create_agent(
    model=llm_rapido,
    system_prompt=ORQUESTRADOR_PROMPT_COMPLETO,
)

faq_app = create_agent(
    model=llm_rapido,
    tools=FAQ_TOOLS,
    system_prompt=FAQ_PROMPT_COMPLETO,
)


TOOL_CALL_LEAK_PATTERN = re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL)

def limpar_tool_call_vazado(texto: str) -> str:
    """Remove blocos <tool_call>...</tool_call> que às vezes vazam como texto
    em vez de serem executados como chamada de ferramenta de verdade."""
    if not texto:
        return texto
    return TOOL_CALL_LEAK_PATTERN.sub("", texto).strip()


class Estado(MessagesState):
    agentes_chamados: Annotated[list[str], operator.add]  
    session_id: str
    rota: str
    mapa_pii: dict
    juiz_aprovou: bool


def no_roteador(estado: Estado, config: RunnableConfig) -> dict:
    saida = router_app.invoke({"messages": com_contexto_temporal(estado["messages"], contexto_temporal())}, config=config)
    texto = saida["messages"][-1].text

    rota, resposta_direta = interpretar_roteador(texto)

    
    if not rota:
        return {
            "agentes_chamados": ["roteador"],
            "rota": rota,
            "messages": [{"role": "assistant", "content": resposta_direta}],
        }

    return {
        "agentes_chamados": ["roteador"],
        "rota": rota,
    }


def no_financeiro(estado: Estado, config: RunnableConfig) -> dict:
    saida = financeiro_app.invoke(
        {"messages": com_contexto_temporal(estado["messages"], contexto_temporal())},
        config=config,
    )
    ultima = saida["messages"][-1]
    texto_limpo = limpar_tool_call_vazado(ultima.text)

    return {
        "agentes_chamados": ["financeiro"],
        "messages": [{"role": "assistant", "content": texto_limpo}],
    }


def no_agenda(estado: Estado, config: RunnableConfig) -> dict:
    # config: sem ele o modelo deste nó não herda o metadata do grafo e o
    
    saida = agenda_app.invoke({"messages": com_contexto_temporal(estado["messages"], contexto_temporal())}, config=config)
    ultima = saida["messages"][-1]
    texto_limpo = limpar_tool_call_vazado(ultima.text)

    return {
        "agentes_chamados": ["agenda"],
        "messages": [{"role": "assistant", "content": texto_limpo}],
    }


def no_faq(estado: Estado, config: RunnableConfig) -> dict:
    saida = faq_app.invoke({"messages": com_contexto_temporal(estado["messages"], contexto_temporal())}, config=config)
    ultima = saida["messages"][-1]
    texto_limpo = limpar_tool_call_vazado(ultima.text)

    return {
        "agentes_chamados": ["faq"],
        "messages": [{"role": "assistant", "content": texto_limpo}],
    }


def no_orquestrador(estado: Estado, config: RunnableConfig) -> dict:
    ultima_especialista = ""
    for mensagem in reversed(estado["messages"]):
        if mensagem.type == "ai" and mensagem.text:
            ultima_especialista = mensagem.text
            break

    
    # não herda o metadata do grafo (e o registro de observabilidade perde o nó).
    saida = orquestrador_app.invoke({
        "messages": [{"role": "human", "content": ultima_especialista}]
    }, config=config)

    texto_limpo = limpar_tool_call_vazado(saida["messages"][-1].text)

    return {
        "agentes_chamados": ["orquestrador"],
        "messages": [{"role": "assistant", "content": texto_limpo}],
    }


def no_guardrail_entrada(estado: Estado) -> dict:
    """Anonimiza PII e roda o guardrail de entrada.
    Ligado como porta de entrada do grafo (Etapa 6): é daqui que a tela de
    monitoramento tira o status "bloqueado"."""
    human_message = list(estado["messages"])[-1]

    texto_anonimizado, mapa = anonimizar_entrada(human_message.text)

    resultado = guardrail_entrada(texto_anonimizado)

    if resultado["bloqueado"]:
        return {
            "messages": [
                RemoveMessage(id=human_message.id),
                {"role": "human", "content": texto_anonimizado},
                {"role": "assistant", "content": resultado["mensagem"]},
            ],
            "rota": "fim",
            "mapa_pii": {},
            "agentes_chamados": [f"guardrail_entrada:{resultado['motivo']}"],
        }

    return {
        "messages": [
            RemoveMessage(id=human_message.id),
            {"role": "human", "content": texto_anonimizado},
        ],
        "mapa_pii": mapa,
        "agentes_chamados": ["guardrail_entrada:aprovado"],
        "rota": "",
    }


def no_guardrail_saida(estado: Estado) -> dict:
    ultima = ""
    for msg in reversed(estado["messages"]):
        if msg.type == "ai" and msg.text:
            ultima = msg.text
            break

    pedido = next((m.text for m in reversed(estado["messages"]) if m.type == "human"), "")
    pendentes = atual()
    resultado = guardrail_saida(ultima, estado.get("mapa_pii", {}),
                                pergunta=pedido, operacoes=pendentes.operacoes if pendentes else [])

    return {
        "messages": [{"role": "assistant", "content": resultado["conteudo"]}],
        "agentes_chamados": ["guardrail_saida"],
        "juiz_aprovou": resultado["aprovado"],
    }


def decidir_especialista(estado: Estado) -> str:
    """Lê o protocolo do roteador e devolve o nome do próximo nó"""
    return estado["rota"] if estado["rota"] in ("financeiro", "agenda", "faq") else "fim"


def decidir_apos_guardrail(estado: Estado) -> str:
    """Guardrail de entrada bloqueou (rota == "fim")? Encerra. Senão, segue para o roteador."""
    return "fim" if estado.get("rota") == "fim" else "roteador"


grafo = StateGraph(Estado)

grafo.add_node("guardrail_entrada", no_guardrail_entrada)
grafo.add_node("roteador", no_roteador)
grafo.add_node("financeiro", no_financeiro)
grafo.add_node("agenda", no_agenda)
grafo.add_node("faq", no_faq)
grafo.add_node("orquestrador", no_orquestrador)
grafo.add_node("guardrail_saida", no_guardrail_saida)

grafo.set_entry_point("guardrail_entrada")

grafo.add_conditional_edges(
    "guardrail_entrada",
    decidir_apos_guardrail,
    {
        "roteador": "roteador",
        "fim": END,  
    },
)

grafo.add_conditional_edges(
    "roteador",
    decidir_especialista,
    {
        "financeiro": "financeiro",
        "agenda": "agenda",
        "faq": "faq",
        "fim": END,  
    },
)

grafo.add_edge("financeiro", "orquestrador")
grafo.add_edge("agenda", "orquestrador")
grafo.add_edge("orquestrador", "guardrail_saida")
grafo.add_edge("guardrail_saida", END)
grafo.add_edge("faq", END)  


memory = MemorySaver()
fluxo_agentes = grafo.compile(checkpointer=memory)


def _registrar_recusa_no_historico(config_grafo: dict, estado_final: dict, resposta: str) -> None:
    """A resposta do checkpoint deve refletir o rollback, não um lançamento preparado."""
    try:
        ultima = estado_final["messages"][-1]
        fluxo_agentes.update_state(
            config_grafo,
            {"messages": [RemoveMessage(id=ultima.id), {"role": "assistant", "content": resposta}]},
            as_node="guardrail_saida",
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Não foi possível atualizar checkpoint após rollback")


def executar_fluxo_assessor(
    pergunta_usuario: str, session_id: str, user_id: str = "usuario_teste",
    retornar_agentes: bool = False,
) -> str | tuple[str, list[str]]:
    pergunta_usuario_anonimizado, _ = anonimizar_entrada(pergunta_usuario)
    estado_inicial = {
        "messages":         [{"role": "human", "content": pergunta_usuario}],
        "agentes_chamados": [],
        "rota":             "",
        "mapa_pii":         {},
        "session_id":       session_id,
        "juiz_aprovou": False,
    }

    
    turno_id = abrir_turno()
    token_escrita = iniciar(user_id=user_id)
    status = "erro"
    rota = ""
    config_grafo = {"configurable": {"thread_id": session_id, "user_id": user_id}}
    try:
        estado_final = fluxo_agentes.invoke(estado_inicial, config=config_grafo)

        resposta = estado_final["messages"][-1].text
        pendentes = atual()
        if pendentes and pendentes.operacoes:
            aprovado = (not pendentes.falhou) and estado_final.get("juiz_aprovou") is True and "guardrail_saida" in (
                estado_final.get("agentes_chamados") or []
            )
            finalizar(aprovado)
            if not aprovado:
                resposta = "Não pude aprovar essa operação. Nenhuma alteração foi salva."
                _registrar_recusa_no_historico(config_grafo, estado_final, resposta)


        try:
            salvar_turno(session_id, pergunta_usuario_anonimizado, resposta, user_id=user_id)
        except Exception:
            
            
            import logging
            logging.getLogger(__name__).exception("Falha ao salvar histórico do turno")

        status = status_do_estado(estado_final)
        rota = estado_final.get("rota") or ""
        
        
        if rota not in ("financeiro", "agenda", "faq", "fim"):
            rota = "direto"
        if retornar_agentes:
            historico = estado_final.get("agentes_chamados") or []
            
            
            inicio_turno = max((i for i, nome in enumerate(historico)
                                if isinstance(nome, str) and nome.startswith("guardrail_entrada:")),
                               default=-1)
            agentes = [nome for nome in historico[inicio_turno + 1:]
                       if nome in ("roteador", "financeiro", "agenda", "faq", "orquestrador")]
            return resposta, agentes
        return resposta
    finally:
        try:
            limpar(token_escrita)
        finally:
            fechar_turno(turno_id, session_id=session_id, rota=rota, status=status)
