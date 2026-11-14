"""Native LiveKit LLMs retain streamed chunks, tool calls and metrics."""

from livekit.agents.llm import LLM

from app.config.settings import ProviderConfig


def openai_compatible(config: ProviderConfig) -> LLM:
    from livekit.plugins import openai

    return openai.LLM(
        api_key=config.api_key, model=config.model, base_url=config.base_url
    )


def gemini(config: ProviderConfig) -> LLM:
    from livekit.plugins import google

    return google.LLM(api_key=config.api_key, model=config.model, vertexai=False)
