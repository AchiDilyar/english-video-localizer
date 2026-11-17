"""C: bilingual meaning, terminology, review and narration revision services."""
from .common import run_nodes,resolve_stage_nodes


def run_c(state,nodes=None):
    if nodes is None:
        nodes=resolve_stage_nodes(('build_blocks','translate_blocks','review_blocks','repair_blocks'))
    return run_nodes(state,nodes)


def plan_bilingual_parts(groups,request_json):
    from nodes.semantic_subtitles import request_pairs
    return request_pairs(groups,request_json)


def request_narration_change(**request):
    from nodes.translate_blocks import _text_model
    return _text_model.request_json(**request)


def audit_content(state):
    from nodes.repair_blocks import find_review_issues
    return find_review_issues(state)


def repair_content(state,issues):
    from nodes.repair_blocks import repair_segments
    return repair_segments(state,issues)
