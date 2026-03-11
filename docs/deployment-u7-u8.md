# Deployment: Uberspace 7 vs Uberspace 8

Step-by-step deployment for both Uberspace generations. The installer (`augur install`) is version-agnostic — these notes explain what differs under the hood and what to watch for.

---

## Quick Comparison

| Feature | Uberspace 7 (U7) | Uberspace 8 (U8) |
|---------|-------------------|-------------------|
| **OS** | CentOS 7 | **Arch Linux** |
| **Python** | `python3.12` (explicit version binary) | `python3` (system, **3.14**) |
| **Node.js** | `uberspace tools version use node 22` | System-provided (**v25+**, no version management) |
| **Process manager** | **supervisord** (`~/etc/services.d/`) | **systemd** (`~/.config/systemd/user/`) |
| **Web routing** | `uberspace web backend set / --http --port 3080` | `uberspace web backend add / port 3080` |
| **Service commands** | `supervisorctl start/stop/restart/status` | `systemctl --user start/stop/restart/status` |
| **SSH** | `ssh user@user.uber.space` | same |
| **RAM** | ~1.5 GB soft limit | ~1.5 GB soft limit |
| **Storage** | 10 GB (expandable) | 10 GB (expandable) |
| **MongoDB** | External (Atlas M0) | External (Atlas M0) |
| **Docker** | Not available | Not available |

The installer auto-detects U7 vs U8 (via `/etc/arch-release`) and uses the correct commands for each. You don't need to do anything different — just run the one-liner.

---

## Prerequisites (Both U7 and U8)

1. **Uberspace account** — https://uberspace.de (~5 EUR/mo, pay what you want)
2. **MongoDB Atlas M0** — https://cloud.mongodb.com (free, 512 MB)
3. **At least one LLM API key** — Anthropic, OpenAI, Groq (free tier), Gemini (free tier), etc.
4. **GitHub account** — https://github.com (free)

---

## Step 1: Set Up MongoDB Atlas (5 min)

This is identical for U7 and U8 — MongoDB runs externally.

1. Go to https://cloud.mongodb.com → create a **free M0** cluster
2. Create a database user (username + strong password)
3. **Network Access → Add IP Address → `0.0.0.0/0`**
   - Uberspace has no static IP, so you must allow all IPs
   - The database user password is the real access control
4. Click **Connect → Drivers** → copy the connection string:
   ```
   mongodb+srv://youruser:yourpass@cluster0.xxxxx.mongodb.net/
   ```
5. You'll use two databases on the same cluster:
   - `LibreChat` — LibreChat internal data
   - `signals` — trading signals store

---

## Step 2: SSH into Uberspace

```bash
ssh youruser@youruser.uber.space
```

Replace `youruser` with your actual Uberspace username. Both U7 and U8 use the same SSH pattern.

### Verify your environment

```bash
# Check Uberspace generation
cat /etc/os-release
# U7: CentOS Linux 7
# U8: Arch Linux

# Check available Python
python3 --version        # U8: works directly (3.14)
python3.12 --version     # U7: usually available

# Check Node.js
node -v                  # may not be set yet — installer handles this
```

---

## Step 3: Run the Installer (one-liner)

```bash
curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/Augur.sh?$(date +%s)" | bash
```

This single command does the same thing on both U7 and U8:

1. **Sets Node.js 22** via `uberspace tools version use node 22`
2. **Clones the repo** → `~/augur/`
3. **Finds Python 3.10+** — scans `python3.13` → `python3.12` → `python3.11` → `python3.10` → `python3`
   - U7 typically resolves to `python3.12`
   - U8 typically resolves to `python3` (which is 3.11+)
4. **Creates Python venv** + installs dependencies (`fastmcp`, `httpx`, `pymongo`, etc.)
5. **Downloads LibreChat** release bundle from GitHub Releases
6. **Registers supervisord services**: `librechat`, `trading`, `charts`
7. **Sets web backends**: `/` → port 3080 (LibreChat), `/charts` → port 8066
8. **Installs `augur` shortcut** → `~/bin/augur`

### What if Python is missing? (U7 edge case)

On older U7 hosts, Python 3.10+ might not be pre-installed. The installer will fail with:

```
✗ Python 3.10+ not found. On U7: check python3.12 --version. On U8: check python3 --version.
```

