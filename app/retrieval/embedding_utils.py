"""Embedding configuration for the OpenAI-compatible Ollama endpoint."""

import os

from langchain_openai import OpenAIEmbeddings


def create_embeddings() -> OpenAIEmbeddings:
    """Create embeddings through the endpoint configured in .env."""
    base_url = os.getenv("OLLAMA_EMBED_BASE_URL")
    model = os.getenv("EMBEDDING_MODEL")
    if not base_url or not model:
        raise RuntimeError(
            "Set OLLAMA_EMBED_BASE_URL and EMBEDDING_MODEL before indexing or searching."
        )

    return OpenAIEmbeddings(
        model=model,
        base_url=base_url,
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
        check_embedding_ctx_length=False,
    )
