"""Tests for the profile service (placeholder for further test expansion)."""

from tests.fake_repos import FakeDocumentRepository, FakeProfileRepository


def test_fake_profile_repo():
    """Verify the in-memory fake repo works for basic operations."""
    import asyncio

    repo = FakeProfileRepository()

    async def _run():
        pid = await repo.create_profile({"full_name": "Jane Doe", "email": "jane@test.com"})
        assert pid is not None
        profile = await repo.get_profile_by_id(pid)
        assert profile["full_name"] == "Jane Doe"
        assert await repo.count_profiles() == 1

    asyncio.get_event_loop().run_until_complete(_run())


def test_fake_document_repo():
    import asyncio

    repo = FakeDocumentRepository()

    async def _run():
        did = await repo.create_document({"profile_id": "p1", "file_name": "cv.pdf"})
        assert did is not None
        docs = await repo.get_documents_by_profile("p1")
        assert len(docs) == 1

    asyncio.get_event_loop().run_until_complete(_run())
