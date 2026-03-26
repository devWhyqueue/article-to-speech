import json

from bs4 import BeautifulSoup

from article_to_speech.article.extractor import ArticleExtractor
from article_to_speech.article.extractor_support import _extract_archive_replay_text

ARTICLE_BODY = " ".join(
    [
        (
            "Paragraph one with enough words to look like a real article and establish the "
            "basic reporting context."
        ),
        "Paragraph two keeps going and adds a lot more context and supporting detail.",
        "Paragraph three continues the story with specific details and proper narrative flow.",
        "Paragraph four adds more words so the extractor crosses the completeness threshold.",
        "Paragraph five adds even more text to make this body long enough for the heuristics.",
        "Paragraph six exists to make the article clearly complete and not a teaser.",
        "Paragraph seven makes the total comfortably longer than the minimum word count.",
        "Paragraph eight adds more factual wording and keeps the structure realistic.",
        "Paragraph nine extends the body with extra descriptive sentences and concrete detail.",
        "Paragraph ten is here to push the extractor beyond the minimum word threshold.",
        "Paragraph eleven continues with additional context and reporting details.",
        "Paragraph twelve adds more plain prose so the body remains close to a full article.",
        "Paragraph thirteen contributes still more words and keeps the article complete.",
        "Paragraph fourteen closes out the test article with enough remaining language.",
        "Paragraph fifteen adds more wording to ensure the extractor treats it as complete.",
        "Paragraph sixteen extends the body again with several extra descriptive phrases.",
        "Paragraph seventeen includes plain reporting language and additional context.",
        "Paragraph eighteen exists solely to raise the total word count above the threshold.",
        "Paragraph nineteen adds several more words and keeps the test body realistic enough.",
        "Paragraph twenty contributes additional reporting context and descriptive language.",
        "Paragraph twenty one adds more plain prose so the extractor clearly accepts it.",
        "Paragraph twenty two keeps the article long and avoids teaser-like brevity.",
        "Paragraph twenty three supplies yet more words so the body is undeniably complete.",
        "Paragraph twenty four finishes the sample with extra detail and final context.",
    ]
)

EXAMPLE_HTML = f"""
<html>
  <head>
    <title>Fallback title</title>
    <meta property="og:title" content="Test Article" />
    <meta property="og:site_name" content="Example News" />
    <meta name="author" content="Jane Doe" />
    <meta property="article:published_time" content="2026-03-24T12:00:00Z" />
    <script type="application/ld+json">
      {{
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "Test Article",
        "articleBody": {json.dumps(ARTICLE_BODY)},
        "author": {{"@type": "Person", "name": "Jane Doe"}},
        "datePublished": "2026-03-24T12:00:00Z"
      }}
    </script>
  </head>
  <body>
    <article><p>Ignored fallback paragraph.</p></article>
  </body>
</html>
"""

PAYWALLED_DIRECT_HTML = f"""
<html data-is-truncated-by-paywall>
  <head>
    <title>Karin Prien | DIE ZEIT</title>
    <meta property="og:title" content='Karin Prien: "Ich möchte wirklich davor warnen zu sagen: Alle Männer sind so"' />
    <meta property="og:site_name" content="DIE ZEIT" />
    <script type="application/ld+json">
      {{
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "Karin Prien",
        "isAccessibleForFree": "False",
        "articleBody": {json.dumps(ARTICLE_BODY)}
      }}
    </script>
  </head>
  <body>
    <article>
      <h1>Z+ (abopflichtiger Inhalt); Karin Prien</h1>
      <p>{ARTICLE_BODY}</p>
    </article>
    <aside id="paywall"></aside>
  </body>
</html>
"""


