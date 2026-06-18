"""Deterministic action gating for agent final responses."""

from __future__ import annotations

from typing import Literal

Intent = Literal["answer", "action", "clarify", "blocked"]
FinalKind = Literal["answer", "completed", "promise", "blocker", "clarification"]
GuardResult = Literal[
    "continued",
    "tool_evidence",
    "allowed_blocker",
    "allowed_clarification",
    "not_actionable",
    "retry_exhausted",
    "allowed_answer",
]

ACTION_FOLLOWUP_MESSAGE = (
    "You claimed or implied action, but no tools were used. "
    "Perform the requested action now, or state the concrete blocker."
)

_ACTION_MARKERS = (
    "检查", "查看", "修复", "修改", "运行", "推送", "部署", "补测试", "创建", "删除",
    "发送", "设置提醒", "执行", "更新", "提交", "分析日志", "看日志", "ssh", "gcloud",
    "inspect", "check", "fix", "modify", "edit", "run", "push", "deploy", "create",
    "delete", "send", "schedule", "execute", "update", "commit", "test", "look up",
    "view logs", "check logs",
)
_QUESTION_MARKERS = ("为什么", "为何", "怎么", "如何", "what", "why", "how", "?")
_PROMISE_MARKERS = (
    "我会", "我将", "我来", "接下来我", "稍后", "马上", "let me", "i will",
    "i'll", "i’m going to", "i am going to", "next i will",
)
_COMPLETED_MARKERS = (
    "已完成", "已经完成", "已检查", "已经检查", "已修复", "已经修复", "已推送",
    "已部署", "通过测试", "completed", "fixed", "checked", "deployed",
    "pushed", "tests passed",
)
_BLOCKER_MARKERS = (
    "无法", "不能", "缺少", "没有权限", "权限", "需要你", "blocked", "cannot",
    "can't", "unable", "missing", "permission", "need credentials", "need access",
)
_CLARIFICATION_MARKERS = (
    "请确认", "需要确认", "请提供", "哪个", "哪一个", "clarify", "which",
    "please provide", "need you to confirm",
)


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def classify_user_intent(text: str | None) -> Intent:
    value = _normalize(text)
    if not value:
        return "answer"
    if any(marker in value for marker in _ACTION_MARKERS):
        return "action"
    if any(marker in value for marker in _QUESTION_MARKERS):
        return "answer"
    return "answer"


def classify_final_response(text: str | None) -> FinalKind:
    value = _normalize(text)
    if not value:
        return "answer"
    if any(marker in value for marker in _BLOCKER_MARKERS):
        return "blocker"
    if any(marker in value for marker in _CLARIFICATION_MARKERS):
        return "clarification"
    if any(marker in value for marker in _PROMISE_MARKERS):
        return "promise"
    if any(marker in value for marker in _COMPLETED_MARKERS):
        return "completed"
    return "answer"


def has_successful_tool_event(tool_events: list[dict[str, str]]) -> bool:
    return any(event.get("status") == "ok" for event in tool_events)


def should_continue_for_action_guard(
    intent: Intent,
    final_kind: FinalKind,
    tool_events: list[dict[str, str]],
    *,
    already_retried: bool,
) -> bool:
    if intent != "action":
        return False
    if has_successful_tool_event(tool_events):
        return False
    if final_kind not in ("promise", "completed"):
        return False
    return not already_retried


def guard_result(
    intent: Intent,
    final_kind: FinalKind,
    tool_events: list[dict[str, str]],
    *,
    continued: bool,
    already_retried: bool,
) -> GuardResult:
    if continued:
        return "continued"
    if intent != "action":
        return "not_actionable"
    if has_successful_tool_event(tool_events):
        return "tool_evidence"
    if final_kind == "blocker":
        return "allowed_blocker"
    if final_kind == "clarification":
        return "allowed_clarification"
    if already_retried and final_kind in ("promise", "completed"):
        return "retry_exhausted"
    return "allowed_answer"
