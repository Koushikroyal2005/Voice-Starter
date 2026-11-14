from datetime import UTC, datetime, timedelta, timezone

from pydantic import Field

from app.tools.base import ExecutionContext, Schema, ToolDefinition


class TimeInput(Schema):
    utc_offset_minutes: int = Field(
        default=0, ge=-720, le=840, description="UTC offset in minutes; use 0 for UTC."
    )


class TimeOutput(Schema):
    iso_time: str
    utc_offset_minutes: int


async def current_time(args: TimeInput, _context: ExecutionContext) -> TimeOutput:
    zone = timezone(timedelta(minutes=args.utc_offset_minutes))
    return TimeOutput(
        iso_time=datetime.now(UTC).astimezone(zone).isoformat(),
        utc_offset_minutes=args.utc_offset_minutes,
    )


TIME_TOOL = ToolDefinition(
    name="get_current_time",
    title="Check current time",
    description="Get the real current time, optionally at a specified UTC offset.",
    input_schema=TimeInput,
    output_schema=TimeOutput,
    handler=current_time,
    public_result=lambda result: result.iso_time,
)
