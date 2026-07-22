"""Open-domain Ollama chat with optional, explicitly isolated web tools."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from ollama import AsyncClient

from backend.core.config import Settings
from backend.services.cache import CacheInfo, TTLCache


GENERAL_SYSTEM_PROMPT = """You are the general-chat assistant.
Answer open-domain questions directly and clearly. Use web tool results when
they are present, cite them inline as [1], [2], and keep citations brief.
Never claim that general-chat answers came from the user's document library.
"""


WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the public web for current information.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch the readable content of a public web page.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]


@dataclass
class PreparedGeneralChat:
    messages: list[dict[str, Any]]
    sources: list[dict[str, Any]] = field(default_factory=list)
    web_enabled: bool = False


class GeneralChatService:
    """Runs Qwen general chat without touching document retrieval."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._web_cache: TTLCache[str, dict[str, Any]] = TTLCache(
            settings.general_web_cache_size,
            settings.general_web_cache_ttl_seconds,
        )

    @property
    def web_enabled(self) -> bool:
        return bool(
            self.settings.general_web_search_enabled
            and self.settings.ollama_api_key
        )

    def _client(self, *, web: bool = False) -> AsyncClient:
        kwargs: dict[str, Any] = {
            "timeout": self.settings.llm_request_timeout_seconds,
        }
        if web and self.settings.ollama_api_key:
            kwargs["headers"] = {
                "Authorization": (
                    f"Bearer {self.settings.ollama_api_key.get_secret_value()}"
                )
            }
        return AsyncClient(host=self.settings.ollama_host, **kwargs)

    async def prepare(
        self,
        question: str,
        history: list[dict[str, str]],
    ) -> PreparedGeneralChat:
        limit = self.settings.general_chat_history_messages
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": GENERAL_SYSTEM_PROMPT},
            *history[-limit:],
            {"role": "user", "content": question},
        ]
        prepared = PreparedGeneralChat(
            messages=messages,
            web_enabled=self.web_enabled,
        )
        if not self.web_enabled or not self._needs_web(question):
            return prepared

        client = self._client(web=True)
        try:
            response = await client.chat(
                model=self.settings.general_chat_model,
                messages=messages,
                tools=WEB_TOOLS,
                stream=False,
                think=False,
                keep_alive=self.settings.general_chat_keep_alive,
                options={"temperature": 0.2, "num_predict": 256},
            )
            tool_calls = response.message.tool_calls or []
            if not tool_calls:
                return prepared
            prepared.messages.append(response.message.model_dump(exclude_none=True))
            for tool_call in tool_calls[:3]:
                name = tool_call.function.name
                arguments = tool_call.function.arguments or {}
                result = await self._run_tool(client, name, arguments)
                prepared.sources.extend(result["sources"])
                prepared.messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(result["content"]),
                    }
                )
        finally:
            await client.close()
        return prepared

    async def stream(
        self,
        prepared: PreparedGeneralChat,
    ) -> AsyncIterator[str]:
        client = self._client()
        try:
            async with asyncio.timeout(self.settings.general_chat_timeout_seconds):
                response = await client.chat(
                    model=self.settings.general_chat_model,
                    messages=prepared.messages,
                    stream=True,
                    think=False,
                    keep_alive=self.settings.general_chat_keep_alive,
                    options={
                        "temperature": 0.35,
                        "num_predict": self.settings.general_chat_max_tokens,
                        "num_ctx": self.settings.general_chat_num_ctx,
                    },
                )
                async for event in response:
                    token = event.message.content
                    if token:
                        yield token
        finally:
            await client.close()

    async def _run_tool(
        self,
        client: AsyncClient,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        cache_key = self._web_cache_key(name, arguments)
        cached = self._web_cache.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)

        if name == "web_search":
            response = await client.web_search(
                str(arguments.get("query") or ""),
                max_results=self.settings.general_web_max_results,
            )
            results = [item.model_dump() for item in response.results]
            result = {
                "content": results,
                "sources": [
                    self._source(
                        url=str(item.get("url") or ""),
                        title=str(item.get("title") or "Web result"),
                        text=str(item.get("content") or ""),
                    )
                    for item in results
                    if item.get("url")
                ],
            }
            self._web_cache.put(cache_key, copy.deepcopy(result))
            return result
        if name == "web_fetch" and self.settings.general_web_fetch_enabled:
            url = str(arguments.get("url") or "")
            response = await client.web_fetch(url)
            data = response.model_dump()
            text = str(data.get("content") or "")
            result = {
                "content": data,
                "sources": [
                    self._source(
                        url=url,
                        title=str(data.get("title") or url),
                        text=text,
                    )
                ],
            }
            self._web_cache.put(cache_key, copy.deepcopy(result))
            return result
        return {"content": {"error": "Tool unavailable"}, "sources": []}

    @property
    def web_cache_info(self) -> CacheInfo:
        return self._web_cache.info()

    def clear_web_cache(self) -> None:
        self._web_cache.clear()

    def _web_cache_key(self, name: str, arguments: dict[str, Any]) -> str:
        payload = {
            "tool": name,
            "arguments": arguments,
            "max_results": self.settings.general_web_max_results,
            "fetch_enabled": self.settings.general_web_fetch_enabled,
        }
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()

    @staticmethod
    def _needs_web(question: str) -> bool:
        normalized = question.lower()
        markers = (
            "latest",
            "current",
            "today",
            "recent",
            "news",
            "price",
            "weather",
            "search the web",
            "look up",
            "verify online",
            "http://",
            "https://",
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _source(*, url: str, title: str, text: str) -> dict[str, Any]:
        concise = " ".join(text.split())
        if len(concise) > 420:
            concise = f"{concise[:417].rstrip()}..."
        return {
            "document_id": hashlib.sha256(url.encode()).hexdigest()[:24],
            "title": title,
            "source_url": url,
            "chunk_text": concise,
            "summary": concise,
            "metadata": {"provider": "ollama_web"},
        }
