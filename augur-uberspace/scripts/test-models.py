#!/usr/bin/env python3
"""Test all configured LLM providers and models from librechat.yaml.

Sends a tiny completion request to each provider/model combo and reports
pass/fail. Skips providers whose API key env var is empty.

Usage:
    python test-models.py <librechat.yaml> [--timeout SECS]
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

import yaml

TIMEOUT = 10  # seconds per request


def resolve_env(val):
    """Resolve ${VAR} references in strings."""
    if not isinstance(val, str):
        return val
    match = re.match(r"^\$\{(\w+)\}$", val.strip())
    if match:
        return os.environ.get(match.group(1), "")
    return val


def load_endpoints(yaml_path):
    """Extract custom endpoints from librechat.yaml."""
    with open(yaml_path) as f:
        cfg = yaml.safe_load(f) or {}
    endpoints = cfg.get("endpoints", {})
    custom = endpoints.get("custom", [])
    if not isinstance(custom, list):
        return []
    return custom


def test_model(base_url, api_key, model, timeout):
    """Send a tiny chat completion and return (ok, detail)."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Say ok"}],
        "max_tokens": 3,
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
            text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
            if isinstance(text, list):
                text = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in text)
            return True, (text or "").strip()[:40] or "(empty response)"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode()[:120]
        except Exception:
            pass
        return False, f"HTTP {e.code}: {detail}"
    except Exception as e:
        return False, str(e)[:120]


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <librechat.yaml> [--timeout SECS]")
        sys.exit(1)

    yaml_path = sys.argv[1]
    timeout = TIMEOUT
    if "--timeout" in sys.argv:
        idx = sys.argv.index("--timeout")
        if idx + 1 < len(sys.argv):
            timeout = int(sys.argv[idx + 1])

    if not os.path.isfile(yaml_path):
        print(f"Error: {yaml_path} not found", file=sys.stderr)
        sys.exit(1)

    endpoints = load_endpoints(yaml_path)
    if not endpoints:
        print("No custom endpoints found in config.")
        sys.exit(0)

    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    NC = "\033[0m"

    total = 0
    passed = 0
    skipped = 0
    failed = 0

    for ep in endpoints:
        name = ep.get("name", "?")
        base_url = ep.get("baseURL", "")
        api_key_raw = ep.get("apiKey", "")
        api_key = resolve_env(api_key_raw)
        models = ep.get("models", {}).get("default", [])

        if not api_key or api_key in ("dummy", ""):
            print(f"\n{YELLOW}⊘ {name}{NC} — skipped (no API key for {api_key_raw})")
            skipped += 1
            continue

        print(f"\n{CYAN}● {name}{NC}  {base_url}")
        for model in models:
            total += 1
            ok, detail = test_model(base_url, api_key, model, timeout)
            if ok:
                print(f"  {GREEN}✓{NC} {model}  → {detail}")
                passed += 1
            else:
                print(f"  {RED}✗{NC} {model}  → {detail}")
                failed += 1

    print(f"\n{'─' * 50}")
    print(f"Results: {GREEN}{passed} passed{NC}, {RED}{failed} failed{NC}, {YELLOW}{skipped} skipped{NC} ({total} tested)")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
