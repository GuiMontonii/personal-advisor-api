import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.routes import chat, sessions, perfil, monitor
from app.config import validar_config, FRONTEND_DIR

app = FastAPI(
    title="Assesor IA",
    description="Assessor financeiro e de agenda com LangChain e LangGraph",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[s.strip() for s in os.getenv(
        "CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
    ).split(",") if s.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(perfil.router)
app.include_router(monitor.router)

@app.get("/health")
def health() -> dict:
    problemas = validar_config()
    return {
        "status" : "ok" if not problemas else "atencao",
        "problemas_de_configuracao": problemas,
    }

if (FRONTEND_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/", tags=["infra"])
    def raiz() -> dict:
        return {
            "mensagem": "API do acessor no ar. O frontend ainda não foi criado.",
        }