def test_extractor_prefers_full_ld_json_body() -> None:
    extractor = ArticleExtractor()
    article = extractor.extract(
        url="https://example.com/article",
        final_url="https://example.com/article",
        html=EXAMPLE_HTML,
    )
    assert article is not None
    assert article.title == "Test Article"
    assert article.source == "Example News"
    assert article.author == "Jane Doe"
    assert article.published_at == "2026-03-24"
    assert article.paywalled is False
    assert "Paragraph seven" in article.body_text


def test_extractor_rejects_teaser_content() -> None:
    extractor = ArticleExtractor()
    teaser_html = """
    <html><body><article><p>Short teaser only.</p></article></body></html>
    """
    assert (
        extractor.extract(
            url="https://example.com/short",
            final_url="https://example.com/short",
            html=teaser_html,
        )
        is None
    )


def test_extractor_ignores_fides_privacy_overlay() -> None:
    extractor = ArticleExtractor()
    article_html = " ".join(f"Sentence {index} with enough words to look like article text." for index in range(1, 60))
    html = f"""
    <html>
      <head>
        <meta property="og:title" content="Overlay Test" />
      </head>
      <body>
        <div id="fides-modal">
          <div id="fides-consent-content">
            <h2>Manage Privacy Preferences</h2>
            <p>Cookies cookies cookies consent consent privacy privacy.</p>
          </div>
        </div>
        <article>
          <p>{article_html}</p>
        </article>
      </body>
    </html>
    """

    article = extractor.extract(
        url="https://example.com/overlay",
        final_url="https://example.com/overlay",
        html=html,
    )

    assert article is not None
    assert "Manage Privacy Preferences" not in article.body_text
    assert "Sentence 20" in article.body_text


def test_extractor_marks_paywalled_direct_page_incomplete() -> None:
    extractor = ArticleExtractor()

    article = extractor.extract(
        url="https://www.zeit.de/example",
        final_url="https://www.zeit.de/example",
        html=PAYWALLED_DIRECT_HTML,
    )

    assert article is not None
    assert article.paywalled is True
    assert extractor.is_incomplete(article) is True


def test_extractor_does_not_mark_archive_snapshot_incomplete_for_copied_paywall_text() -> None:
    extractor = ArticleExtractor()

    article = extractor.extract(
        url="https://www.zeit.de/example",
        final_url="https://archive.is/example",
        html=PAYWALLED_DIRECT_HTML,
    )

    assert article is not None
    assert article.paywalled is False
    assert extractor.is_incomplete(article) is False


def test_extractor_trims_to_title_and_drops_related_content() -> None:
    extractor = ArticleExtractor()
    paragraphs = "\n".join(
        f"<p>Paragraph {index} with enough extra words to keep the article realistic, complete, and clearly longer than a teaser snippet for extraction heuristics.</p>"
        for index in range(1, 25)
    )
    body = f"""
    <html>
      <head>
        <meta property="og:title" content="Exact Headline" />
      </head>
      <body>
        <article>
          <p>Bovino Interview</p>
          <p>Tracking ICE Activity</p>
          <p>Exact Headline</p>
          <p>Lead summary sentence for the article.</p>
          {paragraphs}
          <p>Related Content</p>
          <p>Unrelated module text should be removed.</p>
        </article>
      </body>
    </html>
    """

    article = extractor.extract(
        url="https://example.com/title-trim",
        final_url="https://example.com/title-trim",
        html=body,
    )

    assert article is not None
    assert article.body_text.startswith("Exact Headline")
    assert "Bovino Interview" not in article.body_text
    assert "Related Content" not in article.body_text


