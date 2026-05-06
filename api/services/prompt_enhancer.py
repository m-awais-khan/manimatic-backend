"""
Prompt Enhancement Service — RAG + Multi-Model Fallback Router

Pipeline:
  1. Embed the user's raw prompt (SentenceTransformers, CPU-only)
  2. Query ChromaDB for the top-5 most semantically similar dataset examples
  3. Build a rich few-shot system prompt using those examples
  4. Call Groq (primary — ultra-fast) → fallback to Gemini on any error

Dependencies:
  pip install chromadb sentence-transformers groq
"""

import os
import logging
import random
from pathlib import Path

# FIX: Prevent Rust tokenizers from crashing in multithreaded environments (like Django)
os.environ["TOKENIZERS_PARALLELISM"] = "false"
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Lazy singletons (loaded once per process) ─────────────────────────────────

_embedder = None
_chroma_collection = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        import torch
        # Prevent PyTorch from spawning too many threads in Django workers (prevents silent crashes)
        torch.set_num_threads(1)
        from sentence_transformers import SentenceTransformer
        logger.info("Loading SentenceTransformer model for prompt enhancement...")
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedder


def _get_collection():
    global _chroma_collection
    if _chroma_collection is None:
        import chromadb
        chroma_dir = Path(__file__).resolve().parent.parent.parent / "chroma_db"
        if not chroma_dir.exists():
            raise FileNotFoundError(
                f"ChromaDB not found at {chroma_dir}. "
                "Run: python manage.py seed_chromadb"
            )
        client = chromadb.PersistentClient(path=str(chroma_dir))
        _chroma_collection = client.get_collection("manim_prompts")
        logger.info(f"ChromaDB collection loaded: {_chroma_collection.count()} prompts.")
    return _chroma_collection


# ── RAG Retrieval ─────────────────────────────────────────────────────────────

def retrieve_similar_examples(raw_prompt: str, n_results: int = 5) -> list[str]:
    """Return the top-N most semantically similar dataset prompts."""
    embedder = _get_embedder()
    collection = _get_collection()

    query_embedding = embedder.encode([raw_prompt]).tolist()
    results = collection.query(query_embeddings=query_embedding, n_results=n_results)

    return results["documents"][0]  # list of instruction strings


# ── LLM Router (Groq → Gemini fallback) ──────────────────────────────────────

ENHANCE_SYSTEM_PROMPT = """You are an expert prompt engineer for a Manim animation AI called Manimatic.
Your ONLY job is to rephrase a user's raw idea into a precise, detailed, and structured animation prompt.

A great Manimatic prompt:
- Specifies WHAT objects to animate (shapes, text, equations, graphs)
- Specifies COLORS explicitly (e.g., "in Blue", "highlighted in Red")
- Describes the ANIMATION sequence step-by-step
- Mentions LABELS, TITLES, and any on-screen text needed
- Is written in English imperative style (e.g., "Animate...", "Display...", "Show...")

Here are examples of PERFECT Manimatic prompts to match the style:
{examples}

Now rephrase the following raw user request into a perfect Manimatic prompt.
IMPORTANT: Output ONLY the enhanced prompt text. No explanations, no code, no extra commentary.

Raw request: {raw_prompt}"""


def _call_groq(system_prompt: str) -> str:
    """Call Groq API (llama-3.3-70b-versatile) — primary, ultra-fast."""
    from groq import Groq, RateLimitError

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set in environment.")

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": system_prompt}],
        max_tokens=350,
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


def _call_gemini(system_prompt: str) -> str:
    """Call Gemini 2.5 Flash — fallback."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage

    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
        config={"timeout": 30},
    )
    response = llm.invoke([HumanMessage(content=system_prompt)])
    return response.content.strip()


def enhance_prompt(raw_prompt: str) -> str:
    """
    Full pipeline:
      1. Retrieve semantically similar examples from ChromaDB
      2. Build the few-shot system prompt
      3. Route through Groq → Gemini fallback
    Returns the enhanced prompt string.
    """
    # Step 1: RAG retrieval
    try:
        examples = retrieve_similar_examples(raw_prompt, n_results=5)
        formatted_examples = "\n".join(
            f"{i+1}. {ex}" for i, ex in enumerate(examples)
        )
        logger.info(f"RAG: Retrieved {len(examples)} similar examples for prompt enhancement.")
    except Exception as e:
        logger.warning(f"RAG retrieval failed ({e}). Falling back to no examples.")
        formatted_examples = "(No examples available)"

    # Step 2: Build system prompt
    full_prompt = ENHANCE_SYSTEM_PROMPT.format(
        examples=formatted_examples,
        raw_prompt=raw_prompt,
    )

    # Step 3: Call Groq → Gemini fallback
    try:
        logger.info("Prompt enhancement: trying Groq (primary)...")
        result = _call_groq(full_prompt)
        logger.info("Prompt enhancement: Groq succeeded.")
        return result
    except Exception as groq_err:
        logger.warning(f"Groq failed ({groq_err}). Falling back to Gemini...")
        try:
            result = _call_gemini(full_prompt)
            logger.info("Prompt enhancement: Gemini fallback succeeded.")
            return result
        except Exception as gemini_err:
            logger.error(f"Both Groq and Gemini failed for prompt enhancement. Groq: {groq_err} | Gemini: {gemini_err}")
            raise RuntimeError("All enhancement models are currently unavailable. Please try again shortly.")