Fix for U7:
```bash
# U7: request Python via Uberspace support or check available versions
ls /opt/rh/rh-python*/root/usr/bin/python3* 2>/dev/null
# If python3.12 is available but not in PATH:
export PATH="/opt/rh/rh-python312/root/usr/bin:$PATH"
# Then re-run the installer
```

On U8 this is not an issue — Python 3.11+ is always available as `python3`.

---

## Step 4: Configure .env Files (2 min)

The installer creates two `.env` files that need your secrets. If you're in an interactive terminal, it offers to open `nano` for each one. If piped via `curl | bash`, it prints the paths.

### 4a. Signals stack (`~/augur/.env`)

```bash
nano ~/augur/.env
```

**Required:**
```bash
MONGO_URI_SIGNALS=mongodb+srv://youruser:yourpass@cluster0.xxxxx.mongodb.net/signals
```

**Optional API keys** (most data sources work without):
```bash
# FRED_API_KEY=           # US macro data
# ACLED_API_KEY=           # conflict/protest data
# EIA_API_KEY=             # energy data
```

### 4b. LibreChat (`~/LibreChat/.env`)

```bash
nano ~/LibreChat/.env
```

**Required:**
```bash
MONGO_URI=mongodb+srv://youruser:yourpass@cluster0.xxxxx.mongodb.net/LibreChat

# At least one LLM provider:
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# GROQ_API_KEY=gsk_...         # free: https://console.groq.com/keys
# GEMINI_API_KEY=AI...          # free: https://aistudio.google.com/apikey
```

Crypto keys (`CREDS_KEY`, `JWT_SECRET`, etc.) are auto-generated by the installer.

> **Tip:** If you set `MONGO_URI` in the LibreChat `.env` before running `augur install`, the installer auto-derives `MONGO_URI_SIGNALS` (same cluster, `signals` database).

---

## Step 5: Start Services

The `augur` command abstracts U7/U8 differences, but you can also use native commands:

**Using `augur` (recommended, works on both):**
```bash
augur restart
augur status
```

**Native commands (if you prefer):**
```bash
# U7 (supervisord)
supervisorctl start librechat
supervisorctl start trading

# U8 (systemd)
systemctl --user start librechat
systemctl --user start trading
```

Expected `augur status` output:
```
librechat: RUNNING
trading: RUNNING
charts: RUNNING
Version: 1.6.1+abc1234
Host: youruser.uber.space
Platform: U8 (Arch/systemd)    # or: U7 (CentOS/supervisord)
```

### Troubleshooting startup

```bash
# U7
supervisorctl tail librechat stderr
supervisorctl tail trading stderr

# U8
journalctl --user -u librechat -f
journalctl --user -u trading -f

# Or just use augur:
augur logs
```

---

## Step 6: Access and Register

Open in browser:
```
https://youruser.uber.space
```

Register your first account — **this becomes the admin**.

### Seed pre-built agents (optional)

After registering, seed the trading agents:
```bash
augur agents you@example.com yourpassword
```

Preview without changes:
```bash
augur agents --dry-run
```

---

## Step 7: Git-Versioned Data Backup (optional, 5 min)

1. Create a **private** repo on GitHub: `YourUser/Augur_Data`
2. Run:
   ```bash
   bash ~/augur/augur-uberspace/scripts/setup-data-repo.sh
   ```
3. Add the SSH public key it prints to your GitHub repo's deploy keys
4. Verify cron is set up:
   ```bash
   crontab -l | grep augur
   # */15 * * * * ~/bin/augur cron 2>&1 | logger -t augur-cron
   ```

---

## Step 8: Health Check

```bash
augur check
```

Checks: stack repo, Python venv, Node.js, LibreChat install, `.env` files, supervisord services, HTTP connectivity, profiles, cron, script syntax.

For the full test suite:
```bash
augur check --test
```

---

## Day-to-Day Operations (Same on U7 and U8)

```bash
augur help           # all commands
augur status         # services + version + host
augur logs           # tail LibreChat logs
augur restart        # restart LibreChat + trading
augur version        # installed version

augur pull           # dev: git pull + restart (no release needed)
augur update         # prod: download latest release bundle
augur install        # re-run full installer (idempotent)
augur rollback       # restore previous version

augur sync           # force git sync of data
augur check          # health check

augur env            # edit LibreChat .env
augur yaml           # edit librechat.yaml
augur conf           # edit deploy.conf
```