def test_extractor_prefers_archive_story_structure() -> None:
    extractor = ArticleExtractor()
    body_paragraphs = "\n".join(
        f"<div>Paragraph {index} contains enough reporting detail, complete sentences, and factual wording to look like a real archived news article body for extraction.</div>"
        for index in range(1, 25)
    )
    html = f"""
    <html>
      <head>
        <title>Snapshot - The New York Times</title>
        <meta property="article:published_time" content="2026-03-24T15:42:00Z" />
      </head>
      <body>
        <article id="story">
          <div>U.S. Immigration Crackdown Bovino Interview Tracking ICE Activity</div>
          <header>
            <div>Supported by SKIP ADVERTISEMENT</div>
            <div><h1>Supreme Court Seems Open to Trump Request to Block Asylum Seekers at Border</h1></div>
            <div class="article-summary">A policy of turning back many asylum seekers at the border was rescinded in 2021, but the Justice Department wants the flexibility to reinstate it as a tool for border control.</div>
            <div>By Ann E. Marimow Reporting from Washington</div>
            <div>March 24, 2026 Updated 3:42 p.m. ET</div>
          </header>
          <section>{body_paragraphs}</section>
          <div>Related Content More in Politics</div>
        </article>
      </body>
    </html>
    """

    article = extractor.extract(
        url="https://www.nytimes.com/example",
        final_url="https://archive.is/example",
        html=html,
    )

    assert article is not None
    assert article.trace == ("archive_story",)
    assert article.title == "Supreme Court Seems Open to Trump Request to Block Asylum Seekers at Border"
    assert article.source == "The New York Times"
    assert article.author == "Ann E. Marimow"
    assert article.published_at == "2026-03-24"
    assert article.body_text.startswith(
        "Supreme Court Seems Open to Trump Request to Block Asylum Seekers at Border"
    )
    assert "Bovino Interview" not in article.body_text
    assert "Related Content" not in article.body_text
    assert "Paragraph 20 contains enough reporting detail" in article.body_text


