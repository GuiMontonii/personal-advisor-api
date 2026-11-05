from fastapi import APIRouter

from app.perfil import salvar_perfil
from app.schemas import PerfilRequest, PerfilResponse

router = APIRouter(tags=["perfil"])


@router.post("/perfil", response_model=PerfilResponse)
def criar_ou_atualizar_perfil(requisicao: PerfilRequest) -> PerfilResponse:
    """Cria ou atualiza o perfil financeiro enviado pela tela Perfil."""
    perfil = salvar_perfil(
        user_id=requisicao.user_id,
        renda_mensal=requisicao.renda_mensal,
        objetivo=requisicao.objetivo,
        tolerancia_risco=requisicao.tolerancia_risco,
        preferencias=requisicao.preferencias,
    )
    return PerfilResponse(**perfil)
