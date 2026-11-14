"""Scores only observed values. Null means not measured/reviewed, never zero."""

import unicodedata


def distance(reference, observed):
    row = list(range(len(observed) + 1))
    for i, token in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(observed, 1):
            current.append(
                min(current[-1] + 1, row[j] + 1, row[j - 1] + (token != other))
            )
        row = current
    return row[-1]


def transcription_scores(reference, observed):
    ref = unicodedata.normalize("NFC", reference).casefold()
    hyp = unicodedata.normalize("NFC", observed).casefold()
    return {
        "word_error_rate": distance(ref.split(), hyp.split()) / len(ref.split())
        if ref.split()
        else None,
        "character_error_rate": distance(ref, hyp) / len(ref) if ref else None,
    }


def summarize(events, *, reference=None, transcript=None, review=None):
    review = review or {}
    tools = [event for event in events if event["stage"] == "tool_execution"]

    def values(stage):
        return [
            event["duration"]
            for event in events
            if event["stage"] == stage and event.get("duration") is not None
        ]

    return {
        "transcription": transcription_scores(reference, transcript)
        if reference is not None and transcript is not None
        else None,
        "intent_accuracy": review.get("intent_correct")
        if type(review.get("intent_correct")) is bool
        else None,
        "task_completion": review.get("task_completed")
        if type(review.get("task_completed")) is bool
        else None,
        "tool_success_rate": sum(t["status"] == "completed" for t in tools) / len(tools)
        if tools
        else None,
        "first_audio_seconds": values("response_first_audio"),
        "full_turn_seconds": values("full_turn"),
        "interruption_seconds": values("interruption_stop"),
    }
