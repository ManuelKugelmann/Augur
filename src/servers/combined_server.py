"""Combined trading server — signals store + 12 data domains in one process."""
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Ensure both src/servers/ and src/store/ are importable regardless of CWD
_here = Path(__file__).resolve().parent
_store_dir = str(_here.parent / "store")
_servers_dir = str(_here)
if _servers_dir not in sys.path:
    sys.path.insert(0, _servers_dir)
if _store_dir not in sys.path:
    sys.path.insert(0, _store_dir)

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("trading",
    instructions="Trading signals: store (profiles, snapshots, notes, risk gate) + 12 OSINT data domains (75+ sources)")

# Signals store (profiles, snapshots, charts, archival)
from server import mcp as store  # noqa: E402 — src/store/server.py

# 12 data domains (src/servers/*_server.py)
from weather_server import mcp as weather  # noqa: E402
from disasters_server import mcp as disaster  # noqa: E402
from macro_server import mcp as econ  # noqa: E402
from agri_server import mcp as agri  # noqa: E402
from conflict_server import mcp as conflict  # noqa: E402
from commodities_server import mcp as commodity  # noqa: E402
from health_server import mcp as health  # noqa: E402
from elections_server import mcp as politics  # noqa: E402
from transport_server import mcp as transport  # noqa: E402
from water_server import mcp as water  # noqa: E402
from humanitarian_server import mcp as humanitarian  # noqa: E402
from infra_server import mcp as infra  # noqa: E402

mcp.mount(store, namespace="store")
mcp.mount(weather, namespace="weather")
mcp.mount(disaster, namespace="disaster")
mcp.mount(econ, namespace="econ")
mcp.mount(agri, namespace="agri")
mcp.mount(conflict, namespace="conflict")
mcp.mount(commodity, namespace="commodity")
mcp.mount(health, namespace="health")
mcp.mount(politics, namespace="politics")
mcp.mount(transport, namespace="transport")
mcp.mount(water, namespace="water")
mcp.mount(humanitarian, namespace="humanitarian")
mcp.mount(infra, namespace="infra")

if __name__ == "__main__":
    import os
    transport_mode = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport_mode in ("streamable-http", "http"):
        port = int(os.environ.get("MCP_PORT", "8071"))
        mcp.run(transport="http", host="127.0.0.1", port=port,
                stateless_http=True)
    else:
        mcp.run(transport="stdio")
