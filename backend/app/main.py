"""Windows-safe module entrypoint: uv run python -m app.main dev."""

import logging
import sys

from livekit.agents import AgentServer, JobContext, cli, room_io

from app.agents.orchestrator import MainAgent
from app.bootstrap import build_orchestrator
from app.config.settings import ConfigurationError, load_settings
from app.providers.pipeline import create_session
from app.providers.registry import ProviderError
from app.services.workbench import install_workbench

logger = logging.getLogger("voice-starter")


async def voice_session(ctx: JobContext) -> None:
    config = load_settings()
    logger.info("Voice job received", extra={"room": ctx.room.name})
    session = create_session(config)
    orchestrator = build_orchestrator(config)

    @session.on("close")
    def on_session_close(_event):
        logger.info("Voice session closed", extra={"room": ctx.room.name})
        ctx.shutdown(reason="voice_session_closed")

    await session.start(
        agent=MainAgent(config, orchestrator),
        room=ctx.room,
        room_options=room_io.RoomOptions(close_on_disconnect=True),
    )
    await ctx.connect()
    await install_workbench(ctx, session, config.stt.language, orchestrator)
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
    except (ConfigurationError, ProviderError) as error:
        raise SystemExit(f"Configuration error: {error}") from None
