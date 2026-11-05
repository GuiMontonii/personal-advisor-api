"""
Verificações de segurança e compliance do assessor financeiro.

ENTRADA  → anonimizar → checar injeção → checar dados internos → classificar (LLM)
SAÍDA    → redigir PII → desanonimizar → revisar compliance (LLM)
"""

import re
import uuid
from app.llms import llm_rapido   


PII = [
    ("CARTAO",   r"\d{4}\s?\d{4}\s?\d{4}\s?\d{4}"),
    ("CNPJ",     r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}"),
    ("CPF",      r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}"),
    ("TELEFONE", r"\(?\d{2}\)?\s?\d{4,5}-?\d{4}"),
    ("EMAIL",    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    ("CONTA",    r"(?<![\w-])\d{4,6}-\d(?![\d-])"),
]


def _bloquear(motivo, mensagem):
    return {"bloqueado": True, "motivo": motivo, "mensagem": mensagem}

def _aprovado():
    return {"bloqueado": False, "motivo": "aprovado", "mensagem": ""}

def _saida_ok(conteudo):
    return {"bloqueado": False, "motivo": "saida_revisada", "conteudo": conteudo}


def anonimizar_entrada(texto):
    mapa = {}

    for tipo, padrao in PII:
        matches = re.findall(padrao, texto)
        for valor in matches:
            token = f"[PII_{tipo}_{uuid.uuid4().hex[:6]}]"
            mapa[token] = valor
            texto = texto.replace(valor, token, 1)

    return texto, mapa

def desanonimizar_saida(texto, mapa, restaurar=False):
    """Resolve tokens de PII na saída. Por padrão omite — não repete dado pessoal."""
    for token, valor in mapa.items():
        if token in texto:
            substituto = valor if restaurar else f"[{token.split('_')[1]} OMITIDO]"
            texto = texto.replace(token, substituto)
    return texto


_PADROES_INJECAO = [
    r"ignore\s+(as\s+)?instru[çc][oõ]es",
    r"ignore\s+previous\s+instructions",
    r"forget\s+your\s+instructions",
    r"you\s+are\s+now\s+",
    r"\bact\s+as\s+(if\s+)?",
    r"pretend\s+(you\s+are|to\s+be)",
    r"jailbreak",
    r"\bdan\s+mode",
    r"modo\s+irrestrito",
    r"system\s*prompt",
    r"<\s*system\s*>",
    r"\[INST\]",
    r"###\s*instruction",
    r"override\s+(your\s+)?instructions",
    r"desconsider[ea]\s+(suas\s+)?instru[çc][oõ]es",
]

_KEYWORDS_DADOS_INTERNOS = [
    "prompt do sistema", "system prompt", "suas instruções", "your instructions",
    "variável de ambiente", "chave de api", "api key", "senha do sistema",
    "token de acesso", "banco de dados interno", "tabela interna",
    "dados de outros clientes", "lista de clientes", "credenciais",
]


_PROMPT_CLASSIFICADOR = """\
Você é um classificador de segurança de um sistema de assessoria financeira e agenda.
Classifique a mensagem em UMA categoria. Responda SOMENTE:

CATEGORIA: [categoria]
JUSTIFICATIVA: [uma linha]

Categorias:
APROVADO        - mensagem legítima sobre finanças (informativa), agenda ou operações
OFENSIVO        - xingamentos, assédio, discurso de ódio
PERIGOSO        - instruções que causam dano físico, psicológico ou coletivo
ILICITO         - pedido de auxílio para atividades ilegais ou fraudulentas
POLITICO        - opiniões ou debates políticos, partidos, eleições
INDICACAO_INVEST - recomendação direta de ativo específico para comprar/vender/manter

Mensagem: {mensagem}
"""

_RESPOSTAS_BLOQUEIO = {
    "OFENSIVO":         ("conteudo_ofensivo",      "Por favor, mantenha um tom respeitoso para que eu possa te ajudar."),
    "PERIGOSO":         ("pedido_perigoso",         "Não posso ajudar com esse tipo de solicitação."),
    "ILICITO":          ("pedido_ilicito",           "Não posso auxiliar com atividades ilegais ou irregulares."),
    "POLITICO":         ("pergunta_politica",        "Não me envolvo em temas políticos. Posso ajudar com finanças ou sua agenda."),
    "INDICACAO_INVEST": ("indicacao_investimento",   "Por regulação, não forneço indicações diretas de ativos. Posso explicar classes de investimento ou agendar uma reunião com seu assessor."),
}

def guardrail_entrada(mensagem_anonimizada):
    """
    Executa as verificações de entrada em ordem de custo crescente:
    determinístico primeiro, LLM só se necessário.
    Retorna dict com bloqueado, motivo e mensagem.
    """
    
    for padrao in _PADROES_INJECAO:
        if re.search(padrao, mensagem_anonimizada, re.IGNORECASE):
            return _bloquear("prompt_injection", "Não consigo processar essa solicitação.")

    
    texto_lower = mensagem_anonimizada.lower()
    for kw in _KEYWORDS_DADOS_INTERNOS:
        if kw in texto_lower:
            return _bloquear("acesso_dados_internos", "Não tenho como compartilhar informações internas do sistema.")

    
    resposta = llm_rapido.invoke(_PROMPT_CLASSIFICADOR.format(mensagem=mensagem_anonimizada)).text

    categoria = None
    for linha in resposta.splitlines():
        if linha.strip().upper().startswith("CATEGORIA:"):
            categoria = linha.split(":", 1)[1].strip().upper()
            break

    if categoria in _RESPOSTAS_BLOQUEIO:
        motivo, mensagem = _RESPOSTAS_BLOQUEIO[categoria]
        return _bloquear(motivo, mensagem)
    if categoria != "APROVADO":
        return _bloquear("classificacao_inconclusiva", "Não consegui validar a mensagem. Tente novamente.")

    return _aprovado()


_PROMPT_COMPLIANCE = """\
Você é o juiz final de segurança e veracidade. Confira se a resposta está
sustentada pela solicitação do usuário e pelos resultados reais das ferramentas.
Não invente registros nem afirme que uma operação falhou se foi preparada.
Corrija afirmações financeiras de rentabilidade garantida, recomendações sem
alerta de risco ou certezas indevidas. Se faltar evidência, recuse.
Responda SOMENTE com o protocolo:
STATUS: APROVADO ou CORRIGIDO
RESPOSTA:
[texto final]

Solicitação original: {pergunta}
Operações preparadas (ainda NÃO confirmadas): {operacoes}
Resposta a avaliar: {resposta}
"""


def guardrail_saida(resposta, mapa_pii, restaurar_pii=False, pergunta="", operacoes=None):
    """Emite veredito explícito; qualquer falha é recusa, nunca commit."""
    for tipo, padrao in PII:
        resposta = re.sub(padrao, f"[{tipo} OMITIDO]", resposta)
    resposta = desanonimizar_saida(resposta, mapa_pii, restaurar=restaurar_pii)
    try:
        saida = llm_rapido.invoke(_PROMPT_COMPLIANCE.format(
            resposta=resposta, pergunta=pergunta, operacoes=operacoes or []
        )).text.strip()
        match = re.search(r"(?im)^STATUS:\s*(APROVADO|CORRIGIDO)\s*$", saida)
        texto = saida.split("RESPOSTA:", 1)[1].strip() if "RESPOSTA:" in saida else ""
        if match and texto:
            aprovado = match.group(1).upper() == "APROVADO"
            print(f"[juiz] {'APROVADO' if aprovado else 'RECUSADO'}")
            
            for tipo, padrao in PII:
                texto = re.sub(padrao, f"[{tipo} OMITIDO]", texto)
            texto = desanonimizar_saida(texto, mapa_pii, restaurar=restaurar_pii)
            return {"conteudo": texto, "aprovado": aprovado}
    except Exception:
        pass
    print("[juiz] INDISPONIVEL")
    return {"conteudo": "Não consegui validar a resposta. Nenhuma alteração foi confirmada.", "aprovado": False}
