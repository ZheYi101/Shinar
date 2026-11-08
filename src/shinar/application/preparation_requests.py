"""Resumable semantic preparation, independently cached and durably budgeted."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Any, TypeVar

from shinar.core.domain import new_id
from shinar.core.knowledge import (
    ReasoningRequest,
    ReasoningResponse,
    model_call_usage,
)
from shinar.core.knowledge_context import (
    estimate_tokens,
)

T = TypeVar("T")


class PreparationFailure(ValueError):
    """Safe diagnostic: no raw model output or source material in error messages."""


class PreparationTruncated(PreparationFailure):
    """A different, smaller source request is needed; never raise its token cap."""


def parse_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value



class PreparationRequests:
    """Own request locks, durable reservations and validated response caching."""

    def __init__(self, provider, store, foreground_active):
        self.provider = provider
        self.store = store
        self.foreground_active = foreground_active
        self._locks = {}

    async def account(
        self,
        owner: str,
        workload: str,
        fingerprint: str,
        input_tokens: int,
        output_tokens: int,
        operation: Callable[[], Awaitable[T]],
        *,
        deadline: float = 150,
        metadata: dict[str, Any] | None = None,
    ) -> T:
        """Reserve before sending; unknown failed/cancelled usage keeps its reservation."""
        call_id = new_id("call")
        if hasattr(self.store, "reserve_model_call"):
            self.store.reserve_model_call(
                call_id,
                owner,
                workload,
                fingerprint,
                input_tokens,
                output_tokens,
                lease_seconds=deadline + 15,
                metadata=metadata,
            )
        usage: dict[str, Any] = {}
        token = model_call_usage.set(usage)
        started = perf_counter()
        status = "unknown"
        try:
            result = await operation()
            if isinstance(result, ReasoningResponse):
                usage.update(
                    {
                        key: value
                        for key, value in result.usage.items()
                        if key
                        in {
                            "input_tokens",
                            "output_tokens",
                            "total_tokens",
                            "reasoning_tokens",
                            "finish_reason",
                        }
                    }
                )
            status = "truncated" if usage.get("finish_reason") == "length" else "completed"
            return result
        except BaseException:
            status = "failed" if "input_tokens" in usage and "output_tokens" in usage else "unknown"
            raise
        finally:
            model_call_usage.reset(token)
            if hasattr(self.store, "settle_model_call"):
                self.store.settle_model_call(
                    call_id, usage, status, elapsed_ms=(perf_counter() - started) * 1000
                )


    async def request(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        owner: str,
        cache_key: str,
        source_hash: str,
        validate: Callable[[dict[str, Any]], T],
        max_tokens: int = 4096,
        deadline: float = 120,
        background: bool = False,
    ) -> T:
        lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            last = (
                self.store.latest_model_call(owner, method, cache_key)
                if hasattr(self.store, "latest_model_call")
                else None
            )
            if last and last["status"] == "truncated":
                raise PreparationTruncated("该输入曾达到输出预算，需要缩小输入后继续。")
            failure = (
                self.store.get_knowledge_artifact("failed:" + cache_key)
                if hasattr(self.store, "get_knowledge_artifact")
                else None
            )
            if failure and failure.get("reason") == "length":
                raise PreparationTruncated("该输入曾达到输出预算，需要缩小输入后继续。")
            cached = (
                self.store.get_knowledge_artifact(cache_key)
                if hasattr(self.store, "get_knowledge_artifact")
                else None
            )
            if cached:
                try:
                    result = validate(cached)
                except (ValueError, TypeError, KeyError):
                    pass
                else:
                    if hasattr(self.store, "record_knowledge_cache_hit"):
                        self.store.record_knowledge_cache_hit(cache_key, source_hash, method)
                    return result
            for attempt in range(2):
                while background and self.foreground_active():
                    await asyncio.sleep(0.05)
                request_payload = dict(payload)
                if attempt:
                    request_payload["repair"] = (
                        "Previous structure or evidence IDs were invalid. Return the compact requested schema using only supplied IDs."
                    )
                request = ReasoningRequest(
                    payload=request_payload, max_tokens=max_tokens, deadline_seconds=deadline
                )
                response = await self.account(
                    owner,
                    method,
                    cache_key + f":{attempt}",
                    estimate_tokens(json.dumps(request_payload, ensure_ascii=False)) + 1000,
                    max_tokens,
                    lambda: asyncio.wait_for(
                        getattr(self.provider, method)(request), timeout=deadline
                    ),
                    deadline=deadline,
                    metadata={
                        "source_hash": source_hash,
                        "source_revision": cache_key,
                        "source_ids": [item["id"] for item in payload.get("paragraphs", [])],
                        "message_ids": [
                            item["id"]
                            for item in payload.get("recent", payload.get("messages", []))
                        ],
                    },
                )
                if response.usage.get("finish_reason") == "length":
                    if hasattr(self.store, "save_knowledge_artifact"):
                        self.store.save_knowledge_artifact(
                            "failed:" + cache_key, source_hash, "failure", {"reason": "length"}
                        )
                    raise PreparationTruncated(
                        "模型输出达到预算，当前资料未记为成功；可保留进度后重试。"
                    )
                try:
                    data = parse_object(response.content)
                    result = validate(data)
                except (ValueError, TypeError, KeyError):
                    if attempt:
                        raise PreparationFailure(
                            "资料结构或来源验证失败，原文与已完成进度保留。"
                        ) from None
                    continue
                if hasattr(self.store, "save_knowledge_artifact"):
                    self.store.save_knowledge_artifact(cache_key, source_hash, method, data)
                return result
        raise AssertionError("unreachable")


