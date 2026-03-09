"""Brand configurations for all 4 Augur brands."""

from .types import BrandConfig, HorizonConfig, PaletteConfig, SourceConfig

_EN_GENERAL_HORIZONS = [
    HorizonConfig("tomorrow", "tomorrow", "Tomorrow", "0 */6 * * *", "+1d"),
    HorizonConfig("soon", "soon", "Soon", "0 2 * * *", "+1m"),
    HorizonConfig("future", "future", "Future", "0 3 * * 1", "+1y"),
]

_DE_GENERAL_HORIZONS = [
    HorizonConfig("tomorrow", "morgen", "Morgen", "0 1,7,13,19 * * *", "+1d"),
    HorizonConfig("soon", "bald", "Bald", "0 4 * * *", "+1m"),
    HorizonConfig("future", "zukunft", "Zukunft", "0 5 * * 1", "+1y"),
]

_IMG_GENERAL = "Editorial documentary photograph, photojournalistic style, natural lighting, high detail, 35mm lens. "
_IMG_FINANCIAL = "Professional financial editorial photograph, Bloomberg terminal aesthetic, corporate environment, clean lighting. "

BRANDS: dict[str, BrandConfig] = {
    "the": BrandConfig(
        name="The Augur",
        slug="the",
        locale="en",
        module="general",
        masthead="THE AUGUR",
        subtitle="Foresight from the signal noise",
        horizons=_EN_GENERAL_HORIZONS,
        palette=PaletteConfig("#f4f0e8", "#1a1a1a", "#8b0000", "#6b5b4f"),
        image_style_prefix=_IMG_GENERAL,
        tone_prompt=(
            "You are a clear-eyed analyst writing for The Augur. Lead with the problem. "
            "Don't soften it. Then identify real, concrete, sourced efforts addressing it. "
            "Never fabricate solutions. If no credible solution exists, say so. Write in AP/Reuters style."
        ),
        legal_disclaimer="AI-generated speculation — not news. Not financial advice.",
        osint_sources=[
            SourceConfig("tavily", query="top geopolitical developments today"),
            SourceConfig("gdelt"),
            SourceConfig("rss", url="https://feeds.bbci.co.uk/news/world/rss.xml"),
            SourceConfig("rss", url="https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
        ],
        social_targets=["x", "bluesky", "facebook"],
    ),
    "der": BrandConfig(
        name="Der Augur",
        slug="der",
        locale="de",
        module="general",
        masthead="DER AUGUR",
        subtitle="Voraussicht aus dem Signalrauschen",
        horizons=_DE_GENERAL_HORIZONS,
        palette=PaletteConfig("#f4f0e8", "#1a1a1a", "#1a3a5c", "#6b5b4f"),
        image_style_prefix=_IMG_GENERAL,
        tone_prompt=(
            "Du bist ein nüchterner Analyst, der für Der Augur schreibt. Beginne mit dem Problem. "
            "Beschönige nichts. Identifiziere dann reale, konkrete, belegte Lösungsansätze. "
            "Erfinde keine Lösungen. Wenn keine glaubwürdige Lösung existiert, sage das. "
            "Schreibe im Stil von Reuters/DPA."
        ),
        legal_disclaimer="KI-generierte Spekulation — keine Nachricht. Keine Finanzberatung.",
        osint_sources=[
            SourceConfig("tavily", query="wichtigste geopolitische Entwicklungen heute"),
            SourceConfig("gdelt"),
            SourceConfig("rss", url="https://www.tagesschau.de/xml/rss2/"),
            SourceConfig("rss", url="https://www.spiegel.de/schlagzeilen/tops/index.rss"),
        ],
        social_targets=["x", "mastodon", "linkedin"],
    ),
    "financial": BrandConfig(
        name="Financial Augur",
        slug="financial",
        locale="en",
        module="markets",
        masthead="FINANCIAL AUGUR",
        subtitle="Market foresight from open signals",
        horizons=[
            HorizonConfig("tomorrow", "tomorrow", "Tomorrow", "0 2,8,14,20 * * *", "+1d"),
            HorizonConfig("soon", "soon", "Soon", "30 2 * * *", "+1m"),
            HorizonConfig("future", "future", "Future", "0 6 * * 1", "+1y"),
        ],
        palette=PaletteConfig("#f0f2f4", "#1a1a1a", "#0a6e3a", "#5a6570"),
        image_style_prefix=_IMG_FINANCIAL,
        tone_prompt=(
            "You are a financial analyst writing for Financial Augur. Focus on market signals, "
            "sector rotations, and macro trends. Cite specific data points. Assign confidence levels. "
            "Never recommend specific trades. Frame as sector-level opinion only."
        ),
        legal_disclaimer="AI-generated opinion — not financial advice. The Augur may hold positions in discussed sectors.",
        osint_sources=[
            SourceConfig("tavily", query="financial markets major developments today"),
            SourceConfig("yahoo"),
            SourceConfig("rss", url="https://feeds.bloomberg.com/markets/news.rss"),
            SourceConfig("trade"),
        ],
        social_targets=["x", "linkedin", "bluesky"],
        trade_system_feed="/tmp/sentiment.json",
    ),
    "finanz": BrandConfig(
        name="Finanz Augur",
        slug="finanz",
        locale="de",
        module="markets",
        masthead="FINANZ AUGUR",
        subtitle="Marktvoraussicht aus offenen Signalen",
        horizons=[
            HorizonConfig("tomorrow", "morgen", "Morgen", "0 3,9,15,21 * * *", "+1d"),
            HorizonConfig("soon", "bald", "Bald", "30 4 * * *", "+1m"),
            HorizonConfig("future", "zukunft", "Zukunft", "0 7 * * 1", "+1y"),
        ],
        palette=PaletteConfig("#f0f2f4", "#1a1a1a", "#0a6e3a", "#5a6570"),
        image_style_prefix=_IMG_FINANCIAL,
        tone_prompt=(
            "Du bist ein Finanzanalyst, der für Finanz Augur schreibt. Fokussiere auf Marktsignale, "
            "Sektorrotationen und Makrotrends. Zitiere spezifische Datenpunkte. Weise Konfidenzniveaus zu. "
            "Empfehle niemals spezifische Trades. Formuliere als Sektormeinung."
        ),
        legal_disclaimer="KI-generierte Einschätzung — keine Finanzberatung. Der Augur kann Positionen in besprochenen Sektoren halten.",
        osint_sources=[
            SourceConfig("tavily", query="Finanzmärkte wichtigste Entwicklungen heute"),
            SourceConfig("yahoo"),
            SourceConfig("rss", url="https://www.handelsblatt.com/contentexport/feed/top"),
            SourceConfig("trade"),
        ],
        social_targets=["x", "mastodon", "linkedin"],
        trade_system_feed="/tmp/sentiment.json",
    ),
}
