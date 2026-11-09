"""Run a minimal LangGraph translation and review loop."""

import argparse
import json
import os
from collections.abc import Callable
from functools import partial
from typing import TypedDict

import httpx
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError

from .deepseek import DEFAULT_MODEL, DeepSeekError, generate_json

SAMPLE = {
    "segment_id": "sample-001",
    "start_ms": 1000,
    "end_ms": 4000,
    "en": "Do not unplug the cable.",
}

TRANSLATE_PROMPT = (
    "你是英译中译员。保留原文数字、否定词和条件。收到审校意见时只修正指出的问题。"
    '输出 JSON，例如 {"zh_subtitle":"请勿拔线。","zh_dub":"别拔线。"}。'
)
REVIEW_PROMPT = (
    "你是独立的双语审校员。比较原文、中文字幕和中文口播稿，检查漏译、数字和否定词。"
    '输出 JSON，例如 {"issue":"漏掉了否定词"}。如无实质错误，issue 为空字符串。'
)


class Draft(BaseModel):
    zh_subtitle: str = Field(min_length=1)
    zh_dub: str = Field(min_length=1)


class Review(BaseModel):
    issue: str


class State(TypedDict, total=False):
    segment: dict
    draft: dict
    issue: str
    attempts: int


def build_graph(generate: Callable[[str, dict], dict] | None = None):
    def translate(state: State) -> dict:
        issue = state.get("issue", "")
        if generate is None:
            text = "请勿拔下线缆。" if issue else "请拔下线缆。"
            result = {"zh_subtitle": text, "zh_dub": text}
        else:
            result = generate(
                TRANSLATE_PROMPT,
                {
                    "segment": state["segment"],
                    "previous_draft": state.get("draft"),
                    "review_issue": issue,
                },
            )
        return {
            "draft": Draft.model_validate(result).model_dump(),
            "attempts": state["attempts"] + 1,
        }

    def review(state: State) -> dict:
        if generate is None:
            return {"issue": "漏译了否定词" if state["attempts"] == 1 else ""}
        result = generate(REVIEW_PROMPT, {"segment": state["segment"], "draft": state["draft"]})
        return Review.model_validate(result).model_dump()

    graph = StateGraph(State)
    graph.add_node("translate", translate)
    graph.add_node("review", review)
    graph.add_edge(START, "translate")
    graph.add_edge("translate", "review")
    graph.add_conditional_edges(
        "review",
        lambda state: "translate" if state["issue"] and state["attempts"] < 2 else END,
        ["translate", END],
    )
    return graph.compile()


def run_demo(generate: Callable[[str, dict], dict] | None = None) -> int:
    issue = ""
    graph = build_graph(generate)
    for update in graph.stream({"segment": SAMPLE, "attempts": 0}, stream_mode="updates"):
        print(json.dumps(update, ensure_ascii=False))
        if "review" in update:
            issue = update["review"]["issue"]
    if issue:
        print("返工后仍有问题，待人工复核。")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="运行英文片段的翻译、审校和返工示例。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="使用 DeepSeek API 运行固定测试片段")
    mode.add_argument("--graph", action="store_true", help="输出 Mermaid 流程图")
    args = parser.parse_args()
    if args.graph:
        print(build_graph().get_graph().draw_mermaid())
        return 0
    if not args.live:
        return run_demo()

    load_dotenv()
    try:
        with httpx.Client(timeout=60) as client:
            generate = partial(
                generate_json,
                client,
                api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                model=os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL,
            )
            return run_demo(generate)
    except DeepSeekError as error:
        parser.exit(1, f"{error}\n")
    except ValidationError:
        parser.exit(1, "DeepSeek JSON 字段不符合翻译或审校约定。\n")


if __name__ == "__main__":
    raise SystemExit(main())
