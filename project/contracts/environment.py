"""Optional incremental receipts; media bytes and fixed paths stay outside state."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class EnvironmentAudio(BaseModel):
    """B environment publication, bound to the current source and segment timeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_sha256: SHA256
    segments_sha256: SHA256
    environment_sha256: SHA256
    duration_sec: float = Field(gt=0, allow_inf_nan=False)
    restored_intervals_ms: list[tuple[int, int]] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_intervals(self):
        if any(
            not 0 <= start < end <= round(self.duration_sec * 1000)
            for start, end in self.restored_intervals_ms
        ):
            raise ValueError(
                "Restored intervals must be positive millisecond spans within the video"
            )
        return self


class MixedAudio(BaseModel):
    """E mix publication, bound to the current source, environment and Chinese dub."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_sha256: SHA256
    environment_sha256: SHA256
    dub_sha256: SHA256
    mixed_sha256: SHA256
    duration_sec: float = Field(gt=0, allow_inf_nan=False)
