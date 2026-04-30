from __future__ import annotations

from pathlib import Path

import pytest

from article_to_speech.article.extractor import ArticleExtractor
from article_to_speech.core.exceptions import ArchivedPaywallError

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "archive"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_extracts_spektrum_archive_snapshot_as_markdown() -> None:
    article = ArticleExtractor().extract(
        url=(
            "https://www.spektrum.de/news/"
            "was-ein-schimpansen-buergerkrieg-ueber-menschliche-konflikte-verraet/2319030"
        ),
        final_url="https://archive.is/PqXGV",
        html=_fixture("spektrum_PqXGV.html"),
    )

    assert article is not None
    assert article.source == "Spektrum.de"
    assert article.title == "Was ein Schimpansen-Bürgerkrieg über menschliche Konflikte verrät"
    assert article.author == "Lars Fischer"
    assert article.published_at == "2026-04-10"
    assert (
        article.subtitle
        and "Die Geschichte einer rätselhaften Schimpansengemeinschaft in Uganda hat eine unerwartete"
        in article.subtitle
    )
    assert "Welche Schlüsse sich daraus für menschliche Gemeinschaften" in article.body_text
    assert "© EyeEm Mobile GmbH / Getty Images / iStock / Getty Images Plus (Ausschnitt)" not in article.body_text
    assert "Schwindender sozialer Zusammenhalt innerhalb von Schimpansengruppen" not in article.body_text
    assert "Das könnte Sie auch interessieren" not in article.body_text
    assert "Digitalpaket: Krieg und Frieden" not in article.body_text
    assert "Diesen Artikel empfehlen" not in article.body_text
    assert "WEITERLESEN MIT »SPEKTRUM +«" not in article.body_text
    assert "Artikel zum Thema" not in article.body_text
    assert "Themenkanäle" not in article.body_text
    assert "SponsoredPartnerinhalte" not in article.body_text
    assert "<div" not in article.body_text


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


def test_extracts_spiegel_archive_snapshot_ctofu_as_markdown() -> None:
    article = ArticleExtractor().extract(
        url=(
            "https://www.spiegel.de/karriere/"
            "hirnforschung-warum-pausen-das-gehirn-zu-besseren-ideen-fuehren-"
            "a-4d7f82de-4d58-4bf0-b641-aa74510afd0d"
        ),
        final_url="https://archive.is/CToFU",
        html=_fixture("spiegel_CToFU.html"),
    )

    assert article is not None
    assert article.source == "DER SPIEGEL"
    assert article.title == "Hirnforschung: Warum Pausen das Gehirn zu besseren Ideen führen"
    assert (
        article.subtitle
        == "Der Neurowissenschaftler Joseph Jebelli erforscht das Ruhenetzwerk im Gehirn – "
        "und erklärt, wie wir auf brillante Ideen kommen. Ein Gespräch über Leere, "
        "Tagträume und warum die meisten von uns es ihrem Hirn grundlos schwer machen."
    )
    assert article.author == "Stefan Boes"
    assert article.published_at == "2025-08-01"
    assert "SPIEGEL: Herr Jebelli" in article.body_text
    assert "Jebelli: Es gibt viele Wege, dem Gehirn Erholung zu verschaffen" in article.body_text
    assert "SPIEGEL: Wie sähe ein gehirnfreundlicher Arbeitstag aus?" in article.body_text
    assert (
        "Irgendwann habe ich begriffen, dass ich meinem Gehirn das Leben "
        "grundlos schwer gemacht habe."
    ) in article.body_text
    assert "Anzeige" not in article.body_text
    assert "Bei Amazon bestellen" not in article.body_text
    assert "Preisabfragezeitpunkt" not in article.body_text
    assert "DER SPIEGEL Zur Startseite" not in article.body_text


def test_rejects_spiegel_archive_snapshot_that_only_contains_paywall() -> None:
    html = """
<!DOCTYPE html>
<html lang="de">
  <head>
    <title>Analyse zur Bundesregierung - DER SPIEGEL</title>
  </head>
  <body>
    <main>
      <article>
        <h1>Analyse zur Bundesregierung</h1>
        <h2>Wie sich die Koalition in den kommenden Wochen sortieren muss.</h2>
        <div>DER SPIEGEL</div>
        <div>SPIEGEL+</div>
        <div>Mehr Perspektiven, mehr verstehen.</div>
        <div>Inklusive digitaler Ausgabe des wöchentlichen Magazins.</div>
        <div>4 Wochen für 1 Euro</div>
        <div>Jetzt anmelden</div>
        <div>Bereits Abonnent? Hier einloggen.</div>
        <div>Als Abonnent:in können Sie diesen Monat noch 3 Artikel verschenken.</div>
        <div>Verschenkte Artikel sind ohne Abonnement lesbar.</div>
      </article>
    </main>
  </body>
</html>
"""

    with pytest.raises(
        ArchivedPaywallError, match="Archive snapshot still shows the SPIEGEL\\+ paywall"
    ):
        ArticleExtractor().extract(
            url="https://www.spiegel.de/politik/deutschland/example.html",
            final_url="https://archive.is/example",
            html=html,
        )


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


