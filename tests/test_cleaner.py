from article_to_speech.article.cleaner import NarrationFormatter
from article_to_speech.core.models import ResolvedArticle


def test_cleaner_preserves_article_text_in_single_request() -> None:
    formatter = NarrationFormatter()
    article = ResolvedArticle(
        canonical_url="https://example.com/article",
        original_url="https://example.com/article",
        final_url="https://example.com/article",
        title="Example",
        subtitle="Subtitle",
        source="Example Source",
        author="Reporter",
        published_at="2026-03-24",
        body_text=("## Section\n\nParagraph one.\n\n" + ("Paragraph two. " * 40)),
    )
    requests = formatter.build_requests(article)
    assert len(requests) == 1
    assert "do not read markdown punctuation literally" in requests[0].prompt_text
    assert "<text>" in requests[0].prompt_text
    assert "Example" in requests[0].prompt_text
    assert "Subtitle" in requests[0].prompt_text
    assert "Section" in requests[0].prompt_text
    assert "Paragraph one." in requests[0].prompt_text
    assert "Paragraph two." in requests[0].prompt_text


def test_cleaner_drops_boilerplate_lines() -> None:
    formatter = NarrationFormatter()
    article = ResolvedArticle(
        canonical_url="https://example.com/article",
        original_url="https://example.com/article",
        final_url="https://example.com/article",
        title="Example",
        subtitle=None,
        source=None,
        author=None,
        published_at=None,
        body_text="Advertisement\n\nActual paragraph.\n\nRead more\n\nSecond paragraph.",
    )
    cleaned = formatter.clean_article_text(article)
    assert "Advertisement" not in cleaned
    assert "Read more" not in cleaned
    assert "Actual paragraph." in cleaned


def test_cleaner_trims_leading_site_chrome_labels() -> None:
    formatter = NarrationFormatter()
    article = ResolvedArticle(
        canonical_url="https://example.com/article",
        original_url="https://example.com/article",
        final_url="https://example.com/article",
        title="Example",
        subtitle=None,
        source=None,
        author=None,
        published_at=None,
        body_text=(
            "Tracking ICE Activity\n\n"
            "Minnesota Shootings\n\n"
            "Share full article\n\n"
            "Editors' Picks\n\n"
            "Costa Rica said it had agreed to take up to 25 deportees a week from the United States.\n\n"
            "The court seemed open to the administration's request during arguments."
        ),
    )

    cleaned = formatter.clean_article_text(article)

    assert "Tracking ICE Activity" not in cleaned
    assert "Share full article" not in cleaned
    assert cleaned.startswith("Example\n\n")
    assert "Costa Rica said it had agreed to take up to 25 deportees a week from the United States." in cleaned


def test_cleaner_chunks_long_article_into_multiple_requests() -> None:
    formatter = NarrationFormatter()
    formatter.max_chatgpt_message_chars = 450
    article = ResolvedArticle(
        canonical_url="https://example.com/article",
        original_url="https://example.com/article",
        final_url="https://example.com/article",
        title="Example",
        subtitle="Subtitle",
        source=None,
        author=None,
        published_at=None,
        body_text=(
            "First paragraph. " * 12
            + "\n\n"
            + "Second paragraph. " * 12
            + "\n\n"
            + "Third paragraph. " * 12
        ),
    )

    requests = formatter.build_requests(article)

    assert len(requests) > 1
    assert "Part 1 of" in requests[0].prompt_text
    assert (
        "Output the full cleaned text of this part as a direct continuation of the article."
        in requests[0].prompt_text
    )
    assert "return only the cleaned passage." in requests[0].prompt_text
    assert "Example" in requests[0].prompt_text
    assert "Subtitle" in requests[0].prompt_text
    assert all("<text>" not in request.prompt_text for request in requests)
    assert all(
        len(request.prompt_text) <= formatter.max_chatgpt_message_chars for request in requests
    )
    assert all("Example" not in request.prompt_text for request in requests[1:])
    assert all("Subtitle" not in request.prompt_text for request in requests[1:])


def test_cleaner_prefers_paragraph_boundaries_when_chunking() -> None:
    formatter = NarrationFormatter()
    formatter.max_chatgpt_message_chars = 460
    article = ResolvedArticle(
        canonical_url="https://example.com/article",
        original_url="https://example.com/article",
        final_url="https://example.com/article",
        title="Boundary Test",
        subtitle=None,
        source=None,
        author=None,
        published_at=None,
        body_text="Alpha. " * 18 + "\n\n" + "Beta. " * 18,
    )

    requests = formatter.build_requests(article)

    alpha_chunks = [request.prompt_text for request in requests if "Alpha." in request.prompt_text]
    beta_chunks = [request.prompt_text for request in requests if "Beta." in request.prompt_text]

    assert alpha_chunks
    assert beta_chunks
    assert all("Beta." not in prompt_text for prompt_text in alpha_chunks)
    assert all("Alpha." not in prompt_text for prompt_text in beta_chunks)


def test_cleaner_splits_oversized_paragraph_safely() -> None:
    formatter = NarrationFormatter()
    formatter.max_chatgpt_message_chars = 340
    article = ResolvedArticle(
        canonical_url="https://example.com/article",
        original_url="https://example.com/article",
        final_url="https://example.com/article",
        title="Sentence Test",
        subtitle=None,
        source=None,
        author=None,
        published_at=None,
        body_text=(
            "Sentence one is deliberately long enough to take space. "
            "Sentence two is deliberately long enough to take space. "
            "Sentence three is deliberately long enough to take space. "
            "Sentence four is deliberately long enough to take space."
        ),
    )

    requests = formatter.build_requests(article)

    assert len(requests) > 1
    assert "Sentence one" in requests[0].prompt_text
    assert any("Sentence four" in request.prompt_text for request in requests)
    assert all(
        len(request.prompt_text) <= formatter.max_chatgpt_message_chars for request in requests
    )


def test_cleaner_hard_splits_when_sentence_exceeds_budget() -> None:
    formatter = NarrationFormatter()
    formatter.max_chatgpt_message_chars = 320
    article = ResolvedArticle(
        canonical_url="https://example.com/article",
        original_url="https://example.com/article",
        final_url="https://example.com/article",
        title="Hard Split",
        subtitle=None,
        source=None,
        author=None,
        published_at=None,
        body_text="A" * 600,
    )

    requests = formatter.build_requests(article)

    assert len(requests) > 1
    assert all(
        len(request.prompt_text) <= formatter.max_chatgpt_message_chars for request in requests
    )
