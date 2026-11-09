"""Historical standalone API, loaded only when explicitly requested.

Shared nodes import in-memory algorithms without importing the legacy graph/CLI.
"""
from importlib import import_module

_EXPORTS = {
    "build_b_graph": ("sentence_mode", "build_sentence_graph"),
    "run_b": ("sentence_mode", "run_sentences"),
    "resume_b": ("sentence_mode", "resume_sentences"),
    "load_timetable": ("sentence_mode", "load_sentence_table"),
    "resolve_input": ("video_inputs", "resolve_input"),
    "download_input": ("video_inputs", "download_input"),
    "diarize": ("diarization", "diarize"),
    "assign_speakers": ("diarization", "assign_speakers"),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, attribute = _EXPORTS[name]
    return getattr(import_module(f"{__name__}.{module}"), attribute)
