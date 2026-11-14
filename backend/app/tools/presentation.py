"""Opt-in public formatting only; never execute, authorize or retry an operation."""

import json
import logging

from pydantic import BaseModel

from app.tools.base import ToolDefinition

logger = logging.getLogger("voice-starter.tools")


def present_result(
    definition: ToolDefinition,
    validated_output: BaseModel,
    call_id: str,
    approved_cards: frozenset[str],
) -> dict | None:
    """Return reviewed public fields, or omit presentation without changing outcome.

    Retain the existing ASCII-escaped JSON budget and formatter opt-in semantics.
    This dictionary is validated against shared v1 schemas at the workbench
    boundary; no parallel result-event schema or transport delivery lives here.
    """
    if not definition.public_result:
        return None
    try:
        event = {
            "type": "result",
            "id": call_id,
            "title": definition.title,
            "text": definition.public_result(validated_output)[:4000],
        }
        if definition.public_card:
            card = definition.public_card(validated_output)
            if card.card_type not in approved_cards:
                raise ValueError("Unapproved public card type")
            event.update(card.model_dump(mode="json"))
        if len(json.dumps(event, allow_nan=False).encode()) > 12000:
            raise ValueError("Public result is too large")
        return event
    except Exception:
        # Never log private output, formatter exceptions or an exception traceback.
        logger.warning("Tool public result unavailable")
        return None
