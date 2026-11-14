from pydantic import Field

from app.tools.base import ExecutionContext, Schema, ToolDefinition, ToolFailure
from app.tools.common.calculator import CalculateInput
from app.tools.common.time import TimeOutput


class WorkflowInput(CalculateInput):
    utc_offset_minutes: int = Field(default=0, ge=-720, le=840)


class WorkflowOutput(Schema):
    checked_at: str
    value: float


class TimeCalculationWorkflow:
    async def run(
        self, args: WorkflowInput, context: ExecutionContext
    ) -> WorkflowOutput:
        time = await context.run_tool(
            "get_current_time",
            {"utc_offset_minutes": args.utc_offset_minutes},
            call_id=f"{context.call_id}:time",
        )
        if time.status != "completed":
            raise ToolFailure(
                "workflow_step_failed",
                "The time check failed; calculation was not started.",
            )
        calculation = await context.run_tool(
            "calculate_expression",
            {"expression": args.expression},
            call_id=f"{context.call_id}:calculate",
        )
        if calculation.status != "completed":
            raise ToolFailure("workflow_step_failed", "The calculation step failed.")
        return WorkflowOutput(
            checked_at=TimeOutput.model_validate(time.data).iso_time,
            value=calculation.data["value"],
        )


WORKFLOW_TOOL = ToolDefinition(
    name="time_and_calculate",
    title="Time-stamped calculation",
    description="Check the current time, then calculate an arithmetic expression. "
    "Both child tools must be allowed.",
    input_schema=WorkflowInput,
    output_schema=WorkflowOutput,
    handler=TimeCalculationWorkflow().run,
    public_result=lambda result: f"{result.value} · checked at {result.checked_at}",
)