### Dev workflow

```bash
# On your dev machine:
git push

# On Uberspace:
augur pull
# → git pull + pip install + restart
```

### Production release

```bash
# On dev machine:
git tag v0.3.0 && git push --tags
# → CI builds bundle → GitHub Release

# On Uberspace:
augur update
# → downloads release, atomic swap, restart
```

---

## U7 vs U8: Key Differences in Practice

### Process management

| Action | U7 (supervisord) | U8 (systemd) |
|--------|-------------------|---------------|
| Start | `supervisorctl start librechat` | `systemctl --user start librechat` |
| Stop | `supervisorctl stop librechat` | `systemctl --user stop librechat` |
| Restart | `supervisorctl restart librechat` | `systemctl --user restart librechat` |
| Status | `supervisorctl status` | `systemctl --user status` |
| Logs | `supervisorctl tail -f librechat` | `journalctl --user -u librechat -f` |
| Service files | `~/etc/services.d/librechat.ini` | `~/.config/systemd/user/librechat.service` |

**You don't need to remember these.** The `augur` command abstracts them:
```bash
augur status    # works on both
augur restart   # works on both
augur logs      # works on both
```

### Web routing

| | U7 | U8 |
|---|---|---|
| Set backend | `uberspace web backend set / --http --port 3080` | `uberspace web backend add / port 3080` |
| Remove | `uberspace web backend del /` | same |
| List | `uberspace web backend list` | same |

The installer uses the correct syntax automatically.

### Node.js

| | U7 | U8 |
|---|---|---|
| Version management | `uberspace tools version use node 22` | Not available (system-provided) |
| Default version | Set by user (recommend 22) | System default (v25+) |

### Python binary name

| | U7 | U8 |
|---|---|---|
| Default Python 3 | `python3.12` (explicit version) | `python3` (system, 3.14) |
| Fallback | May need `python3.11` or `python3.10` | Always works |
| `PYTHON_VERSION` override | Set in `deploy.conf` if needed | Not needed |

The installer scans all candidates automatically (`python3.14` → `python3.13` → ... → `python3`). Only set `PYTHON_VERSION` in `deploy.conf` if automatic detection picks the wrong one.

### Filesystem paths

Identical on both except service files. All paths use `$HOME` and `~/`:
- `~/augur/` — Augur repo
- `~/LibreChat/` — LibreChat installation
- `~/Augur_Data/` — git-versioned data
- `~/bin/augur` — ops CLI

---

## Migrating from U7 to U8

If Uberspace migrates your account from U7 to U8 (or you create a new U8 account):

1. **On the old U7 host** — back up your config:
   ```bash
   augur backup                           # MongoDB backup
   cat ~/augur/.env                     # copy signals config
   cat ~/LibreChat/.env                # copy LibreChat config
   ```

2. **On the new U8 host** — run the installer:
   ```bash
   curl -sL "https://raw.githubusercontent.com/ManuelKugelmann/Augur/main/Augur.sh?$(date +%s)" | bash
   ```

3. **Restore config** — paste your saved `.env` contents:
   ```bash
   nano ~/augur/.env                    # paste signals config
   nano ~/LibreChat/.env               # paste LibreChat config
   ```

4. **Start services:**
   ```bash
   augur restart
   augur status
   ```

5. **Restore MongoDB** (if needed):
   ```bash
   augur restore path/to/backup.json.gz
   ```

MongoDB Atlas is external, so if you keep the same cluster, your data is already there — no restore needed.

---

## Resource Budget

| Component | ~RAM | Notes |
|-----------|------|-------|
| LibreChat (Node.js) | 500–800 MB | `--max-old-space-size=1024` |
| Trading server (Python) | ~80 MB | Single process, all 12 domains |
| Charts server (Python) | ~30 MB | Plotly chart endpoint |
| **Total** | **~600–900 MB** | Fits within 1.5 GB limit |

Same on both U7 and U8.

---

## Cost

| Service | Cost |
|---------|------|
| Uberspace | ~5 EUR/mo (pay what you want, min 1 EUR) |
| MongoDB Atlas M0 | Free (512 MB) |
| GitHub | Free |
| LLM APIs | Per-use (many free tiers) |
| **Total** | **~5 EUR/mo + LLM usage** |