def test_extractor_prefers_archive_replay_article_body() -> None:
    extractor = ArticleExtractor()
    archive_blocks = [
        (
            "Die schwarz-rote Koalition wagt die Flucht nach vorn. Zumindest behaupten das "
            "ihre Spitzen, Bundeskanzler Friedrich Merz (CDU) und dessen Vize Lars Klingbeil "
            "(SPD). Das Land soll mit tiefgreifenden Reformen wieder fit gemacht werden, die "
            "Konjunktur soll anspringen, und ein großes Unterfangen steht im Raum."
        ),
        (
            "In den nächsten Wochen, so das Versprechen des Kanzlers, werde man sehr hart an "
            "einer Zukunftsagenda arbeiten. Bis Pfingsten könnte das Paket an Maßnahmen "
            "stehen, bis zum Sommer die Gesetzentwürfe fertig sein. Was genau ist geplant, "
            "was können Union und Sozialdemokraten durchsetzen, und was wäre wirklich sinnvoll?"
        ),
        (
            "Die Kosten für die sozialen Systeme laufen immer mehr aus dem Ruder. Bei den "
            "Krankenkassen klafft in den kommenden Jahren ein Defizit von 13 Milliarden Euro, "
            "das der Bund nicht mehr ausgleichen kann. Die Zuschüsse für die Rente betragen "
            "schon heute über 120 Milliarden Euro, und die Haushaltslücke bleibt groß."
        ),
        (
            "Einkommensteuer Weitgehend einig sind sich Union und SPD, dass die Belastung der "
            "Gehälter durch Steuern und Abgaben zurückgehen müsse. Vor allem Verdiener "
            "mittlerer und unterer Einkommen sollen wieder mehr Netto vom Brutto bekommen. "
            "Ökonomen unterstützen die Regierung in diesem Ansinnen, weil das mehr Menschen "
            "zur Arbeit motiviert."
        ),
        (
            "Mehrwertsteuer Um die Kosten für die Reformen wieder einzudämmen, könnte die "
            "Mehrwertsteuer angehoben werden. Sie ist im europäischen Vergleich relativ "
            "niedrig. Zwei Prozentpunkte mehr, also 21 Prozent, würden dem Staat rund 32 "
            "Milliarden Euro einbringen. Ein Kompromiss bestünde darin, die Mehrwertsteuer "
            "auf Lebensmittel weiter zu reduzieren."
        ),
        (
            "Mehr Arbeit Die Regierung kann nicht regeln, dass die Deutschen mehr arbeiten. "
            "Sie kann aber an Stellschrauben drehen, sodass mehr Menschen eine Beschäftigung "
            "aufnehmen. Die SPD will dafür das Ehegattensplitting abschaffen, das es bislang "
            "für Ehepartner finanziell unattraktiv machte, zu arbeiten."
        ),
        (
            "Rente Um die Milliardenzuschüsse des Staates für die Rentenbeiträge zu senken, "
            "könnte der Staat an das Renteneintrittsalter gehen. Außerdem könnte die starre "
            "Altersgrenze bei der Rente fallen. Die Liste der steuerlichen Privilegien, die "
            "gestrichen werden könnten, ist lang und politisch toxisch."
        ),
    ]
    html = f"""
    <html>
      <head>
        <meta property="og:title" content="Bewährungsprobe der Regierung: Mehrwertsteuer rauf, Ehegattensplitting weg? Das sind die Reformideen von Schwarz-Rot" />
        <meta property="og:site_name" content="DER SPIEGEL" />
        <meta name="author" content="Gerald Traufetter" />
        <title>Bundesregierung: Mehrwertsteuer rauf, Ehegattensplitting weg? Das sind die Reformideen - DER SPIEGEL</title>
      </head>
      <body>
        <div id="HEADER">archive.today webpage capture</div>
        <div id="CONTENT">
          <article>
            <header>
              <span>Bewährungsprobe der Regierung</span>
              <h1>Mehrwertsteuer rauf, Ehegattensplitting weg? Das sind die Reformideen von Schwarz-Rot</h1>
            </header>
            <div>
              <div>Zur Merkliste hinzufügen Artikel anhören (7 Minuten)</div>
              <section>
                <div>Bild vergrößern Koalitionäre Klingbeil (SPD) und Merz (CDU) im Kabinett Foto: Reuters</div>
                <div>Dieser Artikel gehört zum Angebot von SPIEGEL+. Sie können ihn auch ohne Abonnement lesen, weil er Ihnen geschenkt wurde.</div>
                <div></div>
                <div>
                  <div></div>
                  <div>{archive_blocks[0]}</div>
                  <div></div>
                  <section>Mehr zum Thema Teure Pläne von Union und SPD</section>
                  <div>{archive_blocks[1]} {archive_blocks[2]}</div>
                  <div></div>
                  <div>DEBATTE Sind Ihnen Leistungskürzungen lieber als wachsende Beiträge? Diskutieren Sie hier</div>
                  <div>{archive_blocks[3]}</div>
                  <div></div>
                  <div>{archive_blocks[4]}</div>
                  <div></div>
                  <div>{archive_blocks[5]}</div>
                  <div></div>
                  <div>{archive_blocks[6]}</div>
                  <div>DEBATTE Rettet die Reformagenda die SPD oder spaltet sie die Partei? Diskutieren Sie hier</div>
                </div>
              </section>
            </div>
            <footer>Startseite Feedback</footer>
          </article>
          <article>
            <header><h2>Another story</h2></header>
            <div><p>Short teaser that must not be preferred over the main article replay.</p></div>
          </article>
        </div>
      </body>
    </html>
    """

    article = extractor.extract(
        url="https://example.com/article",
        final_url="https://archive.is/example",
        html=html,
    )

    assert article is not None
    assert article.source == "DER SPIEGEL"
    assert article.author == "Gerald Traufetter"
    assert "Die schwarz-rote Koalition wagt die Flucht nach vorn." in article.body_text
    assert "Mehrwertsteuer Um die Kosten für die Reformen wieder einzudämmen" in article.body_text
    replay_text = _extract_archive_replay_text(BeautifulSoup(html, "lxml"))

    assert replay_text is not None
    assert "Mehr zum Thema" not in replay_text
    assert "Diskutieren Sie hier" not in replay_text
