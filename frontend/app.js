const API_BASE = window.location.protocol === "file:" ? "http://localhost:8000" : window.location.origin;
const SESSION_STORAGE_KEY = "assistente_session_id";
let enviando = false;

const composer = document.getElementById("composer");
const perguntaInput = document.getElementById("pergunta");
const enviarButton = document.getElementById("enviar");
const thread = document.getElementById("thread");
const threadEmpty = document.getElementById("thread-empty");
const hint = document.getElementById("hint");
const resetButton = document.getElementById("reset-session");
const sessionIdElement = document.getElementById("session-id");
const statusDot = document.getElementById("status-dot");

function gerarSessionId() {
    if (crypto.randomUUID) {
        return crypto.randomUUID();
    }

    return "sessao-" + Date.now();
}

let sessionId = localStorage.getItem(SESSION_STORAGE_KEY);

if (!sessionId) {
    sessionId = gerarSessionId();
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
}

if (sessionIdElement) {
    sessionIdElement.textContent = sessionId;
}

function formatarTexto(texto) {
    return texto
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/\*\*(\S(?:.*?\S)?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(\S(?:.*?\S)?)\*/g, "<strong>$1</strong>")
        .replace(/^- /gm, "• ")
        .replace(/\n{3,}/g, "\n\n")
        .trim();
}

function adicionarMensagem(texto, tipo) {
    if (threadEmpty) {
        threadEmpty.style.display = "none";
    }

    const mensagem = document.createElement("div");

    mensagem.classList.add("message");
    mensagem.classList.add(`message--${tipo}`);
    
    const bolha = document.createElement("div");
    bolha.classList.add("message__bubble");

    if (tipo === "assistant") {
        bolha.innerHTML = formatarTexto(texto);
    } else {
        bolha.textContent = texto;
    }

    mensagem.appendChild(bolha);

    thread.appendChild(mensagem);
    thread.scrollTop = thread.scrollHeight;

    return mensagem;
}

function setHint(texto) {
    if (hint) {
        hint.textContent = texto;
    }
}

function setStatus(online) {
    if (statusDot) {
        statusDot.classList.toggle("status--offline", !online);
    }
}

async function enviarPergunta(pergunta) {
    try {
        enviando = true;
        enviarButton.disabled = true;
        resetButton.disabled = true;
        perguntaInput.disabled = true;

        setHint("Pensando...");

        const response = await fetch(`${API_BASE}/chat`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                session_id: sessionId,
                pergunta: pergunta
            })
        });

        if (!response.ok) {
            const erro = await response.json().catch(() => ({}));
            throw new Error(typeof erro.detail === "string" ? erro.detail : `Erro ${response.status}`);
        }

        const data = await response.json();

        console.log("Resposta:", data);

        adicionarMensagem(
            data.resposta || data.response || data.message || "Não recebi uma resposta.",
            "assistant"
        );

        setHint("Pronto.");
        setStatus(true);

    } catch (error) {
        console.error("Erro:", error);

        adicionarMensagem(
            "Erro ao enviar a pergunta: " + error.message,
            "error"
        );

        setHint("Erro ao conectar com a API.");
        setStatus(false);

    } finally {
        enviando = false;
        enviarButton.disabled = false;
        resetButton.disabled = false;
        perguntaInput.disabled = false;
        perguntaInput.focus();
    }
}

composer.addEventListener("submit", async (event) => {
    event.preventDefault();

    const pergunta = perguntaInput.value.trim();

    if (!pergunta) {
        return;
    }

    adicionarMensagem(pergunta, "user");

    perguntaInput.value = "";

    await enviarPergunta(pergunta);
});

perguntaInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        composer.requestSubmit();
    }
});

async function encerrarSessaoAtual(id) {
    try {
        const response = await fetch(
            `${API_BASE}/sessions/${encodeURIComponent(id)}/encerrar`,
            {
                method: "POST"
            }
        );

        if (!response.ok) {
            throw new Error("Não foi possível encerrar a sessão.");
        }

        const data = await response.json();

        return data.resumo;

    } catch (error) {
        console.error("Erro ao encerrar sessão:", error);
        throw error;
    }
}

async function iniciarNovaSessao() {
    if (enviando || resetButton.disabled) return;
    resetButton.disabled = true;
    try {
        await encerrarSessaoAtual(sessionId);
    } catch (error) {
        setHint("Não foi possível finalizar a conversa. Tente novamente.");
        resetButton.disabled = false;
        return;
    }

    sessionId = gerarSessionId();

    localStorage.setItem(
        SESSION_STORAGE_KEY,
        sessionId
    );

    if (sessionIdElement) {
        sessionIdElement.textContent = sessionId;
    }

    thread.innerHTML = "";

    if (threadEmpty) {
        thread.appendChild(threadEmpty);
        threadEmpty.style.display = "block";
    }

    setHint("Nova sessão iniciada.");

    resetButton.disabled = false;

    perguntaInput.focus();
}

resetButton.addEventListener(
    "click",
    iniciarNovaSessao
);

async function verificarAPI() {
    try {
        const response = await fetch(`${API_BASE}/health`);

        if (!response.ok) {
            throw new Error("API indisponível");
        }

        const dados = await response.json();
        const pronto = dados.status === "ok";
        setStatus(pronto);
        setHint(pronto ? "Assistente pronto." : "Verifique a configuração da API.");

    } catch (error) {
        console.error("API:", error);

        setStatus(false);
        setHint("API indisponível.");
    }
}

verificarAPI();