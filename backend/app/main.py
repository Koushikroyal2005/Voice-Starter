"""Windows-safe module entrypoint: uv run python -m app.main dev."""

import sys

from livekit.agents import AgentServer, JobContext, cli

from app.agents.demo import DemoAgent
from app.config.settings import ConfigurationError, load_settings
from app.providers.pipeline import create_session


async def voice_session(ctx: JobContext) -> None:
    config = load_settings()
    session = create_session(config)
    await session.start(agent=DemoAgent(config), room=ctx.room)
    await ctx.connect()
    await session.generate_reply(
        instructions="Greet the user briefly and ask what they would like to try."
    )


def create_server() -> AgentServer:
    # download-files and --help must work before credentials are configured.
    download_only = "download-files" in sys.argv or "--help" in sys.argv
    settings = None if download_only else load_settings()
    server = AgentServer(
        **(
            {
                "ws_url": settings.livekit_url,
                "api_key": settings.livekit_api_key,
                "api_secret": settings.livekit_api_secret,
            }
            if settings
            else {}
        )
    )

    # Keep the callback at module scope so Windows multiprocessing can pickle it.
    server.rtc_session(agent_name=settings.agent_name if settings else "")(
        voice_session
    )
    return server


if __name__ == "__main__":
    try:
        cli.run_app(create_server())
    except ConfigurationError as error:
        raise SystemExit(f"Configuration error: {error}") from None
