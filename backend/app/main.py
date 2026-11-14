"""Windows-safe module entrypoint: uv run python -m app.main dev."""

import logging
import sys

from livekit.agents import AgentServer, JobContext, cli, room_io

from app.agents.orchestrator import MainAgent
from app.bootstrap import build_orchestrator
from app.config.settings import ConfigurationError, load_settings
from app.observability.session import install_observability
from app.providers.pipeline import create_session
from app.providers.registry import ProviderError
from app.services.infrastructure import install_infrastructure
from app.services.workbench import install_workbench

logger = logging.getLogger("voice-starter")


async def voice_session(ctx: JobContext) -> None:
    config = load_settings()
    session = create_session(config)
    orchestrator = build_orchestrator(config)
    install_observability(ctx, session, orchestrator, config)
    logger.info("Voice job received")

    @session.on("close")
    def on_session_close(_event):
        logger.info("Voice session closed")
        ctx.shutdown(reason="voice_session_closed")

    agent = MainAgent(config, orchestrator)
    await session.start(
        agent=agent,
        room=ctx.room,
        room_options=room_io.RoomOptions(close_on_disconnect=True),
        record=False,  # No implicit cloud audio/transcript recording for telemetry.
    )
    await ctx.connect()
    await install_infrastructure(ctx, session, orchestrator, config)
    try:
        await install_workbench(ctx, session, config.stt.language, orchestrator)
    except BaseException:
        if orchestrator.close_infrastructure:
            await orchestrator.close_infrastructure()
        raise
    if orchestrator.external_tools:
        orchestrator.external_tools.start(agent)
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
