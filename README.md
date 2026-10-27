# Nexora

Factory price research for **hospital consumables** (syringes, masks, gloves, cannulas, urine bags).
Built for dealers in India who want to know, before negotiating:

1. **What it costs to make**, per unit in ₹, with sources.
2. **The lowest and highest price manufacturers sell it at**, with direct links and a calculator
   (units, GST, freight).

Drop a photo or paste the requirement. The app finds the items, asks only the questions needed to pin
down the variant, and searches nothing until you press **Start research**. Products made of parts get an
optional **Split and research** button.

Research only: no ordering or payments. India and INR only. Manufacturers only (their own sites, or
IndiaMART / TradeIndia / ExportersIndia when the seller is the maker); retail pharmacies are blocked.
Medicines are out of scope.

## Quick start (Windows)

Needs Python 3.11+ and Node 20+.

1. Copy `backend\.env.example` to `backend\.env` and set `OPENAI_API_KEY`, `OPENAI_MODEL`,
   `OPENAI_VISION_MODEL` and `TAVILY_API_KEY`.
2. `.\start.ps1` installs everything on first run and starts:
   - App: <http://localhost:5173>
   - API: <http://localhost:8015>
   - Public: <https://nexora.softsuaveai.space> through a Cloudflare Tunnel to port 5173 (Vite also
     proxies `/api`, so one port serves everything). The tunnel `nexora` and its DNS record are created on
     first run with the machine's `cloudflared` login. Use `.\start.ps1 -NoTunnel` for local only.
3. `.\stop.ps1` stops everything (including the tunnel). After editing `backend\.env`, run
   `.\stop.ps1; .\start.ps1`.

> The public URL has no login. Anyone with the link can run research (spending OpenAI credit) and see
> results. Put a Cloudflare Access policy on the hostname before sharing it.

## Configuration

All settings live in `backend/.env` and override machine-wide variables. Main ones:

| Key | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | | Required |
| `OPENAI_MODEL`, `OPENAI_VISION_MODEL` | | Required. Currently `gpt-4o-mini` |
| `TAVILY_API_KEY` | | Search and page extract. Without it, OpenAI web search only |
| `BUDGET_PAGES`, `BUDGET_LLM_CALLS` | 30, 30 | Pages and AI calls per item (main cost driver) |
| `ITEM_TIMEOUT_SECONDS` | 180 | Time limit per item |
| `RESEARCH_CONCURRENCY` | 2 | Items researched at once |
| `APP_NAME` | PharmaSource | Name in logs; final name not chosen |

Full list: [backend/.env.example](backend/.env.example). The Settings page shows what is configured
(never the keys).

## How it works

See [ARCHITECTURE.md](ARCHITECTURE.md) for the three LangGraph graphs and the rules that keep numbers
honest. In short: every price must be found word for word on the page it links to, unclear sellers show
as Unconfirmed, and wrong variants or box prices are kept out of the range.

## Status

| Area | State |
|---|---|
| Intake, research, cost, sanity checks, run queue, web app | Built and tested (555 backend, 143 frontend tests) |
| Live accuracy | Run 5: right product and lowest price for syringe, mask, gloves, cannula |
| Not yet verified live | Split and research; latest cost changes (cost after search, bulk pricing) |

Known limitations: cost cards are rough (process steps are estimates), the AI may still estimate a cost
above market (shown as Low confidence), MOQ text is sometimes missed. Details in
[docs/research/eval-log.md](docs/research/eval-log.md).

> **Security:** the OpenAI and Tavily keys were shared in a chat during the build. Rotate them, and
> never commit `backend/.env`.

## Checks

```powershell
cd backend;  .venv\Scripts\python -m pytest -q;  .venv\Scripts\ruff check .
cd frontend; npm test;  npm run build;  npm run lint
```

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md): graphs, nodes, rules, code map
- [docs/API.md](docs/API.md): endpoints
- [docs/WORKFLOW.md](docs/WORKFLOW.md): node-by-node detail
- [docs/research/eval-log.md](docs/research/eval-log.md): live runs
- [docs/superpowers/specs/2026-10-26-factory-price-research-design.md](docs/superpowers/specs/2026-10-26-factory-price-research-design.md): design spec
