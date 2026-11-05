from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from app.config import GEMINI_API_KEY, GROQ_API_KEY


llm_gemini = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.7,
    top_p=0.95,
    api_key=GEMINI_API_KEY,
    thinking_budget=0,
    max_retries=2,       
    timeout=30,
)

llm_groq = ChatGroq(
    model="llama-3.3-70b-versatile", 
    temperature=0.7,
    api_key=GROQ_API_KEY,
)

llm_especialista = llm_gemini.with_fallbacks([llm_groq])


llm_rapido = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",
    temperature=0.0,
    api_key=GEMINI_API_KEY,
    max_retries=2,
    timeout=30,
)

MODELOS = [llm_gemini, llm_groq, llm_especialista, llm_rapido]