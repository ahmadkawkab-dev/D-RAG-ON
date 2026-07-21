"""Small async MongoDB fakes used by backend unit tests."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any


def _matches(document: dict, query: dict) -> bool:
    return all(document.get(key) == value for key, value in query.items())


class FakeCursor:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = [deepcopy(document) for document in documents]
        self.index = 0

    def sort(self, key: str, direction: int) -> "FakeCursor":
        self.documents.sort(
            key=lambda document: document.get(key),
            reverse=direction < 0,
        )
        return self

    def __aiter__(self) -> "FakeCursor":
        self.index = 0
        return self

    async def __anext__(self) -> dict:
        if self.index >= len(self.documents):
            raise StopAsyncIteration
        document = self.documents[self.index]
        self.index += 1
        return deepcopy(document)


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []

    async def find_one(
        self,
        query: dict,
        projection: dict | None = None,
    ) -> dict | None:
        for document in self.documents:
            if _matches(document, query):
                if projection:
                    return {
                        key: deepcopy(document[key])
                        for key, included in projection.items()
                        if included and key in document
                    }
                return deepcopy(document)
        return None

    async def insert_one(self, document: dict) -> SimpleNamespace:
        self.documents.append(deepcopy(document))
        return SimpleNamespace(inserted_id=document["_id"])

    async def update_one(self, query: dict, update: dict) -> SimpleNamespace:
        for document in self.documents:
            if _matches(document, query):
                document.update(deepcopy(update.get("$set", {})))
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def find(self, query: dict) -> FakeCursor:
        return FakeCursor(
            [
                document
                for document in self.documents
                if _matches(document, query)
            ]
        )

    async def delete_many(self, query: dict) -> SimpleNamespace:
        before = len(self.documents)
        self.documents = [
            document
            for document in self.documents
            if not _matches(document, query)
        ]
        return SimpleNamespace(deleted_count=before - len(self.documents))

    async def delete_one(self, query: dict) -> SimpleNamespace:
        for index, document in enumerate(self.documents):
            if _matches(document, query):
                self.documents.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class FakeDatabase:
    def __init__(self) -> None:
        self.users = FakeCollection()
        self.chat_sessions = FakeCollection()
        self.chat_messages = FakeCollection()
