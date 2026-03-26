"""Tests for document text extraction (mocked)."""

import base64

import pytest

from app.services.document_parser import DocumentParser


@pytest.mark.asyncio
async def test_invalid_base64_raises():
    parser = DocumentParser()
    with pytest.raises(Exception):
        await parser.extract_text("not-valid-base64!!!", "test.pdf")


@pytest.mark.asyncio
async def test_unsupported_extension_raises():
    parser = DocumentParser()
    content = base64.b64encode(b"dummy content").decode()
    with pytest.raises(Exception, match="Unsupported file extension"):
        await parser.extract_text(content, "test.xyz")
