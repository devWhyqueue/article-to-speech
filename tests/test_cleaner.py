from article_to_speech.article.cleaner import NarrationFormatter
from article_to_speech.core.models import ResolvedArticle


def test_cleaner_preserves_article_text_in_single_chunk() -> None:
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
    chunks = formatter.build_chunks(article)

    assert len(chunks) == 1
    assert chunks[0].text.startswith("Example\n\nSubtitle")
    assert "<text>" not in chunks[0].text
    assert "Part 1 of" not in chunks[0].text
    assert "Section" in chunks[0].text
    assert "Paragraph one." in chunks[0].text
    assert "Paragraph two." in chunks[0].text


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


def test_cleaner_trims_trailing_related_content_sections() -> None:
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
            "The court appeared likely to let the administration move ahead.\n\n"
            "See more on: U.S. Politics, American Civil Liberties Union, U.S. Supreme Court, Donald Trump\n\n"
            "Related Content\n\n"
            "More in Politics\n\n"
            "In South Dakota, Neighbors Feel Sorry for Kristi Noem's Husband\n\n"
            "Trending in The Times\n\n"
            "Opinion: The Epstein Class Had a Signature Weakness"
        ),
    )

    cleaned = formatter.clean_article_text(article)

    assert "The court appeared likely to let the administration move ahead." in cleaned
    assert "See more on:" not in cleaned
    assert "Related Content" not in cleaned
    assert "Trending in The Times" not in cleaned


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


def test_cleaner_chunks_long_article_into_multiple_chunks() -> None:
    formatter = NarrationFormatter()
    formatter.max_tts_input_bytes = 450
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

    chunks = formatter.build_chunks(article)

    assert len(chunks) > 1
    assert "Example" in chunks[0].text
    assert "Subtitle" in chunks[0].text
    assert all("<text>" not in chunk.text for chunk in chunks)
    assert all("Part " not in chunk.text for chunk in chunks)
    assert all(len(chunk.text.encode("utf-8")) <= formatter.max_tts_input_bytes for chunk in chunks)
    assert all("Example" not in chunk.text for chunk in chunks[1:])
    assert all("Subtitle" not in chunk.text for chunk in chunks[1:])


def test_cleaner_prefers_paragraph_boundaries_when_chunking() -> None:
    formatter = NarrationFormatter()
    formatter.max_tts_input_bytes = 220
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

    chunks = formatter.build_chunks(article)

    alpha_chunks = [chunk.text for chunk in chunks if "Alpha." in chunk.text]
    beta_chunks = [chunk.text for chunk in chunks if "Beta." in chunk.text]

    assert alpha_chunks
    assert beta_chunks
    assert all("Beta." not in chunk_text for chunk_text in alpha_chunks)
    assert all("Alpha." not in chunk_text for chunk_text in beta_chunks)


def test_cleaner_splits_oversized_paragraph_safely() -> None:
    formatter = NarrationFormatter()
    formatter.max_tts_input_bytes = 180
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

    chunks = formatter.build_chunks(article)

    assert len(chunks) > 1
    assert "Sentence one" in chunks[0].text
    assert any("Sentence four" in chunk.text for chunk in chunks)
    assert all(len(chunk.text.encode("utf-8")) <= formatter.max_tts_input_bytes for chunk in chunks)


def test_cleaner_hard_splits_when_sentence_exceeds_budget() -> None:
    formatter = NarrationFormatter()
    formatter.max_tts_input_bytes = 320
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

    chunks = formatter.build_chunks(article)

    assert len(chunks) > 1
    assert all(len(chunk.text.encode("utf-8")) <= formatter.max_tts_input_bytes for chunk in chunks)
