"""Export settings shared by subtitle preparation and video composition."""

from pydantic import BaseModel, ConfigDict, field_validator
from subtitle_templates import RESOLUTIONS, reference_height
from utils.config import load_config

RESOLUTION_LABELS = {"source": "原始分辨率", **{f"{n}p": f"{n}p" for n in RESOLUTIONS}}
BITRATE_LABELS = {"source": "源视频码率", "low": "低", "standard": "标准", "high": "高"}

# Target video bitrate in kbps for each output resolution tier.
BITRATE_KBPS = {
    480: (800, 1500, 2500),
    720: (1500, 3000, 5000),
    1080: (3000, 6000, 10000),
    1440: (5000, 10000, 16000),
    2160: (10000, 20000, 35000),
}


class ComposeOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: str = "source"
    bitrate: str = "source"

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, value: str) -> str:
        if value not in RESOLUTION_LABELS:
            raise ValueError("不支持的输出分辨率")
        return value

    @field_validator("bitrate")
    @classmethod
    def validate_bitrate(cls, value: str) -> str:
        if value not in BITRATE_LABELS:
            raise ValueError("不支持的视频码率档位")
        return value

    def output_size(self, width: int, height: int) -> tuple[int, int]:
        if self.resolution == "source":
            return width, height
        output_height = int(self.resolution.removesuffix("p"))
        output_width = max(2, 2 * round(width * output_height / (2 * height)))
        return output_width, output_height

    def target_bitrate(self, output_height: int, source_bitrate: int) -> int:
        if self.bitrate == "source":
            return source_bitrate
        index = ("low", "standard", "high").index(self.bitrate)
        return BITRATE_KBPS[reference_height(output_height)][index] * 1000


def load_compose_options() -> ComposeOptions:
    return ComposeOptions.model_validate(load_config("compose_video.toml"))
