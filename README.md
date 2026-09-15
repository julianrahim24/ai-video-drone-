# Risk-Gated Robinhood Trading System

A disciplined trading assistant with two modes - **PAPER** (simulated, default)
and **LIVE** (real money) - that sizes every trade from a 1-10 risk level you
set, runs a full pre-trade checklist before anything is proposed, and never
submits a live order without your explicit approval.

## API research (read this first)

Before writing any broker code, this project checked what programmatic access
to Robinhood actually, legitimately exists as of September 2026:

- **Equities & options**: Robinhood has no standalone, documented REST API for
  placing stock/option orders. The only officially-sanctioned programmatic
  path is **Robinhood Agentic Trading** (launched May 2026), which runs over
  MCP (Model Context Protocol) and requires an MCP-capable agent session
  (Claude Code, Claude Desktop, ChatGPT) connected with your Robinhood
  authorization, plus a mandatory order-preview step. There is no documented
  way for an unattended standalone script to authenticate to it on its own.
- **Crypto**: Robinhood publishes an **official, documented Crypto Trading
  API** (`https://trading.robinhood.com`), with API keys you generate
  yourself in your Robinhood crypto account settings and Ed25519-signed
  requests. This can be, and is, implemented as a real standalone broker.

**What this means in practice:**

| Mode | Equities / Options | Crypto |
|---|---|---|
| Paper | Fully simulated, fully functional | Fully simulated, fully functional |
| Live | Cannot be submitted by this script alone. Approved orders are queued to `logs/agentic_bridge/pending_orders.jsonl` and must be executed by an MCP-connected agent session with Robinhood's Agentic Trading tools (e.g. this project opened in Claude Code with the Robinhood connector enabled). | Fully functional against the official Crypto Trading API, once you set your own API credentials. |

This isn't a workaround-in-waiting: it's the actual boundary of what
Robinhood currently allows without scraping, bypassing MFA, or using a
private/undocumented endpoint - all of which were explicitly ruled out.
If Robinhood publishes a standalone equities API later, only
`trading/broker/robinhood_agentic_bridge.py` needs to change.

## Safety design

- **Starts in PAPER every single run.** Live mode is never persisted; you
  must type `ENABLE LIVE TRADING` via `/live` every session.
- **Every trade goes through one risk engine** (`trading/risk/risk_engine.py`)
  that checks, in order: asset-class/feature gates (options/leverage),
  market-data staleness, liquidity, volatility ceiling, event risk
  (earnings), signal confidence, daily loss limit, open-position count,
  risk-based position sizing, cash, portfolio exposure, symbol/sector
  concentration, and an absolute position-size cap. Any failure returns a
  specific, human-readable reason and nothing is proposed.
- **Approval is required by default** for both paper and live orders
  (`/approve` / `/reject`); `/autoexec on` removes that gate for live orders
  only if you explicitly turn it on, and prints a warning when you do.
- **Master kill switch** (`trading/execution/kill_switch.py`): trips on a
  duplicate order, an order whose status can't be confirmed, or a manual
  `/stop`, and persists to disk so a crash/restart can't silently clear it.
  Reset requires typing the exact phrase `I UNDERSTAND THE RISK`.
- **Never assumes an order succeeded.** If the broker call errors or returns
  an unresolved status, the order manager checks the broker's own order
  status before doing anything else, and trips the kill switch rather than
  guessing (`trading/execution/order_manager.py`).
- **Duplicate-order protection** via a same-day fingerprint
  (symbol/side/quantity/price) - a second matching order is refused and
  trips the kill switch.
- **Secrets never touch source or git.** Robinhood crypto API credentials and
  the market-data API key are read from environment variables only
  (`.env`, gitignored); nothing asks for your password, MFA code, or session
  cookie.

## Architecture

```
trading/
  broker/        Broker interface + paper, Robinhood crypto (real, official API),
                  and the Robinhood Agentic Trading queue bridge for equities/options
  data/          Market data providers (Finnhub - real, documented, free-tier;
                  a synthetic offline provider for tests/demos)
  analysis/      Technical indicators + a bounded, heuristic confidence/risk score
  risk/          Risk-level table, position sizing, portfolio limits, stop-loss calc,
                  and the risk engine that ties them together
  execution/     Kill switch + order manager (idempotency, duplicate protection,
                  never-assume-success verification)
  strategy/      "Find me a trade" watchlist scanner
  paper/         Simulated portfolio state (JSON-persisted)
  ui/            CLI dashboard and command loop
logs/            trading_events.jsonl (structured), trading.log (human-readable),
                  paper_portfolio.json, kill_switch.json, order_fingerprints.json
tests/           pytest suite for the risk engine, position sizing, kill switch,
                  order manager, paper engine, and analysis engine
```

Every layer only talks to the layer below through an abstract interface
(`Broker`, `MarketDataProvider`), so the Robinhood connection can be replaced
without touching risk logic, and risk logic can be tested without any network
access at all (see `trading/data/synthetic_provider.py`).

## Risk levels

| Level | Label | Max risk/trade | Options | Leverage |
|---|---|---|---|---|
| 1-2 | Very Conservative | 1.0% | No | No |
| 3-4 | Conservative | 1.5% | No | No |
| 5-6 | Moderate | 2.0% | Only if `/options on` | No |
| 7-8 | Aggressive | 3.0% | Only if `/options on` | No |
| 9-10 | Very Aggressive | 5.0% | Only if `/options on` | Only if `/leverage on` |

Position size is always computed from **how much you're willing to lose**
(risk level x portfolio value / stop-loss distance), then hard-capped by the
account's absolute position-size, cash, and concentration limits - never the
other way around.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in FINNHUB_API_KEY (free at finnhub.io) for real market data;
                        # crypto live trading needs your own Robinhood crypto API keys too
python main.py
```

Without `FINNHUB_API_KEY`, the app runs on a clearly-labeled synthetic data
provider - useful for trying the CLI, never for real decisions.

## Running the tests

```bash
pytest -q
```

The suite specifically exercises the required fail-safe scenarios: an
oversized position, the daily loss limit, portfolio exposure, insufficient
cash, stale market data, duplicate orders, and trading after the kill switch
has been tripped - each must be refused, never allowed through.

## Using it

```
> find me a trade
JNJ
Signal: BUY
Shares: 8
Current Price: $223.32
...
Use /approve to submit this trade, or /reject to discard it.
> /approve
```

Run `/help` inside the app for the full command list.
