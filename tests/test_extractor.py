from __future__ import annotations

from pathlib import Path

from article_to_speech.article.extractor import ArticleExtractor

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "archive"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_extracts_zeit_archive_snapshot_as_markdown() -> None:
    article = ArticleExtractor().extract(
        url="https://www.zeit.de/2026/14/karin-prien-bundesfrauenministerin-gewalthilfegesetz-digitale-gewalt",
        final_url="https://archive.is/FEzwe",
        html=_fixture("zeit_FEzwe.html"),
    )

    assert article is not None
    assert article.source == "DIE ZEIT"
    assert article.title == 'Karin Prien: "Ich möchte wirklich davor warnen zu sagen: Alle Männer sind so"'
    assert article.subtitle == (
        "Menschen wollen in Partnerschaft leben, trotz allem. Ein Gespräch mit der "
        "Bundesfrauenministerin Karin Prien darüber, wie man Frauen schützt und Männer besser versteht."
    )
    assert article.author == "Elisabeth Raether und Bernd Ulrich"
    assert article.published_at == "2026-03-26"
    assert "##" in article.body_text
    assert "DIE ZEIT: Frau Prien" in article.body_text
    assert '"Sie brauchen mehr männliche Vorbilder"' in article.body_text
    assert "Diese Zusammenfassung wurde" not in article.body_text
    assert "Die Audioversion dieses Artikels" not in article.body_text
    assert "Exakt mein Gedankengang" not in article.body_text
    assert "<div" not in article.body_text


def test_extracts_spiegel_archive_snapshot_as_markdown() -> None:
    article = ArticleExtractor().extract(
        url="https://www.spiegel.de/kultur/example.html",
        final_url="https://archive.is/tLxbG",
        html=_fixture("spiegel_tLxbG.html"),
    )

    assert article is not None
    assert article.source == "DER SPIEGEL"
    assert (
        article.title
        == "Salzburger Festspiele Intendant Markus Hinterhäuser: Die Angst vor dem nächsten Ausraster"
    )
    assert article.subtitle == (
        "Der Intendant der Salzburger Festspiele steht vor der Ablösung, weil er gegen "
        "eine »Wohlverhaltensklausel« verstoßen haben soll. Dem SPIEGEL liegen Aussagen "
        "vor, laut denen er Mitarbeiterinnen schikaniert habe."
    )
    assert article.author == "Sebastian Hammelehle"
    assert article.published_at == "2026-03-26"
    assert "In der Lobby des Hamburger Hotels Vier Jahreszeiten" in article.body_text
    assert "Barpianist, das wäre vielleicht auch noch etwas für ihn" in article.body_text
    assert "Zur Merkliste hinzufügen" not in article.body_text
    assert "Dieser Artikel gehört zum Angebot von SPIEGEL+" not in article.body_text
    assert "<div" not in article.body_text


def test_extracts_nyt_archive_snapshot_as_markdown() -> None:
    article = ArticleExtractor().extract(
        url="https://www.nytimes.com/2026/03/26/world/europe/europe-iran-trump.html",
        final_url="https://archive.is/YTmQk",
        html=_fixture("nyt_YTmQk.html"),
    )

    assert article is not None
    assert article.source == "The New York Times"
    assert article.title == "Trump’s Threats to Europe Put Its Leaders in a Double Bind Over Iran"
    assert article.subtitle == (
        "European politicians risk angering their voters if they join America’s war. "
        "Yet they could also face domestic upheaval if they take no action to reopen "
        "shipping routes that Iran has blocked and ease an energy crisis."
    )
    assert article.author == "Mark Landler"
    assert article.published_at == "2026-03-26"
    assert "President Trump, in his latest broadside at Europe" in article.body_text
    assert "Iran’s de facto closure of the strategic waterway" in article.body_text
    assert "Advertisement" not in article.body_text
    assert "Share full article" not in article.body_text
    assert "<div" not in article.body_text


