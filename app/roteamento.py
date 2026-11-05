"""Funções puras do grafo (sem LangChain): leitura da saída do roteador e contexto temporal.

Ficam num módulo à parte para poderem ser testadas sem subir modelo nenhum
(veja testar_correcoes.py).
"""
import re

ROTAS_VALIDAS = ("financeiro", "agenda", "faq")

MENSAGEM_PADRAO = (
    "Consigo ajudar apenas com finanças ou agenda. "
    "Prefere olhar seus gastos ou marcar um compromisso?"
)


_RE_ROTA = re.compile(
    r"(?im)^\s*ROUTE\s*[=:]\s*\[?\s*(financeiro|agenda|faq)\s*\]?\s*$"
)
_RE_PROTOCOLO = re.compile(r"(?im)^\s*(ROUTE|PERGUNTA_ORIGINAL)\s*[=:].*$")


def interpretar_roteador(texto: str) -> tuple[str, str]:
    """Devolve (rota, resposta_direta).

    - rota preenchida  -> encaminhar para o especialista; resposta_direta é "".
    - rota vazia       -> o roteador respondeu direto (saudação / fora de escopo);
                          resposta_direta é o texto a entregar ao usuário, sem
                          linhas de protocolo.
    """
    texto = texto or ""
    achou = _RE_ROTA.search(texto)
    if achou:
        return achou.group(1).lower(), ""
    limpo = _RE_PROTOCOLO.sub("", texto).strip()
    return "", (limpo or MENSAGEM_PADRAO)


def com_contexto_temporal(mensagens: list, contexto: str) -> list:
    """Cópia da lista de mensagens com o contexto de data/hora colada na ÚLTIMA
    mensagem humana. O estado do grafo (e o checkpoint) não é alterado: só o que
    o agente enxerga nesta chamada."""
    copia = list(mensagens)
    for i in range(len(copia) - 1, -1, -1):
        mensagem = copia[i]
        if getattr(mensagem, "type", "") == "human":
            copia[i] = mensagem.model_copy(
                update={"content": f"{contexto}\n\n{mensagem.text}"}
            )
            break
    return copia
