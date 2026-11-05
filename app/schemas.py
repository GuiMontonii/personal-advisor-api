from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    """O que o navegador envia no POST /chat."""

    session_id: str = Field(
        ...,
        min_length=1, max_length=128,
        description="Identifica a conversa (UUID gerado pelo front a cada sessão).",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )

    user_id: str = Field(
        default="usuario_teste",
        min_length=1, max_length=128,
        description="Identifica o usuário de forma estável entre sessões. "
                    "É o que permite a memória de longo prazo funcionar.",
        examples=["usuario_teste"],
    )
    
    pergunta: str = Field(
        ...,
        min_length=1,
        description="A mensagem do usuário — o que antes vinha do input().",
        examples=["gastei 50 reais no mercado hoje"],
    )

class ChatResponse(BaseModel):
    """O que a API devolve no POST /chat."""
    resposta:         str
    agentes_chamados: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    """Ainda não é usado — é do Passo 6 da Etapa 3."""
    session_id: str
    resumo:     str | None = None  

class PerfilRequest(BaseModel):
    """Contrato recebido pela tela Perfil."""
    user_id: str = Field(..., min_length=1, max_length=128)
    renda_mensal: float = Field(..., gt=0, allow_inf_nan=False)
    objetivo: str = Field(..., min_length=1)
    tolerancia_risco: str = Field(..., pattern="^(baixa|media|alta)$")
    preferencias: str = Field(..., min_length=1)


class PerfilResponse(BaseModel):
    """Perfil devolvido após o salvamento."""
    user_id: str
    renda_mensal: float
    objetivo: str
    tolerancia_risco: str
    preferencias: str  