def test_extracts_spiegel_archive_without_embedded_media_controls() -> None:
    article = ArticleExtractor().extract(
        url="https://www.spiegel.de/ausland/example.html",
        final_url="https://archive.is/example",
        html="""
<!DOCTYPE html>
<html lang="de">
  <head>
    <title>Iran-Krieg: Interview mit einem Experten - DER SPIEGEL</title>
  </head>
  <body>
    <main>
        <article>
          <h1>Iran-Krieg: Interview mit einem Experten</h1>
          <h2>Ein Gespräch über die Lage im Nahen Osten.</h2>
        <div>SPIEGEL: Wie ist die Lage, nachdem die jüngsten Angriffe die Region weiter destabilisiert haben?</div>
        <div>Vaez: Sie bleibt sehr angespannt. Weitere Eskalation ist möglich, wenn keine Seite politischen Spielraum für Gespräche schafft.</div>
        <div>
          Trumps Ansprache zum Irankrieg. 0 seconds of 1 minute, 35 seconds Volume 90%.
          Tastaturkürzel. Shortcuts Open/Close / or? Spielen/Pause Leertaste.
          Weitere Videos. Als Nächstes.
        </div>
        <div>SPIEGEL: Was müsste jetzt passieren, damit beide Seiten den Konflikt wieder unter Kontrolle bringen?</div>
        <div>Vaez: Beide Seiten müssten politischen Spielraum für Verhandlungen schaffen und die öffentliche Eskalationsspirale durchbrechen.</div>
      </article>
    </main>
  </body>
</html>
""",
    )

    assert article is not None
    assert "SPIEGEL: Wie ist die Lage, nachdem die jüngsten Angriffe" in article.body_text
    assert "Vaez: Beide Seiten müssten politischen Spielraum" in article.body_text
    assert "Spielen/Pause" not in article.body_text
    assert "Tastaturkürzel" not in article.body_text
    assert "Weitere Videos" not in article.body_text


def test_extracts_spiegel_archive_without_nested_teaser_articles() -> None:
    article = ArticleExtractor().extract(
        url=(
            "https://www.spiegel.de/ausland/"
            "viktor-orban-abgewaehlt-demokratien-koennen-sich-selbst-heilen-"
            "ungarn-hat-es-gerade-bewiesen-a-8a39144a-57d8-4945-8bdf-e968c2de83c2"
        ),
        final_url="https://archive.is/example",
        html="""
<!DOCTYPE html>
<html lang="de">
  <head>
    <title>Demokratien können sich selbst heilen. Ungarn hat es gerade bewiesen - DER SPIEGEL</title>
  </head>
  <body>
    <main>
      <article aria-label="Demokratien können sich selbst heilen. Ungarn hat es gerade bewiesen">
        <h2>Der SPIEGEL-Leitartikel von Mathieu von Rohr</h2>
        <h1>Demokratien können sich selbst heilen. Ungarn hat es gerade bewiesen</h1>
        <div>
          Viktor Orbán war das Vorbild für autoritäre Rechte von Washington bis Warschau.
          Nach seiner historischen Niederlage müssen sie ihr Drehbuch neu schreiben.
        </div>
        <div>Von Mathieu von Rohr</div>
        <time datetime="2026-04-15T08:00:00Z">15.04.2026, 08.00 Uhr</time>
        <div>
          Selten hat eine Wahl in einem so kleinen Land weltweit so viel Aufmerksamkeit
          erhalten. Ungarn hat kaum mehr Einwohner als die Schweiz, eine Wirtschaft so
          groß wie die Region München – und doch ist es zum Testfall für eine Frage
          geworden, die weit über das Land hinausweist: Lässt sich ein autoritäres
          System wie das Viktor Orbáns noch demokratisch abwählen – und wenn ja, wie?
        </div>
        <div>
          Die Antwort fiel so klar aus, wie es vor wenigen Monaten kaum jemand für
          möglich gehalten hätte: Die Tisza-Partei des Oppositionsführers Péter Magyar
          kommt auf 138 der 199 Sitze – mehr als eine Zweidrittelmehrheit.
        </div>
        <h2>Kein Kulturkampf</h2>
        <div>
          Magyar ließ sich von dieser Unzufriedenheit ins Amt tragen. Er verweigerte
          sich Orbáns Lieblingsthema: dem Kulturkampf. Mit Migrations- und Genderfragen
          kam der Premier nicht an gegen den Konservativen, der einst selbst zu Fidesz
          gehörte.
        </div>
        <div>
          Dennoch hat Ungarn in dieser Nacht Geschichte geschrieben. Demokratien können
          sich selbst heilen. Der Autoritarismus ist nach dieser Nacht keineswegs am
          Ende, aber sein Siegeszug ist kein Naturgesetz.
        </div>
        <section>
          <article aria-label="Cancer drugs are getting more expensive">
            <div>Cancer drugs are getting more expensive, and patients are paying the price.</div>
          </article>
          <article aria-label="Melania Trump keeps a careful distance">
            <div>Melania Trump keeps a careful distance from the campaign trail.</div>
          </article>
        </section>
      </article>
    </main>
  </body>
</html>
""",
    )

    assert article is not None
    assert article.source == "DER SPIEGEL"
    assert article.title == "Demokratien können sich selbst heilen. Ungarn hat es gerade bewiesen"
    assert article.subtitle and "Viktor Orbán war das Vorbild für autoritäre Rechte" in article.subtitle
    assert "Nach seiner historischen Niederlage müssen sie ihr Drehbuch neu schreiben." in (
        article.subtitle
    )
    assert article.author == "Mathieu von Rohr"
    assert article.published_at == "2026-04-15"
    assert "Selten hat eine Wahl in einem so kleinen Land" in article.body_text
    assert "## Kein Kulturkampf" in article.body_text
    assert "Dennoch hat Ungarn in dieser Nacht Geschichte geschrieben." in article.body_text
    assert "Cancer drugs are getting more expensive" not in article.body_text
    assert "Melania Trump keeps a careful distance" not in article.body_text
