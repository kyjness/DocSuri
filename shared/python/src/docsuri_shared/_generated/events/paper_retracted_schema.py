# DO NOT EDIT. Generated from the JSON Schema SSOT in shared/ by tools/generate.py.
# Change the schema and regenerate (§5-B); never hand-edit.

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class PaperRetractedEvent(BaseModel):
    """
    Paper retraction signal. Producer: U1.VectorIndexWriter when a retraction tombstone is generated. Consumer: U4.LibraryService marks matching saved library metadata as retracted without deleting user data. Delivery: at-least-once; consumer is idempotent by paperId. Trace: shared/events.md §1c, BR-L5.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    paperId: str = Field(
        ...,
        description='Retracted paper identifier. Accepts the canonical paper id used by corpus/index records, including arXiv IDs with or without a version suffix.',
    )
    timestamp: AwareDatetime = Field(
        ..., description='Time the retraction signal was produced.'
    )
