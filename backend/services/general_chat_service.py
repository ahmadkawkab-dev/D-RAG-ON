"""Open-domain Ollama chat with optional, explicitly isolated web tools.

After a configurable number of user questions, the service generates two
answers concurrently. The frontend can display both answers and allow the user
to select one.

Only the selected answer should later be committed to permanent conversation
history.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from uuid import uuid4

from ollama import AsyncClient

from backend.core.config import Settings
from backend.services.cache import CacheInfo, TTLCache


GENERAL_SYSTEM_PROMPT = """You are the general-chat assistant.

Answer open-domain questions directly and clearly.

When web tool results are available:
- Use them when relevant.
- Cite them inline as [1], [2], and so on.
- Keep citations brief.
- Do not invent sources.

Never claim that general-chat answers came from the user's document library.
General chat and document retrieval are separate systems.

If you do not know the answer, say so clearly.
"""


WEB_PLANNING_SYSTEM_PROMPT = """Determine whether the user's question requires
current public web information.

Use web_search for current, recent, changing, or externally verifiable facts.
Use web_fetch when the user provides a URL or when a specific search result
needs to be read in more detail.

Do not use web tools for ordinary reasoning, writing, coding explanations, or
stable general knowledge.
"""


WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the public web for current information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The public-web search query.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch readable content from a public web page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public HTTP or HTTPS URL to fetch.",
                    }
                },
                "required": ["url"],
            },
        },
    },
]


@dataclass(frozen=True)
class AnswerVariant:
    """Configuration for one independently generated answer."""

    answer_id: str
    label: str
    instruction: str
    temperature: float


ANSWER_VARIANTS = (
    AnswerVariant(
        answer_id="answer_a",
        label="Direct answer",
        instruction=(
            "Provide the most direct and practical answer. "
            "Prioritize correctness, clarity, and conciseness. "
            "Do not mention that another answer is being generated."
        ),
        temperature=0.25,
    ),
    AnswerVariant(
        answer_id="answer_b",
        label="Alternative answer",
        instruction=(
            "Provide a genuinely useful alternative answer. "
            "Use a different explanation, structure, or perspective while "
            "remaining accurate. Do not disagree merely to be different. "
            "Do not mention that another answer is being generated."
        ),
        temperature=0.55,
    ),
)


@dataclass
class PreparedGeneralChat:
    """A prepared general-chat request."""

    messages: list[dict[str, Any]]

    # Unique identifier used when the user selects an answer.
    generation_id: str = field(default_factory=lambda: uuid4().hex)

    sources: list[dict[str, Any]] = field(default_factory=list)
    web_enabled: bool = False

    # One answer for early turns, two answers after the configured threshold.
    answer_count: int = 1

    # Number of user questions before the current question.
    previous_user_question_count: int = 0


class GeneralChatService:
    """Runs general Ollama chat without touching document retrieval."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        self._web_cache: TTLCache[str, dict[str, Any]] = TTLCache(
            settings.general_web_cache_size,
            settings.general_web_cache_ttl_seconds,
        )

        # Temporarily stores generated candidates so the backend can retrieve
        # the selected answer by generation_id and answer_id.
        #
        # This prevents the backend from trusting answer text submitted by the
        # browser.
        self._answer_choice_cache: TTLCache[str, dict[str, Any]] = TTLCache(
            settings.general_answer_choice_cache_size,
            settings.general_answer_choice_ttl_seconds,
        )

    @property
    def web_enabled(self) -> bool:
        """Whether Ollama web tools are configured and enabled."""

        return bool(
            self.settings.general_web_search_enabled
            and self.settings.ollama_api_key
        )

    def _client(self, *, web: bool = False) -> AsyncClient:
        """Create an isolated Ollama client."""

        kwargs: dict[str, Any] = {
            "timeout": self.settings.llm_request_timeout_seconds,
        }

        if web and self.settings.ollama_api_key:
            kwargs["headers"] = {
                "Authorization": (
                    f"Bearer "
                    f"{self.settings.ollama_api_key.get_secret_value()}"
                )
            }

        return AsyncClient(
            host=self.settings.ollama_host,
            **kwargs,
        )

    async def prepare(
        self,
        question: str,
        history: list[dict[str, str]],
    ) -> PreparedGeneralChat:
        """Prepare messages and optionally execute isolated web tools.

        The full history is used when counting user questions. Only the latest
        configured number of messages is passed into the model context.
        """

        cleaned_question = question.strip()

        if not cleaned_question:
            raise ValueError("Question cannot be empty.")

        previous_user_question_count = sum(
            1
            for message in history
            if message.get("role") == "user"
        )

        history_limit = self.settings.general_chat_history_messages

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": GENERAL_SYSTEM_PROMPT,
            },
            *copy.deepcopy(history[-history_limit:]),
            {
                "role": "user",
                "content": cleaned_question,
            },
        ]

        prepared = PreparedGeneralChat(
            messages=messages,
            sources=[],
            web_enabled=self.web_enabled,
            answer_count=self._determine_answer_count(
                previous_user_question_count
            ),
            previous_user_question_count=previous_user_question_count,
        )

        if not self.web_enabled:
            return prepared

        if not self._needs_web(cleaned_question):
            return prepared

        await self._prepare_web_context(prepared)

        return prepared

    async def _prepare_web_context(
        self,
        prepared: PreparedGeneralChat,
    ) -> None:
        """Ask the model for web calls and append their results.

        Web execution is performed separately from final answer generation.
        """

        client = self._client(web=True)

        try:
            planning_messages = copy.deepcopy(prepared.messages)

            planning_messages[0]["content"] = (
                f"{planning_messages[0]['content']}\n\n"
                f"{WEB_PLANNING_SYSTEM_PROMPT}"
            )

            response = await client.chat(
                model=self.settings.general_chat_model,
                messages=planning_messages,
                tools=WEB_TOOLS,
                stream=False,
                think=False,
                keep_alive=self.settings.general_chat_keep_alive,
                options={
                    "temperature": 0.2,
                    "num_predict": 256,
                    "num_ctx": self.settings.general_chat_num_ctx,
                },
            )

            tool_calls = response.message.tool_calls or []

            if not tool_calls:
                return

            # The assistant tool-call message must be included before the
            # corresponding tool results.
            prepared.messages.append(
                response.message.model_dump(exclude_none=True)
            )

            for tool_call in tool_calls[:3]:
                name = str(tool_call.function.name)
                arguments = dict(tool_call.function.arguments or {})

                result = await self._run_tool(
                    client=client,
                    name=name,
                    arguments=arguments,
                )

                numbered_content = self._number_tool_content(
                    result["content"],
                    source_offset=len(prepared.sources),
                )

                prepared.sources.extend(result["sources"])

                prepared.messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(
                            numbered_content,
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )
        finally:
            await client.close()

    async def stream(
        self,
        prepared: PreparedGeneralChat,
    ) -> AsyncIterator[str]:
        """Backward-compatible stream returning only the primary answer.

        Existing endpoints can continue using this method.

        New endpoints that support answer selection should use
        stream_candidates().
        """

        primary_answer_id = ANSWER_VARIANTS[0].answer_id

        async for event in self.stream_candidates(prepared):
            if (
                event["type"] == "token"
                and event["answer_id"] == primary_answer_id
            ):
                yield str(event["content"])

    async def stream_candidates(
        self,
        prepared: PreparedGeneralChat,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream one or two independently generated answer candidates.

        Events from both candidates are multiplexed through one async stream.

        Event types:
        - generation_start
        - answer_start
        - token
        - answer_done
        - answer_error
        - generation_done
        """

        variants = ANSWER_VARIANTS[: prepared.answer_count]

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)

        completed_answers: dict[str, dict[str, Any]] = {}

        yield {
            "type": "generation_start",
            "generation_id": prepared.generation_id,
            "answer_id": None,
            "label": None,
            "content": "",
            "answer_count": len(variants),
            "sources": copy.deepcopy(prepared.sources),
        }

        async def produce(variant: AnswerVariant) -> None:
            chunks: list[str] = []

            await queue.put(
                {
                    "type": "answer_start",
                    "generation_id": prepared.generation_id,
                    "answer_id": variant.answer_id,
                    "label": variant.label,
                    "content": "",
                }
            )

            try:
                async for token in self._stream_one_answer(
                    prepared=prepared,
                    variant=variant,
                ):
                    chunks.append(token)

                    await queue.put(
                        {
                            "type": "token",
                            "generation_id": prepared.generation_id,
                            "answer_id": variant.answer_id,
                            "label": variant.label,
                            "content": token,
                        }
                    )

                answer_text = "".join(chunks).strip()

                if not answer_text:
                    raise RuntimeError(
                        "The model completed without producing answer text."
                    )

                completed_answers[variant.answer_id] = {
                    "answer_id": variant.answer_id,
                    "label": variant.label,
                    "content": answer_text,
                }

                await queue.put(
                    {
                        "type": "answer_done",
                        "generation_id": prepared.generation_id,
                        "answer_id": variant.answer_id,
                        "label": variant.label,
                        "content": "",
                    }
                )

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                await queue.put(
                    {
                        "type": "answer_error",
                        "generation_id": prepared.generation_id,
                        "answer_id": variant.answer_id,
                        "label": variant.label,
                        "content": (
                            "This answer could not be generated."
                        ),
                        # Do not expose detailed errors in production if they
                        # may contain internal infrastructure information.
                        "error": str(exc),
                    }
                )

            finally:
                await queue.put(
                    {
                        "type": "_producer_finished",
                        "generation_id": prepared.generation_id,
                        "answer_id": variant.answer_id,
                        "label": variant.label,
                        "content": "",
                    }
                )

        tasks = [
            asyncio.create_task(
                produce(variant),
                name=(
                    f"general-chat-"
                    f"{prepared.generation_id}-"
                    f"{variant.answer_id}"
                ),
            )
            for variant in variants
        ]

        remaining_producers = len(tasks)

        try:
            while remaining_producers > 0:
                event = await queue.get()

                if event["type"] == "_producer_finished":
                    remaining_producers -= 1
                    continue

                yield event

            if completed_answers:
                self._answer_choice_cache.put(
                    prepared.generation_id,
                    {
                        "generation_id": prepared.generation_id,
                        "answers": copy.deepcopy(completed_answers),
                        "sources": copy.deepcopy(prepared.sources),
                        "previous_user_question_count": (
                            prepared.previous_user_question_count
                        ),
                    },
                )

            yield {
                "type": "generation_done",
                "generation_id": prepared.generation_id,
                "answer_id": None,
                "label": None,
                "content": "",
                "available_answer_ids": list(completed_answers),
            }

        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

    async def _stream_one_answer(
        self,
        *,
        prepared: PreparedGeneralChat,
        variant: AnswerVariant,
    ) -> AsyncIterator[str]:
        """Generate one answer candidate."""

        messages = copy.deepcopy(prepared.messages)

        messages[0]["content"] = (
            f"{messages[0]['content']}\n\n"
            "Answer-variant instruction:\n"
            f"{variant.instruction}"
        )

        client = self._client()

        try:
            async with asyncio.timeout(
                self.settings.general_chat_timeout_seconds
            ):
                response = await client.chat(
                    model=self.settings.general_chat_model,
                    messages=messages,
                    stream=True,
                    think=False,
                    keep_alive=self.settings.general_chat_keep_alive,
                    options={
                        "temperature": variant.temperature,
                        "num_predict": (
                            self.settings.general_chat_max_tokens
                        ),
                        "num_ctx": (
                            self.settings.general_chat_num_ctx
                        ),
                    },
                )

                async for event in response:
                    token = event.message.content

                    if token:
                        yield token

        finally:
            await client.close()

    def get_selected_answer(
        self,
        *,
        generation_id: str,
        answer_id: str,
    ) -> dict[str, Any]:
        """Retrieve a generated answer selected by the user.

        The returned content comes from the server-side cache, not from text
        submitted by the frontend.
        """

        generation = self._answer_choice_cache.get(generation_id)

        if generation is None:
            raise KeyError(
                "The generated answers were not found or have expired."
            )

        answers = generation.get("answers", {})
        selected = answers.get(answer_id)

        if selected is None:
            raise KeyError(
                f"Answer '{answer_id}' is not available for this generation."
            )

        return {
            "generation_id": generation_id,
            "answer_id": selected["answer_id"],
            "label": selected["label"],
            "content": selected["content"],
            "sources": copy.deepcopy(generation.get("sources", [])),
        }

    async def _run_tool(
        self,
        client: AsyncClient,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an allowed web tool."""

        cache_key = self._web_cache_key(name, arguments)
        cached = self._web_cache.get(cache_key)

        if cached is not None:
            return copy.deepcopy(cached)

        if name == "web_search":
            query = str(arguments.get("query") or "").strip()

            if not query:
                return {
                    "content": {
                        "error": "A web-search query is required."
                    },
                    "sources": [],
                }

            response = await client.web_search(
                query,
                max_results=self.settings.general_web_max_results,
            )

            results = [
                item.model_dump()
                for item in response.results
            ]

            result = {
                "content": {
                    "query": query,
                    "results": results,
                },
                "sources": [
                    self._source(
                        url=str(item.get("url") or ""),
                        title=str(
                            item.get("title") or "Web result"
                        ),
                        text=str(
                            item.get("content")
                            or "Content unavailable"
                        ),
                    )
                    for item in results
                    if item.get("url")
                ],
            }

            self._web_cache.put(
                cache_key,
                copy.deepcopy(result),
            )

            return result

        if (
            name == "web_fetch"
            and self.settings.general_web_fetch_enabled
        ):
            url = str(arguments.get("url") or "").strip()

            if not self._is_public_web_url(url):
                return {
                    "content": {
                        "error": (
                            "Only public HTTP or HTTPS URLs are allowed."
                        )
                    },
                    "sources": [],
                }

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

            self._web_cache.put(
                cache_key,
                copy.deepcopy(result),
            )

            return result

        return {
            "content": {
                "error": f"Tool '{name}' is unavailable."
            },
            "sources": [],
        }

    def _determine_answer_count(
        self,
        previous_user_question_count: int,
    ) -> int:
        """Return two answers at the end of each repeating question cycle.

        ``general_dual_answer_after_questions`` is the number of normal,
        single-answer questions before one dual-answer question.

        With ``general_dual_answer_after_questions=2``:

        - Questions 1 and 2: one answer.
        - Question 3: two answers.
        - Questions 4 and 5: one answer.
        - Question 6: two answers.
        - The cycle then repeats.
        """

        if not self.settings.general_dual_answer_enabled:
            return 1

        normal_questions_per_cycle = max(
            0,
            self.settings.general_dual_answer_after_questions,
        )

        cycle_length = normal_questions_per_cycle + 1
        current_question_number = previous_user_question_count + 1

        if current_question_number % cycle_length == 0:
            return 2

        return 1

    @staticmethod
    def _number_tool_content(
        content: Any,
        *,
        source_offset: int,
    ) -> Any:
        """Attach source numbers to web-search results."""

        if not isinstance(content, dict):
            return content

        copied = copy.deepcopy(content)
        results = copied.get("results")

        if not isinstance(results, list):
            return copied

        numbered_results: list[Any] = []

        for index, result in enumerate(
            results,
            start=source_offset + 1,
        ):
            if isinstance(result, dict):
                numbered_result = copy.deepcopy(result)
                numbered_result["source_number"] = index
                numbered_results.append(numbered_result)
            else:
                numbered_results.append(result)

        copied["results"] = numbered_results

        return copied

    @staticmethod
    def _is_public_web_url(url: str) -> bool:
        """Perform a minimal URL scheme validation.

        For stronger SSRF protection, validate DNS resolution and reject
        private, loopback, link-local, and internal IP ranges before fetching.
        """

        normalized = url.lower()

        return normalized.startswith(
            (
                "http://",
                "https://",
            )
        )

    @property
    def web_cache_info(self) -> CacheInfo:
        return self._web_cache.info()

    @property
    def answer_choice_cache_info(self) -> CacheInfo:
        return self._answer_choice_cache.info()

    def clear_web_cache(self) -> None:
        self._web_cache.clear()

    def clear_answer_choice_cache(self) -> None:
        self._answer_choice_cache.clear()

    def _web_cache_key(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        payload = {
            "tool": name,
            "arguments": arguments,
            "max_results": (
                self.settings.general_web_max_results
            ),
            "fetch_enabled": (
                self.settings.general_web_fetch_enabled
            ),
        }

        serialized = json.dumps(
            payload,
            sort_keys=True,
            default=str,
        )

        return hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _needs_web(question: str) -> bool:
        normalized = question.lower()

        markers = (
            "latest",
            "current",
            "currently",
            "today",
            "tonight",
            "tomorrow",
            "yesterday",
            "recent",
            "recently",
            "news",
            "price",
            "weather",
            "forecast",
            "score",
            "schedule",
            "search the web",
            "search online",
            "look up",
            "verify online",
            "browse",
            "http://",
            "https://",
        )

        return any(
            marker in normalized
            for marker in markers
        )

    @staticmethod
    def _source(
        *,
        url: str,
        title: str,
        text: str,
    ) -> dict[str, Any]:
        concise = " ".join(text.split())

        if len(concise) > 420:
            concise = (
                f"{concise[:417].rstrip()}..."
            )

        return {
            "document_id": hashlib.sha256(
                url.encode("utf-8")
            ).hexdigest()[:24],
            "title": title,
            "source_url": url,
            "chunk_text": concise,
            "summary": concise,
            "metadata": {
                "provider": "ollama_web",
            },
        }