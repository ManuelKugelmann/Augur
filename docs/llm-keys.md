# LLM Keys & Endpoints

Complete reference for LLM provider credentials used with LibreChat.
All keys go in `~/LibreChat/.env` (or via `augur env`).

At least one LLM provider is required. You can use multiple simultaneously.

---

## Quick Setup

**Native providers** (OpenAI, Anthropic): just set the key in `.env` — auto-detected.

1. Sign up at the provider URL
2. Copy your API key
3. Add it to `~/LibreChat/.env` (via `augur env`)
4. Restart: `augur restart`

**Custom providers** (Groq, Gemini, Mistral, etc.): need a YAML endpoint block too.

1. Set the key in `.env`
2. Add the endpoint block to `librechat-user.yaml` (via `augur yaml`)
3. Restart: `augur restart`

---

## Free Tier Providers

All providers below offer free API tiers (rate-limited, no billing required).
Add the endpoint block to `librechat-user.yaml` (`augur yaml`) to enable.

Reference: [cheahjs/free-llm-api-resources](https://github.com/cheahjs/free-llm-api-resources)

### Groq -- Fastest free inference

| | |
|---|---|
| **Signup** | https://console.groq.com/keys |
| **Free limits** | 14,400 req/day (varies by model), 6K-30K tokens/min |
| **Best models** | `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768` |
| **Env var** | `GROQ_API_KEY=gsk_...` |
| **Notes** | Custom LPU hardware, extremely fast. Best free option for daily use. |

### Google Gemini -- Largest free context

| | |
|---|---|
| **Signup** | https://aistudio.google.com/apikey |
| **Free limits** | 15 RPM, 1M tokens/day (Gemini Flash) |
| **Best models** | `gemini-2.0-flash`, `gemini-2.0-flash-lite`, `gemini-1.5-flash` |
| **Env var** | `GEMINI_API_KEY=AI...` |
| **Notes** | Very generous token limits. 1M context on paid tier. |

### Mistral -- Best European provider

| | |
|---|---|
| **Signup** | https://console.mistral.ai/api-keys |
| **Free limits** | 1 req/sec, 500K tokens/min |
| **Best models** | `mistral-small-latest`, `codestral-latest` |
| **Env var** | `MISTRAL_API_KEY=...` |
| **Notes** | Codestral is great for code tasks. Free tier very generous. |

### Cerebras -- Fast open-model inference

| | |
|---|---|
| **Signup** | https://cloud.cerebras.ai |
| **Free limits** | 30 RPM, 14,400 req/day |
| **Best models** | `llama-3.3-70b`, `qwen-3-235b`, `llama-3.1-8b` |
| **Env var** | `CEREBRAS_API_KEY=csk-...` |
| **Notes** | Very fast inference on open models. |

### Cohere -- Command R family

| | |
|---|---|
| **Signup** | https://dashboard.cohere.com/api-keys |
| **Free limits** | 20 RPM, 1,000 req/month |
| **Best models** | `command-a-03-2025`, `command-r-plus-08-2024` |
| **Env var** | `COHERE_API_KEY=...` |
| **Notes** | Good for RAG use cases. Lower monthly limit but capable models. |

### SambaNova -- Trial credits

| | |
|---|---|
| **Signup** | https://cloud.sambanova.ai |
| **Free limits** | $5 trial credit (3 month expiry) |
| **Best models** | `DeepSeek-V3-0324`, `Meta-Llama-3.3-70B-Instruct`, `Qwen2.5-72B-Instruct` |
| **Env var** | `SAMBANOVA_API_KEY=...` |
| **Notes** | Very fast inference. Trial credits, not perpetual free tier. |

### HuggingFace -- Open model hub

| | |
|---|---|
| **Signup** | https://huggingface.co/settings/tokens |
| **Free limits** | Rate-limited free inference API |
| **Best models** | `Qwen/Qwen2.5-72B-Instruct`, `meta-llama/Llama-3.3-70B-Instruct` |
| **Env var** | `HF_API_KEY=hf_...` |
| **Notes** | Huge model selection. Some models may have queue times. |

### GitHub Models -- Free via GitHub PAT

| | |
|---|---|
| **Signup** | https://github.com/settings/tokens (PAT with no scopes needed) |
| **Free limits** | Rate-limited, generous for personal use |
| **Best models** | `gpt-4o-mini`, `Meta-Llama-3.1-405B-Instruct`, `Mistral-large-2411`, `Phi-4` |
| **Env var** | `GITHUB_MODELS_PAT=ghp_...` |
| **Notes** | Uses your GitHub account. Access via [GitHub Marketplace Models](https://github.com/marketplace?type=models). |

### Alibaba Cloud / Qwen -- Free 1M tokens/month

| | |
|---|---|
| **Signup** | https://dashscope.console.aliyun.com/apiKey |
| **Free limits** | 1M free tokens/month, rate-limited |
| **Best models** | `qwen-plus`, `qwen-turbo`, `qwen-max`, `qwen-long` |
| **Env var** | `DASHSCOPE_API_KEY=sk-...` |
| **Notes** | Alibaba's Qwen family. International endpoint. [Landing page](https://www.alibabacloud.com/en/campaign/qwen-ai-landing-page). |

### OpenRouter -- Aggregator with free models

| | |
|---|---|
| **Signup** | https://openrouter.ai/keys |
| **Free limits** | 20 RPM, 50 req/day (free models only, `:free` suffix) |
| **Best models** | `google/gemini-2.0-flash-exp:free`, `meta-llama/llama-3.3-70b-instruct:free` |
| **Env var** | `OPENROUTER_API_KEY=sk-or-...` |
| **Notes** | Aggregates many providers. Free models marked with `:free`. Also has paid models (see below). |

### Recommended Free Combo

For a free multi-model LibreChat setup, use these 3 together:

1. **Groq** -- daily driver (fast, high limits)
2. **Gemini** -- large context tasks (1M tokens/day)
3. **Mistral** -- code tasks (Codestral)

---

## Paid Providers

### OpenAI -- GPT-4o, o1, o3

| | |
|---|---|
| **Signup** | https://platform.openai.com/api-keys |
| **Pricing** | Pay-per-token, prepaid credits |
| **Best models** | `gpt-4o`, `gpt-4o-mini`, `o3-mini` |
| **Env var** | `OPENAI_API_KEY=sk-...` |
| **Notes** | Native LibreChat endpoint (no custom config needed). Set in `.env` and it works. |

### Anthropic -- Claude Opus, Sonnet, Haiku

| | |
|---|---|
| **Signup** | https://console.anthropic.com/settings/keys |
| **Pricing** | Pay-per-token, prepaid credits |
| **Best models** | `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` |
| **Env var** | `ANTHROPIC_API_KEY=sk-ant-...` |
| **Notes** | Native LibreChat endpoint (no custom config needed). Set in `.env` and it works. |

### OpenRouter -- Multi-provider gateway (paid tier)

| | |
|---|---|
| **Signup** | https://openrouter.ai/keys |
| **Pricing** | Pay-per-token, $10+ credit gives 1000 req/day |
| **Best models** | All OpenAI, Anthropic, Google, Meta models via single key |
| **Env var** | `OPENROUTER_API_KEY=sk-or-...` |
| **Notes** | Recommended if you want access to all major models through one key. Same key works for free `:free` models too. |

### Google Gemini -- Paid tier

| | |
|---|---|
| **Signup** | https://aistudio.google.com/apikey |
| **Pricing** | Pay-per-token (same key as free tier, billing enabled) |
| **Best models** | `gemini-2.0-pro`, `gemini-2.0-flash` (higher limits) |
| **Env var** | `GEMINI_API_KEY=AI...` |
| **Notes** | Same key as free tier. Enable billing for higher rate limits and pro models. |

### Mistral -- Paid tier

| | |
|---|---|
| **Signup** | https://console.mistral.ai/api-keys |
| **Pricing** | Pay-per-token |
| **Best models** | `mistral-large-latest`, `codestral-latest` (higher limits) |
| **Env var** | `MISTRAL_API_KEY=...` |
| **Notes** | Same key as free tier. Enable billing for higher limits and large model access. |

---

## Claude Max Subscription

Use your Claude Pro/Max subscription as a LibreChat endpoint -- no per-token billing.

| | |
|---|---|
| **Requires** | Active Claude Pro or Max subscription |
| **Setup** | `augur proxy setup` (installs CLIProxyAPI, registers service) |
| **How it works** | CLIProxyAPI runs locally on `:8317`, translates OpenAI-compatible requests to Claude CLI |
| **Env var** | `CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...` (in `~/.claude-auth.env`) |
| **Full guide** | [docs/claude-token-wrapper.md](claude-token-wrapper.md) |

Add the "Claude Max" endpoint block to `librechat-user.yaml` (`augur yaml`) and restart.

---

## GitHub Secrets

Store LLM keys as GitHub repository secrets to enable CI validation.
Go to: **Settings > Secrets and variables > Actions > New repository secret**

| Secret name | Used by |
|---|---|
| `OPENAI_API_KEY` | LLM key check CI job |
| `ANTHROPIC_API_KEY` | LLM key check CI job |
| `OPENROUTER_API_KEY` | LLM key check CI job |
| `GROQ_API_KEY` | LLM key check CI job |
| `GEMINI_API_KEY` | LLM key check CI job |
| `MISTRAL_API_KEY` | LLM key check CI job |

All are optional -- the CI job skips providers whose secrets aren't set.

---

## Example .env

```bash
# ── Paid (pick at least one) ──
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...

# ── OpenRouter (one key, all models) ──
# OPENROUTER_API_KEY=sk-or-...

# ── Free providers (uncomment the ones you signed up for) ──
GROQ_API_KEY=gsk_abc123...
GEMINI_API_KEY=AIza...
# MISTRAL_API_KEY=...
# CEREBRAS_API_KEY=csk-...
# COHERE_API_KEY=...
# SAMBANOVA_API_KEY=...
# HF_API_KEY=hf_...
# GITHUB_MODELS_PAT=ghp_...
# DASHSCOPE_API_KEY=sk-...

# Enable custom endpoints
ENDPOINTS=openAI,anthropic,custom
```

Then add the corresponding endpoint blocks to `librechat-user.yaml` (`augur yaml`) and restart.

---

## Endpoint YAML Blocks

Custom providers need an endpoint block in `librechat-user.yaml` (`augur yaml`).
Copy the block(s) you need below. Set the matching key in `.env` first.

**Native providers** (OpenAI, Anthropic) need NO YAML — just the `.env` key.

```yaml
# Paste into librechat-user.yaml via: augur yaml
endpoints:
  custom:

    # ── Groq (free, very fast inference) ──
    - name: "Groq"
      apiKey: "${GROQ_API_KEY}"
      baseURL: "https://api.groq.com/openai/v1"
      models:
        default: [llama-3.3-70b-versatile, llama-3.1-8b-instant, mixtral-8x7b-32768, gemma2-9b-it]
        fetch: false  # true fetches all provider models — use false for curated list
      titleConvo: true
      titleModel: "llama-3.1-8b-instant"
      modelDisplayLabel: "Groq"

    # ── Google Gemini (free tier, 15 RPM / 1M TPD) ──
    - name: "Gemini"
      apiKey: "${GEMINI_API_KEY}"
      baseURL: "https://generativelanguage.googleapis.com/v1beta/openai/"
      models:
        default: [gemini-2.0-flash, gemini-2.0-flash-lite, gemini-1.5-flash]
        fetch: false
      titleConvo: true
      titleModel: "gemini-2.0-flash-lite"
      modelDisplayLabel: "Gemini"

    # ── Mistral (free tier: mistral-small, codestral) ──
    - name: "Mistral"
      apiKey: "${MISTRAL_API_KEY}"
      baseURL: "https://api.mistral.ai/v1"
      models:
        default: [mistral-small-latest, codestral-latest, mistral-large-latest]
        fetch: false
      titleConvo: true
      titleModel: "mistral-small-latest"
      modelDisplayLabel: "Mistral"

    # ── Cerebras (free, 30 RPM / 14.4K RPD) ──
    - name: "Cerebras"
      apiKey: "${CEREBRAS_API_KEY}"
      baseURL: "https://api.cerebras.ai/v1"
      models:
        default: [llama-3.3-70b, llama-3.1-8b, qwen-3-235b]
        fetch: false
      titleConvo: true
      titleModel: "llama-3.1-8b"
      modelDisplayLabel: "Cerebras"

    # ── Cohere (free, 20 RPM / 1K req/month) ──
    - name: "Cohere"
      apiKey: "${COHERE_API_KEY}"
      baseURL: "https://api.cohere.com/compatibility/v1"
      models:
        default: [command-a-03-2025, command-r-plus-08-2024, command-r-08-2024]
        fetch: false
      titleConvo: true
      titleModel: "command-r-08-2024"
      modelDisplayLabel: "Cohere"

    # ── SambaNova (free $5 trial credits) ──
    - name: "SambaNova"
      apiKey: "${SAMBANOVA_API_KEY}"
      baseURL: "https://api.sambanova.ai/v1"
      models:
        default: [DeepSeek-V3-0324, Meta-Llama-3.3-70B-Instruct, Qwen2.5-72B-Instruct]
        fetch: false
      titleConvo: true
      titleModel: "Meta-Llama-3.3-70B-Instruct"
      modelDisplayLabel: "SambaNova"

    # ── HuggingFace Inference (free tier) ──
    - name: "HuggingFace"
      apiKey: "${HF_API_KEY}"
      baseURL: "https://router.huggingface.co/v1"
      models:
        default: [Qwen/Qwen2.5-72B-Instruct, mistralai/Mistral-7B-Instruct-v0.3, meta-llama/Llama-3.3-70B-Instruct]
        fetch: false
      titleConvo: true
      titleModel: "mistralai/Mistral-7B-Instruct-v0.3"
      modelDisplayLabel: "HuggingFace"

    # ── GitHub Models (free, uses GitHub PAT) ──
    - name: "GitHub Models"
      apiKey: "${GITHUB_MODELS_PAT}"
      baseURL: "https://models.inference.ai.azure.com"
      models:
        default: [gpt-4o-mini, Meta-Llama-3.1-405B-Instruct, Mistral-large-2411, Phi-4]
        fetch: false
      titleConvo: true
      titleModel: "gpt-4o-mini"
      modelDisplayLabel: "GitHub Models"

    # ── Alibaba Cloud / Qwen (free 1M tokens/month) ──
    - name: "Qwen"
      apiKey: "${DASHSCOPE_API_KEY}"
      baseURL: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
      models:
        default: [qwen-plus, qwen-turbo, qwen-max, qwen-long]
        fetch: false
      titleConvo: true
      titleModel: "qwen-turbo"
      modelDisplayLabel: "Qwen"

    # ── OpenRouter (some free models with :free suffix) ──
    - name: "OpenRouter"
      apiKey: "${OPENROUTER_API_KEY}"
      baseURL: "https://openrouter.ai/api/v1"
      models:
        default:
          - "google/gemini-2.0-flash-exp:free"
          - "meta-llama/llama-3.3-70b-instruct:free"
          - "qwen/qwen-2.5-72b-instruct:free"
          - "mistralai/mistral-small-3.1-24b-instruct:free"
        fetch: false
      titleConvo: true
      titleModel: "meta-llama/llama-3.3-70b-instruct:free"
      modelDisplayLabel: "OpenRouter"

    # ── Claude Max (subscription via CLIProxyAPI) ──
    # Requires: augur proxy setup + token
    # See docs/claude-token-wrapper.md for full guide.
    - name: "Claude Max"
      apiKey: "dummy"
      baseURL: "http://localhost:8317/v1"
      models:
        default: [claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5-20251001]
        fetch: false
      titleConvo: true
      titleModel: "claude-sonnet-4-6"
      directEndpoint: true
      summarize: false
```

Only include the providers you have keys for. Delete blocks you don't need.

---

## Adding More Providers

Any OpenAI-compatible API can be added as a custom endpoint.
See the [LibreChat docs](https://www.librechat.ai/docs/configuration/librechat_yaml/ai_endpoints/custom)
and these resources for more options:
- [cheahjs/free-llm-api-resources](https://github.com/cheahjs/free-llm-api-resources)
- [leonardomontini.dev/free-llm-api](https://leonardomontini.dev/free-llm-api/)
