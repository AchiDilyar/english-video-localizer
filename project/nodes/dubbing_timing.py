"""Unified source/final-audio/display timing policy; no graph or model calls."""

import math
from dataclasses import dataclass


def forward_windows(segments, duration_ms):
    ordered = sorted(segments, key=lambda item: item.start_ms)
    windows = {}
    for i, segment in enumerate(ordered):
        end = ordered[i + 1].start_ms if i + 1 < len(ordered) else duration_ms
        if not 0 <= segment.start_ms < segment.end_ms <= end <= duration_ms:
            raise ValueError("配音时间窗无效或原始片段重叠，不能向前填充或覆盖下一句。")
        windows[segment.segment_id] = (segment.start_ms, end)
    return windows


@dataclass(frozen=True)
class DubbingPolicy:
    min_speed: float = 1.0
    max_speedup: float = 1.35
    max_forward_delay_ms: int = 0
    repair_rounds: int = 0
    exhaustion: str = "error"

    @classmethod
    def from_plan(cls, plan):
        return cls(
            min_speed=getattr(plan, "min_speed", 1.0),
            max_speedup=plan.max_speedup,
            max_forward_delay_ms=getattr(plan, "max_forward_delay_ms", 0),
            repair_rounds=getattr(plan, "duration_repair_attempts", 0),
            exhaustion=getattr(plan, "duration_exhaustion_policy", "error"),
        )

    def speed_cap(self, group):
        return None if group.get("duration_exhausted") else self.max_speedup

    def continue_after_limit(self):
        return self.exhaustion in {"use_best", "use_latest"}

    def skip_review(self, requests_used):
        return self.exhaustion == "use_latest" and requests_used >= self.repair_rounds


def reserve_end_limits(groups, video_end, policy):
    """Reserve positive time for every following group before spending on TTS."""
    if video_end <= 0 or len(groups) > video_end:
        raise ValueError("DUB_INVALID_TIMELINE: video cannot contain all groups")
    keys = [g["group_id"] for g in groups]
    if len(keys) != len(set(keys)):
        raise ValueError("DUB_INVALID_TIMELINE: duplicate group IDs")
    if any(a["start_ms"] > b["start_ms"] for a, b in zip(groups, groups[1:])):
        raise ValueError("DUB_INVALID_TIMELINE: groups must follow source order")
    limits = {}
    latest = video_end
    for i in range(len(groups) - 1, -1, -1):
        group = groups[i]
        if i + 1 < len(groups):
            latest = min(latest - 1, groups[i + 1]["start_ms"] + policy.max_forward_delay_ms)
        if not 0 <= group["start_ms"] < group["original_end_ms"] or latest <= group["start_ms"]:
            raise ValueError(f"DUB_INVALID_TIMELINE: no positive window for {group['group_id']}")
        limits[group["group_id"]] = latest
    return limits


def schedule_group(group, raw_ms, cursor, video_end, policy, *, end_limit=None):
    if raw_ms <= 0:
        raise ValueError("TTS_EMPTY_AUDIO: 合成音频没有有效时长")
    start = max(group["start_ms"], cursor)
    allowance = policy.max_forward_delay_ms
    if start - group["start_ms"] > allowance:
        raise ValueError(f"DUB_FORWARD_DELAY_LIMIT: {group['group_id']}，前组延迟超过限制")
    deadline = min(video_end, group["available_end_ms"] + allowance)
    if end_limit is not None:
        deadline = min(deadline, end_limit)
    remaining = deadline - start
    if remaining <= 0:
        raise ValueError(f"DUB_FORWARD_DELAY_LIMIT: {group['group_id']}，已无有效配音时间窗")
    if group.get("duration_exhausted"):
        # Prefer its own remaining slot; when an earlier group consumed it,
        # use the pre-reserved deadline instead of inventing a one-ms window.
        end = min(deadline, group["available_end_ms"])
        return start, (end if end > start else deadline) - start
    available = group["available_end_ms"] - start
    window = max(group["original_end_ms"] - group["start_ms"], min(raw_ms, available))
    if allowance:
        window = max(window, math.ceil(raw_ms / min(1.30, policy.max_speedup)))
        if raw_ms <= 700:
            window = max(window, raw_ms)
    window = min(window, remaining)
    if raw_ms > window * policy.max_speedup:
        raise ValueError(f"TTS_TEXT_TOO_LONG: {group['group_id']} 实测{raw_ms}ms，可用{window}ms")
    return start, window


def schedule_segment(group, raw_ms, policy):
    """Legacy per-segment path obeys the same engine, without borrowing next speech."""
    fixed = DubbingPolicy(
        policy.min_speed, policy.max_speedup, 0, policy.repair_rounds, policy.exhaustion
    )
    item = {**group, "available_end_ms": group["start_ms"] + group["available_duration_ms"]}
    return schedule_group(item, raw_ms, group["start_ms"], item["available_end_ms"], fixed)


def member_frame_cuts(group, source, total_frames, sample_rate):
    keys = group["segment_ids"]
    if total_frames < len(keys):
        raise ValueError("TTS_EMPTY_AUDIO: insufficient audio frames for group members")
    span = group["original_end_ms"] - group["start_ms"]
    if span <= 0:
        raise ValueError("配音组原时间范围必须为正")
    scale = min(1.0, total_frames / (span * sample_rate / 1000))
    cuts = [0]
    for i, key in enumerate(keys[1:], 1):
        offset = source[key].start_ms - group["start_ms"]
        proposed = round(offset * sample_rate / 1000 * scale)
        cuts.append(max(cuts[-1] + 1, min(proposed, total_frames - (len(keys) - i))))
    cuts.append(total_frames)
    return cuts, scale


def validate_final_timeline(rows, video_end):
    """Validate final audio bounds, never compare them to original span length."""
    previous = 0
    seen = set()
    for row in rows:
        key = row.get("group_id", row.get("segment_id"))
        start, end = row["start_ms"], row.get("end_ms", row.get("display_end_ms"))
        if key in seen or not 0 <= start < end <= video_end or start < previous:
            raise ValueError(f"DUB_INVALID_FINAL_TIMELINE: {key} overlaps or exceeds video")
        if start < row.get("source_start_ms", start):
            raise ValueError(f"DUB_INVALID_FINAL_TIMELINE: {key} starts before source")
        seen.add(key)
        previous = end


def validate_display_cues(cues, video_end, expected_english=None):
    previous = 0
    for cue in cues:
        if not 0 <= cue["start_ms"] < cue["end_ms"] <= video_end or cue["start_ms"] < previous:
            raise ValueError("SUBTITLE_INVALID_TIMELINE: cue order or final video bounds invalid")
        if not isinstance(cue.get("zh"), str) or not isinstance(cue.get("en"), str):
            raise ValueError("SUBTITLE_INVALID_TEXT: bilingual text is required")
        previous = cue["start_ms"]
    if expected_english is not None:
        if " ".join(c["en"] for c in cues).split() != expected_english.split():
            raise ValueError("SUBTITLE_ENGLISH_COVERAGE: original English changed")
