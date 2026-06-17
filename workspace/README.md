# Applicant
───────────────────────────────────────────────
 ⊹ ࣪ ˖ ૮( ˶ᵔ ᵕ ᵔ˶ )っ  Applicant vers. 1.0
───────────────────────────────────────────────

![Applicant](docs/applicant.jpg)

A self-hosted AI workspace -- meant to be the self-hosted version of the UI experience you get from ChatGPT and Claude. But with more jank and fun. Running on your own hardware, with your own data -- local-first, privacy-first, and no trojan.

## Features
  - **Chat** -- chat with any local model or API; adding them is super simple.<br>　<sub>vLLM · llama.cpp · Ollama · OpenRouter · OpenAI</sub>
  - **Agent** -- hand it tools and let it run the whole task itself.<br>　<sub>built on [opencode](https://github.com/anomalyco/opencode) · MCP · web · files · shell · skills · memory</sub>
  - **Cookbook** -- Scans your hardware, recommends models, click to download and serve.. easy!<br>　<sub>built on [llmfit](https://github.com/AlexsJones/llmfit) · VRAM-aware · GGUF / FP8 / AWQ · fit scoring · vLLM / llama.cpp serving</sub>
  - **Deep Research** -- multi-step runs that gather, read, and synthesize sources into a nice visual report.<br>　<sub>adapted from [Tongyi DeepResearch](https://github.com/Alibaba-NLP/DeepResearch)</sub>
  - **Compare** -- a fun tool to compare models side by side. Test completely blind, no bias!<br>　<sub>multi-model · blind test · synthesis</sub>
  - **Documents** -- YOU write the text, AI is there to assist, not the opposite.<br>　<sub>multi-tab editor · markdown · HTML · CSV · syntax highlighting · AI edits · suggestions</sub>
  - **Memory / Skills** -- Persistent memory and skills, your agent evolves over time as it better understands you and your tasks!<br>　<sub>ChromaDB · fastembed (ONNX) · vector + keyword retrieval · import/export</sub>
  - **Email** -- IMAP/SMTP inbox with AI triage built in: urgency reminders, auto-tag, auto-summary, auto-reply drafts, auto-spam.<br>　<sub>IMAP · SMTP · per-account routing · CalDAV-aware</sub>
  - **Notes & Tasks** -- Quick notes with reminders, a todo list, and scheduled tasks the agent can act on.<br>　<sub>note pings · checklist · cron-style tasks · ntfy / browser / email channels</sub>
  - **Calendar** -- Local-first calendar with CalDAV sync to Radicale / Nextcloud / Apple / Fastmail.<br>　<sub>CalDAV pull · .ics import/export · per-calendar colors · agent-aware</sub>
  - **Works on mobile** -- looks and runs great on your phone, not just desktop.<br>　<sub>responsive · installable (PWA) · touch gestures</sub>
  - **Extras** -- more to explore, happy if you give it a go!<br>　<sub>image editor · theme editor · file uploads (vision + PDF) · web search · presets · sessions · 2FA</sub>

## Demo
A full, hover-to-play tour lives on the landing page (`docs/index.html`).

<details>
<summary>Screenshots / clips</summary>

### Chat & Agents
![Chat & Agents](docs/chat.gif)
### Deep Research
![Deep Research](docs/research.gif)
### Compare
![Compare](docs/compare.gif)
### Documents
![Documents](docs/document.gif)
### Notes & Tasks
![Notes & Tasks](docs/notes.gif)

</details>

## Quick Start

Defaults work out of the box: clone, run, then configure models/search/email
inside **Settings**. Only edit `.env` for deployment-level overrides like
`APP_BIND`, `APP_PORT`, `AUTH_ENABLED`, `DATABASE_URL`, or a pre-seeded admin password.

On first setup, Applicant creates an admin account (`admin` unless
`APPLICANT_ADMIN_USER` is set) and prints a temporary password in the terminal.
For Docker installs, the same line is in `docker compose logs applicant`.
Use that for the first login, then change it in **Settings**.

Contributing? See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, testing, and
pull request guidelines.

> 📚 **Full documentation lives in [`docs/`](docs/README.md)** —
> [Architecture](docs/architecture.md) ·
> [Configuration](docs/configuration.md) ·
> [Deployment](docs/deployment.md) ·
> [API Reference](docs/api.md) ·
> [Troubleshooting](docs/troubleshooting.md).

### Docker (recommended)
```bash
git clone https://github.com/kevinhirsch/applicant.git
cd applicant
cp .env.example .env       # optional, but recommended for explicit defaults
docker compose up -d --build
```
Open `http://localhost:7000` when the containers are healthy. Docker Compose
binds the web UI to `0.0.0.0` (all host interfaces) by default, so it is
reachable across the Docker host's network from the start. If the port is
taken, set `APP_PORT=7001` in `.env` and recreate the container. Set
`APP_BIND=127.0.0.1` to restrict the UI back to loopback only.

#### Updating
To pull the newest version from GitHub and restart:
```bash
./scripts/applicant-update            # backup data, pull code + images, rebuild & restart
```
It snapshots `data/` first, pulls the latest code and service images, then
rebuilds and recreates the containers. Your `data/` and `.env` are left in
place and the app runs its schema migrations automatically on startup. Pass
`--no-backup` to skip the snapshot.

### Native Linux / macOS
```bash
git clone https://github.com/kevinhirsch/applicant.git
cd applicant
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python setup.py
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```
Requirements: Python 3.11+. Cookbook also needs `tmux` for background model
downloads and serves. Use `--host 0.0.0.0` only when you intentionally want
LAN/reverse-proxy access.

### Apple Silicon
Docker on macOS cannot use the Metal GPU. For GPU-accelerated Cookbook on an
M-series Mac, run Applicant natively:

```bash
git clone https://github.com/kevinhirsch/applicant.git
cd applicant
./start-macos.sh
```

It launches at `http://127.0.0.1:7860`. To build a clickable app wrapper:

```bash
./build-macos-app.sh
```

<details>
<summary>Cookbook, GPU, Ollama, and troubleshooting notes</summary>

These topics now have dedicated guides:

- **Docker services, GPU overlays, Ollama, updating, backups, HTTPS** — [Deployment](docs/deployment.md).
- **Refused connections, port conflicts, ChromaDB, Ollama, and more** — [Troubleshooting](docs/troubleshooting.md).

</details>

### Native Windows

**One-command launcher** (creates the venv, installs deps, runs setup, starts the
server; safe to re-run):

```powershell
git clone https://github.com/kevinhirsch/applicant.git
cd applicant
powershell -ExecutionPolicy Bypass -File .\launch-windows.ps1
```

Or do it by hand:

```powershell
git clone https://github.com/kevinhirsch/applicant.git
cd applicant
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python setup.py
python -m uvicorn app:app --host 127.0.0.1 --port 7000
```

**Requirements:** Python 3.11+. The core app (chat, agent, memory, documents,
email, calendar, deep research) runs fully native. For full **Cookbook** background
model downloads and the agent shell tool, also install
[Git for Windows](https://git-scm.com/download/win) (provides `bash.exe`).
Local GPU *serving* of vLLM/SGLang needs Linux/WSL2; for a local model on Windows,
[Ollama](https://ollama.com/download) is the easiest path — point Applicant at
`http://localhost:11434/v1` in Settings.

Open `http://localhost:7000`, log in with the generated admin password,
and configure everything else inside **Settings**.

## Security Notes
Applicant is a self-hosted workspace with powerful local tools (shell, uploads,
model downloads, web research, email/calendar, API tokens) — treat it like an
admin console. The essentials:

- Keep `AUTH_ENABLED=true` for any network-accessible deployment, and put it
  behind HTTPS + a trusted reverse proxy before exposing it.
- Keep `data/`, `.env`, logs, databases, and uploaded/generated media out of Git
  (ignored by default).
- After first boot, review `data/auth.json`: disable open signup unless wanted,
  keep only your account admin, and keep demo/test users non-admin.
- Rotate any keys/tokens that appeared in a shared chat, demo, screenshot, or log.

See the [Security policy](SECURITY.md) for the full checklist and
[Deployment → HTTPS](docs/deployment.md#putting-it-behind-https) for the
reverse-proxy setup.

## Contributing
Help is welcome. The best entry points are fresh-install testing, provider setup
bugs, mobile/editor polish, docs, and small focused refactors. See
[ROADMAP.md](ROADMAP.md) for the current help-wanted list.

## Configuration
Most setup happens inside the app via `/setup` or **Settings**. Use `.env` only
for deployment-level defaults and secrets you want present before first boot —
bind address, port, auth toggles, the database URL, or a pre-seeded admin
password. The most common settings:

| Variable | Default | Description |
|---|---|---|
| `APP_BIND` | `0.0.0.0` | Docker host bind for the web UI. Set `127.0.0.1` for loopback only. |
| `APP_PORT` | `7000` | Docker host port for the web UI. |
| `AUTH_ENABLED` | `true` | Enable/disable login. |
| `DATABASE_URL` | `sqlite:///./data/app.db` | Database connection string. |
| `OPENAI_API_KEY` | — | Optional; prefer adding providers in the app. |

The complete environment-variable reference — every LLM, search, email,
ChromaDB, auth, and scheduling setting — is in
[Configuration](docs/configuration.md).

## Architecture
Applicant is a FastAPI app: a static SPA front end over a JSON/SSE API, with
business logic in `src/` and `services/`, infrastructure in `core/`, and
persistence in SQLite plus the `data/` directory (and optional ChromaDB for
semantic memory and search). All user data lives in `data/` (gitignored).

See [Architecture](docs/architecture.md) for the full breakdown — layout,
request flow, subsystems, storage, background work, and the auth model.

## Star History

<a href="https://www.star-history.com/?repos=kevinhirsch%2Fapplicant&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=kevinhirsch/applicant&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=kevinhirsch/applicant&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=kevinhirsch/applicant&type=date&legend=top-left" />
 </picture>
</a>

## License
MIT -- see [LICENSE](LICENSE) and [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md).

```
                                  |
                                 |||
                                |||||
                  |    |    |   |||||||
                 )_)  )_)  )_)   ~|~
                )___))___))___)\  |
               )____)____)_____)\\|
             _____|____|____|_____\\\__
             \                       /
       ~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~
               ~^~  all aboard!  ~^~
       ~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~~^~^~
```
