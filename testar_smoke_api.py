"""Valida endpoints e frontend com Qdrant e MongoDB simulados."""
import os
from unittest.mock import MagicMock, patch

os.environ.update({
    "GOOGLE_API_KEY": "chave-falsa-para-teste",
    "GROQ_API_KEY": "chave-falsa-para-teste",
    "DATABASE_URL": "postgresql://teste:teste@127.0.0.1:5432/teste",
    "MONGODB_URI": "mongodb://127.0.0.1:27017",
    "QDRANT_URL": "http://127.0.0.1:6333",
    "QDRANT_API_KEY": "",
})

with patch("qdrant_client.QdrantClient", MagicMock()), patch("pymongo.MongoClient", MagicMock()):
    from app import config
    from app.main import app
    from fastapi.testclient import TestClient

    assert config.QDRANT_URL == "http://127.0.0.1:6333"
    with TestClient(app) as client:
        resposta = client.get("/health")
        assert resposta.status_code == 200, resposta.status_code
        corpo = resposta.json()
        assert corpo["status"] == "ok", corpo
        assert corpo["problemas_de_configuracao"] == [], corpo

        resposta = client.get("/openapi.json")
        assert resposta.status_code == 200
        caminhos = {
            (metodo.upper(), caminho)
            for caminho, operacoes in resposta.json()["paths"].items()
            for metodo in operacoes
        }
        esperadas = {
            ("POST", "/chat"),
            ("POST", "/perfil"),
            ("POST", "/sessions/{session_id}/iniciar"),
            ("POST", "/sessions/{session_id}/encerrar"),
            ("GET", "/monitor"),
            ("GET", "/health"),
        }
        assert esperadas.issubset(caminhos), sorted(esperadas - caminhos)

        resposta = client.get("/")
        assert resposta.status_code == 200, resposta.status_code
        assert "text/html" in resposta.headers.get("content-type", "")

print("PASSOU: /health, OpenAPI (6 rotas) e frontend; MongoDB/Qdrant simulados")
