"""Pytest conftest — mock heavy dependencies before store module imports them.

In CI (where pymongo/cffi imports cleanly), mongomock provides a full
in-memory MongoDB for tests. In Claude Code sandbox (broken cffi/pyo3),
pymongo is replaced with a MagicMock and tests use a lightweight
_FakeCollection fallback. See _USE_MONGOMOCK flag.
"""
import sys
from unittest.mock import MagicMock

# Mock dotenv if not installed (only load_dotenv is used at module level)
if "dotenv" not in sys.modules:
    try:
        import dotenv as _real_dotenv  # noqa: F401
        del _real_dotenv
    except ImportError:
        mock_dotenv = MagicMock()
        mock_dotenv.load_dotenv = lambda *a, **kw: None
        sys.modules["dotenv"] = mock_dotenv

# Detect whether real pymongo can import (cffi/cryptography chain).
# Must happen before mongomock import since mongomock imports pymongo.
_USE_MONGOMOCK = False
if "pymongo" not in sys.modules:
    try:
        import pymongo as _real_pymongo  # noqa: F401
        # pymongo imports OK → mongomock will work in CI
        _USE_MONGOMOCK = True
        del _real_pymongo
    except BaseException:
        # Sandbox: cffi/cryptography broken (pyo3 PanicException), mock pymongo
        mock_pymongo = MagicMock()
        mock_pymongo.MongoClient = MagicMock
        sys.modules["pymongo"] = mock_pymongo


# Mock fastmcp (v3 API changes; we only need the @mcp.tool() decorator to be a no-op)
if "fastmcp" not in sys.modules:
    mock_fastmcp = MagicMock()

    class _FakeMCP:
        def __init__(self, name="", **kw):
            self.name = name
            self._tools = {}

        def tool(self, *a, **kw):
            """Decorator that registers and returns the function unchanged."""
            def decorator(fn):
                self._tools[fn.__name__] = fn
                return fn
            return decorator

        def mount(self, child, namespace=""):
            """Collect tools from child with namespace prefix."""
            for name, fn in getattr(child, "_tools", {}).items():
                prefixed = f"{namespace}_{name}" if namespace else name
                self._tools[prefixed] = fn

        async def list_tools(self):
            """Return tool descriptors."""
            class _ToolInfo:
                def __init__(self, name):
                    self.name = name
            return [_ToolInfo(n) for n in sorted(self._tools)]

        def run(self, **kw):
            pass

    mock_fastmcp.FastMCP = _FakeMCP
    sys.modules["fastmcp"] = mock_fastmcp

    # Provide fastmcp.server.dependencies with a stub get_http_headers
    # so _get_user_id() / _get_user_key() can import it (raises RuntimeError
    # by default — same as when there's no active HTTP request).
    mock_server = MagicMock()
    mock_deps = MagicMock()

    def _stub_get_http_headers():
        raise RuntimeError("No active HTTP request (test stub)")

    mock_deps.get_http_headers = _stub_get_http_headers
    mock_server.dependencies = mock_deps
    mock_fastmcp.server = mock_server
    sys.modules["fastmcp.server"] = mock_server
    sys.modules["fastmcp.server.dependencies"] = mock_deps
