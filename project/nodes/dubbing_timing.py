"""Shared display/dubbing windows: fixed starts, forward-only extension."""


def forward_windows(segments, duration_ms):
    ordered = sorted(segments, key=lambda item: item.start_ms)
    windows = {}
    for i, segment in enumerate(ordered):
        end = ordered[i+1].start_ms if i+1 < len(ordered) else duration_ms
        if not 0 <= segment.start_ms < segment.end_ms <= end <= duration_ms:
            raise ValueError('配音时间窗无效或原始片段重叠，不能向前填充或覆盖下一句。')
        windows[segment.segment_id] = (segment.start_ms, end)
    return windows
