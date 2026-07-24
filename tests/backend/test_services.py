from __future__ import annotations

import json

import pytest

from backend.services.chat_service import ChatService, SessionNotFoundError
from backend.services.rag_service import RAGService
from backend.services.sse import encode_sse
from tests.backend.fakes import FakeDatabase


def test_citation_normalization_supports_source_accordion() -> None:
    citation = RAGService.citation_from_chunk(
        {
            "text": "Safeguard evidence",
            "score": 0.75,
            "rerank_score": 0.91,
            "metadata": {
                "document_id": "doc-1",
                "doc_title": "CIS Controls",
                "source_file": "data/cis.pdf",
                "page_start": 42,
                "clause_number": "5.1",
            },
        }
    )

    assert citation.document_id == "doc-1"
    assert citation.title == "CIS Controls"
    assert citation.file_path == "data/cis.pdf"
    assert citation.chunk_text == "Safeguard evidence"
    assert citation.score == pytest.approx(0.91)
    assert citation.relevance == pytest.approx(0.91)
    assert citation.page_number == 42
    assert citation.section == "5.1"


def test_sse_encoder_produces_one_json_data_line() -> None:
    event = encode_sse("delta", {"content": "hello\nworld"})

    assert event.startswith("event: delta\ndata: ")
    assert event.endswith("\n\n")
    data_line = event.splitlines()[1].removeprefix("data: ")
    assert json.loads(data_line) == {"content": "hello\nworld"}


@pytest.mark.asyncio
async def test_chat_history_is_scoped_to_session_owner() -> None:
    database = FakeDatabase()
    service = ChatService(database)
    session = await service.get_or_create_session(
        user_id="user-a",
        session_id=None,
        first_message="Explain control 5",
    )
    await service.append_message(
        session_id=session.id,
        role="user",
        content="Explain control 5",
    )
    await service.append_message(
        session_id=session.id,
        role="assistant",
        content="Grounded answer",
        sources=[
            {
                "document_id": "doc-1",
                "title": "CIS",
                "file_path": "data/cis.pdf",
                "chunk_text": "Evidence",
                "page_number": 5,
            }
        ],
    )

    sessions = await service.list_sessions("user-a")
    stored_session, messages = await service.get_session(
        user_id="user-a",
        session_id=session.id,
    )

    assert [item.id for item in sessions] == [session.id]
    assert stored_session.user_id == "user-a"
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].sources[0].document_id == "doc-1"
    with pytest.raises(SessionNotFoundError):
        await service.get_session(user_id="user-b", session_id=session.id)
    with pytest.raises(SessionNotFoundError):
        await service.delete_session(user_id="user-b", session_id=session.id)

    await service.delete_session(user_id="user-a", session_id=session.id)
    assert await service.list_sessions("user-a") == []
