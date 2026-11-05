"""Publica um commit no Render e confirma a nova versao pela API de deploys."""
import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


FALHAS = {"build_failed", "update_failed", "pre_deploy_failed", "canceled", "deactivated"}


class DeployError(RuntimeError):
    pass


def requisitar_json(url: str, method: str = "GET", headers: dict | None = None) -> tuple[int, dict]:
    requisicao = Request(url, method=method, headers=headers or {})
    try:
        with urlopen(requisicao, timeout=30) as resposta:
            status = resposta.status
            dados = resposta.read().decode("utf-8")
    except HTTPError as erro:
        raise DeployError(f"Requisicao HTTP falhou com codigo {erro.code}.") from None
    except (URLError, TimeoutError) as erro:
        raise DeployError(f"Nao foi possivel concluir a requisicao: {type(erro).__name__}.") from None
    if status == 202 and not dados.strip():
        return status, {}
    try:
        return status, json.loads(dados)
    except (ValueError, TypeError):
        raise DeployError("Servico retornou resposta que nao e JSON valido.") from None


def url_hook_com_commit(hook: str, sha: str) -> str:
    partes = urlsplit(hook)
    if partes.scheme != "https" or not partes.netloc:
        raise DeployError("A URL do Deploy Hook deve ser HTTPS.")
    if partes.fragment:
        raise DeployError("A URL do Deploy Hook nao pode conter fragmentos.")
    query = partes.query + ("&" if partes.query else "") + "ref=" + quote(sha)
    return urlunsplit((partes.scheme, partes.netloc, partes.path, query, ""))


def criar_deploy(hook: str, sha: str) -> str:
    status, resposta = requisitar_json(url_hook_com_commit(hook, sha), method="POST")
    if status == 202:
        raise DeployError("Render enfileirou o deploy sem identificador (HTTP 202). Verifique a politica de deploys simultaneos.")
    if status != 200:
        raise DeployError(f"Render respondeu HTTP {status} ao iniciar o deploy.")
    identificador = resposta.get("deploy", {}).get("id")
    if not identificador or not re.fullmatch(r"dep-[A-Za-z0-9-]+", identificador):
        raise DeployError("O Render nao retornou um ID de deploy valido.")
    print(f"Deploy criado: {identificador}", flush=True)
    return identificador


def consultar_deploy(service_id: str, deploy_id: str, api_key: str) -> dict:
    url = f"https://api.render.com/v1/services/{quote(service_id)}/deploys/{quote(deploy_id)}"
    status, dados = requisitar_json(url, headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
    if status != 200 or not isinstance(dados, dict):
        raise DeployError("Resposta invalida ao consultar o status do deploy.")
    return dados


def aguardar_deploy(service_id: str, deploy_id: str, api_key: str, sha: str, limite: int, intervalo: int) -> None:
    prazo = time.monotonic() + limite
    while True:
        dados = consultar_deploy(service_id, deploy_id, api_key)
        situacao = dados.get("status", "desconhecido")
        print(f"Deploy {deploy_id}: {situacao}", flush=True)
        if situacao in FALHAS:
            raise DeployError(f"Deploy encerrado sem sucesso: {situacao}.")
        if situacao == "live":
            commit = (dados.get("commit") or {}).get("id")
            if not commit or commit.lower() != sha.lower():
                raise DeployError(f"Deploy ficou live, mas o commit publicado nao corresponde ao SHA esperado ({sha[:12]}).")
            print(f"Commit validado no Render: {sha}", flush=True)
            return
        if time.monotonic() >= prazo:
            raise DeployError("Tempo limite de espera pelo deploy excedido.")
        time.sleep(intervalo)


def verificar_saude(app_url: str, limite: int = 180, intervalo: int = 10) -> None:
    partes = urlsplit(app_url)
    if partes.scheme != "https" or not partes.netloc or partes.query or partes.fragment:
        raise DeployError("APP_URL deve conter a origem HTTPS publica do servico, sem query ou fragmento.")
    url = app_url.rstrip("/") + "/health"
    prazo = time.monotonic() + limite
    while True:
        try:
            status, dados = requisitar_json(url)
            if status == 200 and dados.get("status") == "ok" and not dados.get("problemas_de_configuracao"):
                print("GET /health -> HTTP 200, status ok, sem problemas de configuracao", flush=True)
                return
            print(f"/health ainda nao esta pronto: HTTP {status}, status={dados.get('status')}", flush=True)
        except DeployError:
            print("/health ainda indisponivel", flush=True)
        if time.monotonic() >= prazo:
            raise DeployError("/health nao confirmou uma aplicacao corretamente configurada.")
        time.sleep(intervalo)


def executar() -> None:
    nomes = ("RENDER_DEPLOY_HOOK_URL", "RENDER_API_KEY", "RENDER_SERVICE_ID", "APP_URL", "EXPECTED_COMMIT_SHA")
    ausentes = [nome for nome in nomes if not os.environ.get(nome)]
    if ausentes:
        raise DeployError("Faltam Secrets/Variables no GitHub: " + ", ".join(ausentes))
    valores = {nome: os.environ[nome] for nome in nomes}
    sha = valores["EXPECTED_COMMIT_SHA"]
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise DeployError("EXPECTED_COMMIT_SHA deve ter 40 caracteres hexadecimais.")
    try:
        limite = int(os.environ.get("DEPLOY_TIMEOUT_SECONDS", "1200"))
        intervalo = int(os.environ.get("DEPLOY_POLL_SECONDS", "15"))
    except ValueError:
        raise DeployError("Os limites de tempo devem ser numeros inteiros.") from None
    if limite < 1 or intervalo < 1:
        raise DeployError("Os limites de tempo devem ser positivos.")

    deploy_id = criar_deploy(valores["RENDER_DEPLOY_HOOK_URL"], sha)
    aguardar_deploy(valores["RENDER_SERVICE_ID"], deploy_id, valores["RENDER_API_KEY"], sha, limite, intervalo)
    verificar_saude(valores["APP_URL"])
    print("CD concluido: commit esperado publicado e /health saudavel", flush=True)


if __name__ == "__main__":
    try:
        executar()
    except DeployError as erro:
        print(f"::error::{erro}", file=sys.stderr)
        sys.exit(1)
