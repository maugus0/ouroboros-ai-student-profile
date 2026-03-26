"""In-memory fake repositories for unit testing without a database."""

from typing import Any

from app.utils.helpers import generate_uuid


class FakeProfileRepository:
    """In-memory store that mimics ProfileRepository."""

    def __init__(self):
        self._store: dict[str, dict[str, Any]] = {}

    async def create_profile(self, profile_data: dict[str, Any]) -> str:
        profile_id = generate_uuid()
        self._store[profile_id] = {"id": profile_id, **profile_data}
        return profile_id

    async def get_profile_by_id(self, profile_id: str) -> dict[str, Any] | None:
        return self._store.get(profile_id)

    async def get_profile_by_email(self, email: str) -> dict[str, Any] | None:
        for profile in self._store.values():
            if profile.get("email") == email:
                return profile
        return None

    async def list_profiles(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        items = list(self._store.values())
        return items[offset : offset + limit]

    async def count_profiles(self) -> int:
        return len(self._store)

    async def update_profile(self, profile_id: str, updates: dict[str, Any]) -> int:
        if profile_id not in self._store:
            return 0
        self._store[profile_id].update(updates)
        return 1

    async def delete_profile(self, profile_id: str) -> int:
        if profile_id in self._store:
            del self._store[profile_id]
            return 1
        return 0


class FakeDocumentRepository:
    """In-memory store that mimics DocumentRepository."""

    def __init__(self):
        self._store: dict[str, dict[str, Any]] = {}

    async def create_document(self, doc_data: dict[str, Any]) -> str:
        doc_id = generate_uuid()
        self._store[doc_id] = {"id": doc_id, **doc_data}
        return doc_id

    async def get_document_by_id(self, document_id: str) -> dict[str, Any] | None:
        return self._store.get(document_id)

    async def get_documents_by_profile(self, profile_id: str) -> list[dict[str, Any]]:
        return [d for d in self._store.values() if d.get("profile_id") == profile_id]

    async def delete_document(self, document_id: str) -> int:
        if document_id in self._store:
            del self._store[document_id]
            return 1
        return 0
