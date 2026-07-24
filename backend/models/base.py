"""Shared MongoDB model behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MongoDocument(BaseModel):
    id: str = Field(alias="_id")

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        str_strip_whitespace=True,
    )

    def to_mongo(self) -> dict:
        return self.model_dump(
            by_alias=True,
            mode="python",
            exclude_none=False,
        )