def test_extracts_sz_archive_snapshot_as_markdown() -> None:
    article = ArticleExtractor().extract(
        url="https://www.sueddeutsche.de/meinung/usa-trump-iran-krieg-kommentar-1.1234567",
        final_url="https://archive.is/uXKno",
        html=_fixture("sz_uXKno.html"),
    )

    assert article is not None
    assert article.source == "SZ.de"
    assert article.title == "USA: Der Krieg, der Tod, das Leid – sind für Trump nur ein Unterhaltungsspektakel"
    assert article.subtitle == (
        "So gut wie niemand weiß, welchem Zweck die Angriffe auf Iran dienen. "
        "So offensichtlich wie erschütternd dagegen ist die zur Schau gestellte Freude "
        "an der Gewalt dieser Regierung."
    )
    assert article.author == "Boris Herrmann"
    assert article.published_at == "2026-03-26"
    assert "Vor einer Gruppe von Republikanern erzählte Trump dieser Tage" in article.body_text
    assert "## Manchmal schlägt er einfach gerne zu" in article.body_text
    assert "Artikel anhören" not in article.body_text
    assert "Feedback" not in article.body_text
    assert "<div" not in article.body_text


def test_extracts_faz_archive_snapshot_as_markdown() -> None:
    article = ArticleExtractor().extract(
        url="https://www.faz.net/aktuell/politik/inland/klingbeils-kleiner-schroeder-moment-110425856.html",
        final_url="https://archive.is/iYzQJ",
        html=_fixture("faz_iYzQJ.html"),
    )

    assert article is not None
    assert article.source == "FAZ"
    assert article.title == "Rede über Reformen: Klingbeils kleiner Schröder-Moment"
    assert article.subtitle == (
        "Der SPD-Vorsitzende will eine andere SPD. Einige seiner Vorschläge dürften "
        "der eigenen Partei nicht gefallen. Kann er sich trotzdem durchsetzen?"
    )
    assert article.author == "Mona Jaeger"
    assert article.published_at == "2026-03-26"
    assert "Wer ist Lars Klingbeil? Viel!" in article.body_text
    assert "## Klingbeil will den Linksruck verhindern" in article.body_text
    assert "Zur App" not in article.body_text
    assert "Mehr zum Thema" not in article.body_text
    assert "<div" not in article.body_text


def test_extracts_zeit_archive_without_page_heading() -> None:
    article = ArticleExtractor().extract(
        url="https://www.zeit.de/wirtschaft/2026-03/altersvorsorge-riester-rente-etf-depot-faq",
        final_url="https://archive.is/example",
        html="""
<!DOCTYPE html>
<html lang="de">
  <head>
    <title>Private Altersvorsorge: So funktioniert die neue private Altersvorsorge | DIE ZEIT</title>
  </head>
  <body>
    <main>
      <article>
        <header>
          <h1>Private Altersvorsorge: So funktioniert die neue private Altersvorsorge</h1>
        </header>
        <div>Ab 2027 startet eine neue staatliche Förderung für die Altersvorsorge.</div>
        <h3>Artikelzusammenfassung</h3>
        <p>Diese Zusammenfassung wurde mithilfe von Künstlicher Intelligenz erstellt.</p>
        <p>
          Die Reform der privaten Altersvorsorge soll ein altes Problem lösen: Viele
          Riester-Verträge waren teuer, kompliziert und renditeschwach.
        </p>
        <h2>Was sich 2027 ändert</h2>
        <p>Das neue Modell setzt stärker auf kostengünstige Depots und klarere Regeln.</p>
      </article>
    </main>
  </body>
</html>
""",
    )

    assert article is not None
    assert article.title == "Private Altersvorsorge: So funktioniert die neue private Altersvorsorge"
    assert article.subtitle == "Ab 2027 startet eine neue staatliche Förderung für die Altersvorsorge."
    assert (
        "Die Reform der privaten Altersvorsorge soll ein altes Problem lösen" in article.body_text
    )
    assert "## Was sich 2027 ändert" in article.body_text
    assert "Diese Zusammenfassung wurde" not in article.body_text
