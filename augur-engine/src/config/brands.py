"""Brand configurations for all 4 Augur brands."""

from .types import BrandConfig, HorizonConfig, McpEndpoint, PaletteConfig

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

# Default MCP endpoint — the trading server with 50+ tools across 12 domains
_TRADING_MCP = McpEndpoint(url="http://localhost:8071/mcp", name="trading")

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
        mcp_endpoints=[_TRADING_MCP],
        research_prompt=(
            "Research the most significant geopolitical, environmental, or humanitarian "
            "development happening right now. Use weather, conflict, disaster, health, "
            "humanitarian, and macro-economic tools to gather concrete data points. "
            "Focus on events with measurable impact."
        ),
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
        mcp_endpoints=[_TRADING_MCP],
        research_prompt=(
            "Recherchiere die bedeutendste geopolitische, umweltbezogene oder humanitäre "
            "Entwicklung, die gerade stattfindet. Nutze Wetter-, Konflikt-, Katastrophen-, "
            "Gesundheits-, humanitäre und makroökonomische Tools, um konkrete Datenpunkte "
            "zu sammeln. Fokussiere auf Ereignisse mit messbarem Impact."
        ),
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
        mcp_endpoints=[_TRADING_MCP],
        research_prompt=(
            "Research current market-moving developments. Use macro-economic tools (FRED, "
            "World Bank, ECB), commodity price tools, and technical indicator tools to gather "
            "data on sector rotations, rate expectations, and supply chain disruptions. "
            "Check recent events for geopolitical risks impacting markets."
        ),
        social_targets=["x", "linkedin", "bluesky"],
        trade_system_feed="store_recent_events",
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
        mcp_endpoints=[_TRADING_MCP],
        research_prompt=(
            "Recherchiere aktuelle marktbewegende Entwicklungen. Nutze makroökonomische "
            "Tools (FRED, Weltbank, EZB), Rohstoffpreis-Tools und technische Indikator-Tools "
            "für Daten zu Sektorrotationen, Zinserwartungen und Lieferkettenstörungen. "
            "Prüfe aktuelle Ereignisse auf geopolitische Marktrisiken."
        ),
        social_targets=["x", "mastodon", "linkedin"],
        trade_system_feed="store_recent_events",
    ),
}
