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
