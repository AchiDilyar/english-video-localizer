"""Fit semantic ranges to subtitle cues while word alignment is still in memory."""
import math
import re
from bisect import bisect_right

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import milliseconds


class SubtitlePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    target_min_chars: int = Field(default=35, ge=1, le=512)
    max_chars: int = Field(default=42, ge=1, le=512)
    min_duration_sec: float = Field(default=2.0, gt=0)
    max_duration_sec: float = Field(default=4.0, gt=0)
    max_cps: float = Field(default=20.0, gt=0)

    @model_validator(mode="after")
    def ordered_limits(self):
        if self.target_min_chars > self.max_chars:
            raise ValueError("target_min_chars must not exceed max_chars")
        if self.min_duration_sec > self.max_duration_sec:
            raise ValueError("min_duration_sec must not exceed max_duration_sec")
        return self


def cue_issues(text, start_ms, end_ms, policy):
    issues = []
    if len(text) > policy.max_chars:
        issues.append("subtitle_char_limit_exceeded")
    if end_ms - start_ms > policy.max_duration_sec * 1000:
        issues.append("subtitle_duration_limit_exceeded")
    if end_ms > start_ms and len(text) * 1000 / (end_ms - start_ms) > policy.max_cps:
        issues.append("subtitle_reading_speed_high")
    return issues


def _boundary_costs(tokens, nlp):
    """Soft language preferences; a layout limit may require a less natural cut."""
    text = " ".join(tokens)
    starts = []
    position = 0
    for token in tokens:
        starts.append(position)
        position += len(token) + 1
    doc = nlp(text)
    first_token = {}
    last_token = {}
    for token in doc:
        if token.is_space:
            continue
        index = bisect_right(starts, token.idx) - 1
        first_token.setdefault(index, token)
        last_token[index] = token
    costs = {}
    for i in range(1, len(tokens)):
        left = tokens[i - 1]
        right = tokens[i]
        previous = last_token.get(i - 1)
        following = first_token.get(i)
        cost = 1.8
        if re.search(r"[.!?;:][\"'”’)]*$", left):
            cost = 0.0
        elif re.search(r",[\"'”’)]*$", left):
            cost = 0.25
        elif following is not None and following.pos_ in {"CCONJ", "SCONJ"}:
            cost = 0.45
        if previous is not None and previous.pos_ in {"DET", "ADP", "AUX", "CCONJ", "SCONJ"}:
            cost += 5.0
        if previous is not None and (previous.dep_ in {"poss", "compound"} or previous.tag_ == "PRP$"):
            cost += 7.0
        if left.lower().rstrip(",;:") in {"not", "n't", "no", "to"}:
            cost += 5.0
        if previous is not None and following is not None:
            if previous.pos_ == following.pos_ == "PROPN":
                cost += 7.0
            if previous.pos_ == "ADJ" and following.pos_ in {"NOUN", "PROPN"}:
                cost += 3.0
            if following.dep_ in {"case", "punct"}:
                cost += 2.0
        costs[i] = cost
    return costs


def fit_subtitle_ranges(ranges, words, nlp, policy):
    """DP over nonoverlapping aligned word groups, preserving every token exactly once.

    Long words or overlapping word clusters are indivisible. Their exceptions are
    surfaced, never solved by cutting characters or inventing proportional times.
    """
    fitted = []
    split_sources = 0
    for source in ranges:
        aligned = words[source["first"]:source["last"] + 1]
        tokens = source["text"].split()
        if len(tokens) != len(aligned):
            tokens = [w["word"].strip() for w in aligned]
        starts = [milliseconds(w["start"]) for w in aligned]
        ends = [milliseconds(w["end"]) for w in aligned]
        full_text = " ".join(tokens)
        if len(full_text) <= policy.max_chars and max(ends) - min(starts) <= policy.max_duration_sec * 1000:
            fitted.append({**source, "text": full_text})
            continue
        prefix_end = []
        high = -math.inf
        for end in ends:
            high = max(high, end)
            prefix_end.append(high)
        suffix_start = [0] * len(starts)
        low = math.inf
        for i in range(len(starts) - 1, -1, -1):
            low = min(low, starts[i])
            suffix_start[i] = low
        boundaries = [0] + [i for i in range(1, len(tokens))
                            if prefix_end[i - 1] <= suffix_start[i]] + [len(tokens)]
        costs = _boundary_costs(tokens, nlp)
        lengths = [0]
        for token in tokens:
            lengths.append(lengths[-1] + len(token) + 1)
        count = len(boundaries) - 1
        best = [math.inf] * (count + 1)
        next_cut = [None] * count
        best[count] = 0.0
        for a in range(count - 1, -1, -1):
            first = boundaries[a]
            begin = math.inf
            end = -math.inf
            for b in range(a + 1, count + 1):
                last = boundaries[b]
                previous = boundaries[b - 1]
                begin = min(begin, *starts[previous:last])
                end = max(end, *ends[previous:last])
                chars = lengths[last] - lengths[first] - 1
                duration = (end - begin) / 1000
                over = chars > policy.max_chars or duration > policy.max_duration_sec
                if over and b > a + 1:
                    break
                # A zero-duration atomic group remains untimed for the existing audit.
                cps = chars / duration if duration > 0 else policy.max_cps
                cost = 2.0 + 1.4 * (max(0, policy.target_min_chars - chars) / policy.target_min_chars) ** 2
                cost += 0.9 * (max(0, policy.min_duration_sec - duration) / policy.min_duration_sec) ** 2
                cost += 0.15 * min(9.0, (max(0, cps - policy.max_cps) / policy.max_cps) ** 2)
                if last < len(tokens):
                    cost += costs[last]
                if cost + best[b] < best[a]:
                    best[a] = cost + best[b]
                    next_cut[a] = b
                if over:
                    break
        pieces = []
        a = 0
        while a < count:
            b = next_cut[a]
            first, last = boundaries[a], boundaries[b]
            text = " ".join(tokens[first:last])
            warnings = []
            if len(text) > policy.max_chars:
                warnings.append("subtitle_single_token_exceeds_max_chars" if last - first == 1
                                else "subtitle_alignment_overlap_prevents_split")
            if last < len(tokens) and costs[last] >= 5:
                warnings.append("subtitle_boundary_needs_review")
            pieces.append({**source, "first": source["first"] + first,
                           "last": source["first"] + last - 1, "text": text,
                           "subtitle_issues": warnings})
            a = b
        if len(pieces) > 1:
            split_sources += 1
            # Audit the original meaning once, rather than diagnosing intentional
            # subtitle continuations as missing ASR words in every shorter cue.
            from .sentence_rules import sentence_audit

            parent_issues = sentence_audit(source["text"], nlp)
            for piece in pieces:
                piece["subtitle_source_issues"] = parent_issues
                piece["subtitle_issues"].append("subtitle_split_for_readability")
        fitted.extend(pieces)
    return fitted, {"source_ranges_split": split_sources, "source_range_count": len(ranges),
                    "max_source_chars": max((len(r["text"]) for r in ranges), default=0)}
