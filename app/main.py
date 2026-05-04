from pathlib import Path
from typing import Optional
import sqlite3
import time

import yfinance as yf
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "stocks.db"

DEFAULT_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "AVGO", "JPM", "V",
    "MA", "UNH", "COST", "NFLX", "AMD"
]

SAMPLE = {
    "AAPL": {"name": "Apple", "price": 190, "pe": 29, "market_cap": 2900, "revenue_growth": 5, "profit_margin": 25},
    "MSFT": {"name": "Microsoft", "price": 420, "pe": 35, "market_cap": 3100, "revenue_growth": 12, "profit_margin": 34},
    "NVDA": {"name": "NVIDIA", "price": 900, "pe": 70, "market_cap": 2200, "revenue_growth": 120, "profit_margin": 48},
    "GOOGL": {"name": "Alphabet", "price": 150, "pe": 25, "market_cap": 1900, "revenue_growth": 10, "profit_margin": 24},
    "AMZN": {"name": "Amazon", "price": 180, "pe": 55, "market_cap": 1850, "revenue_growth": 11, "profit_margin": 7},
}

app = FastAPI(title="Stock Alpha Local")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def db():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            ticker TEXT PRIMARY KEY,
            name TEXT,
            price REAL,
            pe REAL,
            market_cap REAL,
            revenue_growth REAL,
            profit_margin REAL,
            score REAL,
            updated_at INTEGER
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            ticker TEXT PRIMARY KEY
        )
        """)


def score_stock(x):
    score = 0
  pe = x.get("pe") or 0
    growth = x.get("revenue_growth") or 0
    margin = x.get("profit_margin") or 0
    cap = x.get("market_cap") or 0

    if cap >= 1000:
        score += 20
    elif cap >= 100:
        score += 12

    if growth >= 30:
        score += 30
    elif growth >= 10:
        score += 20
    elif growth >= 0:
        score += 8

    if margin >= 30:
        score += 25
    elif margin >= 15:
        score += 18
    elif margin >= 5:
        score += 8

    if 0 < pe <= 25:
        score += 20
    elif pe <= 40:
        score += 12
    elif pe <= 70:
        score += 5

    return round(score, 1)


def fetch_stock(ticker):
    try:
        info = yf.Ticker(ticker).info
        item = {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName") or ticker,
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "pe": info.get("trailingPE"),
            "market_cap": (info.get("marketCap") or 0) / 1_000_000_000,
            "revenue_growth": (info.get("revenueGrowth") or 0) * 100,
            "profit_margin": (info.get("profitMargins") or 0) * 100,
        }
        if not item["price"]:
            raise ValueError("empty price")
        return item
    except Exception:
        sample = SAMPLE.get(ticker, {
            "name": ticker,
            "price": 100,
            "pe": 30,
            "market_cap": 50,
            "revenue_growth": 8,
            "profit_margin": 10,
        })
        return {"ticker": ticker, **sample}


def upsert_stock(item):
    item["score"] = score_stock(item)
    item["updated_at"] = int(time.time())
    with db() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO stocks
        (ticker, name, price, pe, market_cap, revenue_growth, profit_margin, score, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item["ticker"], item["name"], item["price"], item["pe"],
          item["market_cap"], item["revenue_growth"], item["profit_margin"],
            item["score"], item["updated_at"]
        ))
    return item


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def home():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "Stock Alpha Local is running"}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/sync")
def sync():
    results = []
    for ticker in DEFAULT_TICKERS:
        results.append(upsert_stock(fetch_stock(ticker)))
    return {"count": len(results), "stocks": results}


@app.get("/api/stocks")
def stocks(
    min_score: float = Query(0),
    max_pe: Optional[float] = Query(None),
    min_growth: Optional[float] = Query(None),
):
    sql = "SELECT * FROM stocks WHERE score >= ?"
    params = [min_score]

    if max_pe is not None:
        sql += " AND pe <= ?"
        params.append(max_pe)
    if min_growth is not None:
        sql += " AND revenue_growth >= ?"
        params.append(min_growth)

    sql += " ORDER BY score DESC, market_cap DESC"

    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/stocks/{ticker}")
def stock_detail(ticker: str):
    ticker = ticker.upper()
    with db() as conn:
        row = conn.execute("SELECT * FROM stocks WHERE ticker = ?", (ticker,)).fetchone()
    if row:
        return dict(row)
    return upsert_stock(fetch_stock(ticker))


@app.post("/api/watchlist/{ticker}")
def add_watchlist(ticker: str):
    ticker = ticker.upper()
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO watchlist(ticker) VALUES (?)", (ticker,))
    return {"ok": True, "ticker": ticker}


@app.get("/api/watchlist")
def get_watchlist():
    with db() as conn:
        rows = conn.execute("""
        SELECT s.* FROM watchlist w
        LEFT JOIN stocks s ON s.ticker = w.ticker
        ORDER BY w.ticker
        """).fetchall()
    return [dict(r) for r in rows if r["ticker"]]
