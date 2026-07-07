"""Prompt templates — instruction/data isolation, persona, glossary, grounding (§6 stage 6)."""

from .templates import (
    SUMMARY_TOOL,
    TRANSLATE_TOOL,
    build_summary_prompt,
    build_translate_segments_prompt,
)

__all__ = [
    "SUMMARY_TOOL",
    "TRANSLATE_TOOL",
    "build_summary_prompt",
    "build_translate_segments_prompt",
]
