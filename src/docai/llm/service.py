import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol

from docai.llm.base import run_request
from docai.llm.llm_datatypes import (
    LLMExecutionPlan,
    LLMFunctionRequest,
    LLMFunctionResponse,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRole,
    LLMTarget,
    RetryPolicy,
)

logger = logging.getLogger("docai_project")

CACHE_VERSION = 1


class LLMServiceError(RuntimeError):
    pass


class LLMCache(Protocol):
    def get(self, key: str) -> LLMMessage | None:
        ...

    def set(self, key: str, message: LLMMessage) -> None:
        ...


class InMemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, LLMMessage] = {}

    def get(self, key: str) -> LLMMessage | None:
        return self._store.get(key)

    def set(self, key: str, message: LLMMessage) -> None:
        self._store[key] = message


class DiskCache:
    def __init__(self, cache_dir: str) -> None:
        self._cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get(self, key: str) -> LLMMessage | None:
        path = self._path_for_key(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("Failed to read cache entry %s: %s", path, exc)
            return None
        try:
            return _deserialize_message(data)
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("Failed to decode cache entry %s: %s", path, exc)
            return None

    def set(self, key: str, message: LLMMessage) -> None:
        path = self._path_for_key(key)
        temp_path = f"{path}.tmp"
        payload = _serialize_message(message)
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
            os.replace(temp_path, path)
        except OSError as exc:
            logger.debug("Failed to write cache entry %s: %s", path, exc)

    def _path_for_key(self, key: str) -> str:
        return os.path.join(self._cache_dir, f"{key}.json")


@dataclass(frozen=True)
class LLMService:
    llm_config: dict
    cache: LLMCache | None = None
    request_id_factory: Callable[[], str] = lambda: str(uuid.uuid4())
    runner: Callable[[LLMExecutionPlan], Awaitable[LLMResponse]] = run_request

    async def prompt(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        profile: str = "default",
        fallback_profiles: list[str] | None = None,
        agent_functions: list[str] | None = None,
        structured_output: dict | None = None,
        request_id: str | None = None,
        use_cache: bool = True,
        history: Iterable[LLMMessage] | None = None,
        model_config: dict[str, Any] | None = None,
        provider_config: dict[str, Any] | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> LLMResponse:
        if not prompt and not history:
            raise LLMServiceError("Prompt or history is required")

        request_id = request_id or self.request_id_factory()

        request = self._build_request(
            prompt=prompt,
            request_id=request_id,
            system_prompt=system_prompt,
            agent_functions=agent_functions,
            structured_output=structured_output,
            history=history,
        )

        primary_target, allowed_tools = self._resolve_target(
            profile, model_config, provider_config
        )

        if request.agent_functions is None and allowed_tools is not None:
            request.agent_functions = list(allowed_tools)

        fallback_targets = []
        if fallback_profiles:
            for fallback in fallback_profiles:
                target, _ = self._resolve_target(
                    fallback, model_config, provider_config
                )
                fallback_targets.append(target)

        plan = LLMExecutionPlan(
            request=request,
            primary=primary_target,
            fallbacks=fallback_targets,
            retry=retry_policy or self._build_retry_policy(),
        )

        return await self.get_or_run(plan, use_cache=use_cache)

    async def get_or_run(
        self, plan: LLMExecutionPlan, *, use_cache: bool = True
    ) -> LLMResponse:
        cache_key = self.build_cache_key(plan)
        if use_cache and self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return LLMResponse(request_id=plan.request.request_id, response=cached)

        response = await self.runner(plan)

        if use_cache and self.cache is not None and response.response is not None:
            self.cache.set(cache_key, response.response)

        return response

    def build_cache_key(self, plan: LLMExecutionPlan) -> str:
        payload = {
            "version": CACHE_VERSION,
            "request": _request_to_payload(plan.request),
            "primary": _target_to_payload(plan.primary),
            "fallbacks": [_target_to_payload(t) for t in plan.fallbacks],
            "retry": {
                "max_attempts": plan.retry.max_attempts,
                "retry_on": list(plan.retry.retry_on),
                "backoff_sec": plan.retry.backoff_sec,
            },
        }
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _build_request(
        self,
        *,
        prompt: str,
        request_id: str,
        system_prompt: str | None,
        agent_functions: list[str] | None,
        structured_output: dict | None,
        history: Iterable[LLMMessage] | None,
    ) -> LLMRequest:
        contents = list(history) if history else []
        contents.append(LLMMessage(role=LLMRole.USER, content=prompt))
        return LLMRequest(
            request_id=request_id,
            contents=contents,
            system_prompt=system_prompt,
            agent_functions=agent_functions,
            structured_output=structured_output,
        )

    def _resolve_target(
        self,
        profile_name: str,
        model_config_override: dict[str, Any] | None,
        provider_config_override: dict[str, Any] | None,
    ) -> tuple[LLMTarget, list[str] | None]:
        profiles = self.llm_config.get("profiles", {})
        models = self.llm_config.get("models", {})
        providers = self.llm_config.get("providers", {})

        if profile_name not in profiles:
            raise LLMServiceError(f"Unknown profile '{profile_name}'")

        profile = profiles[profile_name]
        model_key = profile.get("model")
        if not model_key or model_key not in models:
            raise LLMServiceError(
                f"Profile '{profile_name}' references unknown model '{model_key}'"
            )

        model = models[model_key]
        provider = profile.get("provider") or model.get("default-provider")
        if not provider:
            raise LLMServiceError(
                f"Model '{model_key}' does not define a default provider"
            )

        model_name = model.get("model_name", model_key)
        model_config = dict(model.get("generation", {}))
        provider_config = dict(providers.get(provider, {}))

        if model_config_override:
            model_config.update(model_config_override)
        if provider_config_override:
            provider_config.update(provider_config_override)

        tools = None
        if isinstance(profile.get("tools"), dict):
            tools = profile.get("tools", {}).get("allowed")

        return (
            LLMTarget(
                provider=provider,
                model=model_name,
                model_config=model_config or None,
                provider_config=provider_config or None,
            ),
            tools,
        )

    def _build_retry_policy(self) -> RetryPolicy:
        globals_config = self.llm_config.get("globals", {})
        max_attempts = globals_config.get("max_retries")
        retry_on = globals_config.get("retry_on")
        backoff_ms = globals_config.get("retry_delay")

        policy = RetryPolicy()
        if isinstance(max_attempts, int):
            policy.max_attempts = max_attempts
        if isinstance(retry_on, list):
            policy.retry_on = list(retry_on)
        if isinstance(backoff_ms, (int, float)):
            policy.backoff_sec = backoff_ms / 1000.0

        return policy


def _request_to_payload(request: LLMRequest) -> dict:
    return {
        "system_prompt": request.system_prompt,
        "structured_output": request.structured_output,
        "agent_functions": sorted(request.agent_functions)
        if request.agent_functions
        else None,
        "contents": [_message_to_payload(m) for m in request.contents],
    }


def _message_to_payload(message: LLMMessage) -> dict:
    payload = {"role": message.role.value}

    if isinstance(message.content, LLMFunctionRequest):
        payload["content_type"] = "function_request"
        payload["content"] = {
            "name": message.content.name,
            "args": message.content.args,
        }
    elif isinstance(message.content, LLMFunctionResponse):
        payload["content_type"] = "function_response"
        payload["content"] = {
            "name": message.content.name,
            "result": message.content.result,
        }
    else:
        payload["content_type"] = "text"
        payload["content"] = message.content

    if message.original_content is not None:
        payload["original_content_repr"] = repr(message.original_content)

    return payload


def _target_to_payload(target: LLMTarget) -> dict:
    return {
        "provider": target.provider,
        "model": target.model,
        "model_config": target.model_config,
        "provider_config": target.provider_config,
    }


def _serialize_message(message: LLMMessage) -> dict:
    payload = _message_to_payload(message)
    payload.pop("original_content_repr", None)
    return payload


def _deserialize_message(payload: dict) -> LLMMessage:
    role = LLMRole(payload["role"])
    content_type = payload["content_type"]
    content = payload["content"]

    if content_type == "function_request":
        parsed = LLMFunctionRequest(
            name=content["name"],
            args=content.get("args"),
        )
    elif content_type == "function_response":
        parsed = LLMFunctionResponse(
            name=content["name"],
            result=content.get("result"),
        )
    else:
        parsed = content

    return LLMMessage(role=role, content=parsed)
