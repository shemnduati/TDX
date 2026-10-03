# TDX — Paper Trading Bot + React Dashboard

A small crypto paper-trading bot (Python / ccxt) with a modern React
dashboard that renders balance, equity curve, open position, trade
history, and performance metrics (win rate, avg profit, max drawdown).

```
TDX/
├── bot.py              # Main trading loop
├── paper_trader.py     # PaperTrader (persists data.json + equity curve)
├── dashboard.py        # Flask API at http://127.0.0.1:5001
├── strategy.py         # Indicator + signal logic
├── exchange.py         # ccxt exchange factory
├── data.json           # Created at runtime by the trader
└── frontend/           # React + Vite + TS + Tailwind + Recharts UI
```

## 1. Run the backend

```powershell
# from the project root (Windows PowerShell)
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# start the Flask API (port 5001)
python dashboard.py

# in a second terminal, start the bot (writes data.json)
python bot.py
```

The API exposes:

- `GET /data`   — full dashboard state (balance, position, trades, equity history)
- `GET /health` — liveness probe

If `data.json` does not exist yet, `/data` returns a sensible empty
state instead of an error, so the dashboard loads cleanly on first run.

## 2. Run the React dashboard

```powershell
cd frontend
npm install
npm run dev
```

**One terminal:** Vite + Flask on port 5001 (avoids `ECONNREFUSED` on `/api/walkforward/...`, `/api/sweep/...`, etc.):

```powershell
cd frontend
npm install
npm run dev:with-api
```

Open http://127.0.0.1:5173. The Vite dev server proxies
`/api/*` → `http://127.0.0.1:5001/*`, so no CORS hassle in dev.

### Build for production

```powershell
npm run build
```

Serve `frontend/dist` with Nginx (or similar) and proxy `/api/*` to the Flask
API on port 5001. Step-by-step server setup: **[deploy/DEPLOY.md](deploy/DEPLOY.md)**.

## 3. What's in the dashboard

- **Metric cards** — Balance, Total P&L, Win Rate, Avg Profit, Max
  Drawdown, Best/Worst trade.
- **Equity curve** — Recharts area chart of balance over time with a
  dashed reference line at the starting balance.
- **Open position card** — current side, entry price, last update.
- **Trade history table** — newest-first, color-coded P&L.

Metrics are computed client-side from `/data`, so there is no extra
endpoint to maintain.

## Notes

- The equity curve only grows when trades close, because balance only
  changes on `sell()`. If you want per-tick equity points (mark-to-market
  while a position is open), record an equity point from `status()` as
  well, using `balance + (current_price - entry_price)` when long.
- `data.json` is written atomically per trade; polling every 3s is fine.
