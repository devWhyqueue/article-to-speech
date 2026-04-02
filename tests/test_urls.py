from article_to_speech.core.urls import extract_first_url, normalize_url


def test_extract_first_url() -> None:
    text = "Please read https://example.com/article?utm_source=test&x=1 thanks"
    assert extract_first_url(text) == "https://example.com/article?utm_source=test&x=1"


def test_normalize_url_strips_tracking_parameters() -> None:
    assert (
        normalize_url("https://Example.com/news?id=2&utm_source=abc&fbclid=123")
        == "https://example.com/news?id=2"
    )


def test_normalize_url_strips_spiegel_share_parameter() -> None:
    assert (
        normalize_url(
            "https://www.spiegel.de/politik/deutschland/story?sara_ref=re-so-app-sh&id=2"
        )
        == "https://www.spiegel.de/politik/deutschland/story?id=2"
    )


def test_normalize_url_strips_faz_share_parameter() -> None:
    assert (
        normalize_url(
            "https://www.faz.net/aktuell/politik/inland/story.html?share=androidfaznativeshare"
        )
        == "https://www.faz.net/aktuell/politik/inland/story.html"
    )
