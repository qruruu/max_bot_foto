import pytest
from pydantic import ValidationError

from app.news_documents import NewsSnapshot, safe_link


def snapshot(block):
    return {
        "title": "News",
        "summary": "Summary",
        "category": "Update",
        "document": {"type": "doc", "content": [block]},
    }


@pytest.mark.parametrize(
    "block",
    [
        {"type": "iframe", "attrs": {"src": "https://external.test"}},
        {"type": "paragraph", "attrs": {"style": "color:red"}},
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "link",
                    "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                }
            ],
        },
        {
            "type": "image",
            "attrs": {"src": "https://external.test/tracker", "asset_id": "bad", "alt": "x", "caption": "x"},
        },
        {"type": "heading", "attrs": {"level": 1}},
        {"type": "heading", "attrs": {"level": []}},
        {
            "type": "orderedList",
            "attrs": {"start": -1},
            "content": [{"type": "listItem", "content": [{"type": "paragraph"}]}],
        },
        {"type": "listItem", "content": [None]},
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "x", "marks": [{"type": "bold", "attrs": {"style": "x"}}]}],
        },
        {
            "type": "action",
            "attrs": {"href": "/org/11111111-1111-4111-8111-111111111111/photos", "label": "Private"},
        },
    ],
)
def test_unknown_or_unsafe_document_nodes_are_rejected(block):
    with pytest.raises(ValidationError):
        NewsSnapshot.model_validate(snapshot(block))


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "//other.test",
        "/api/photos",
        "/org/company/photos",
        "https://name:secret@example.test",
        "https://example.test\n",
        "/photos\\bad",
    ],
)
def test_links_cannot_execute_code_or_embed_author_organization(link):
    with pytest.raises(ValueError):
        safe_link(link)


@pytest.mark.parametrize(
    "link",
    [
        "https://example.test/help",
        "http://example.test",
        "/photos?date_from=2026-10-16",
        "/days",
        "/news/stable-slug",
    ],
)
def test_external_and_reader_relative_product_links(link):
    assert safe_link(link) == link


def test_depth_and_size_limits():
    block = {"type": "paragraph", "content": [{"type": "text", "text": "a" * 512001}]}
    with pytest.raises(ValidationError):
        NewsSnapshot.model_validate(snapshot(block))
