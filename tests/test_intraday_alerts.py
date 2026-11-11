"""盤中價格提醒 + Telegram / ntfy 推播管道測試（不打外部網路）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import alerts as alerts_mod
from app import notifier
from app.data.db import Database
from app.data.intraday import IntradayQuote


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "alerts.db")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO stock_info (stock_id, stock_name, type, is_tradable) VALUES (?,?,?,?)",
            ("2330", "台積電", "twse", 1),
        )
        conn.execute(
            "INSERT INTO daily_price (stock_id, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
            ("2330", "2026-11-10", 1000, 1010, 990, 1000, 1),
        )
        conn.commit()
    return db


def _make_quote(price: float, live: bool = True) -> IntradayQuote:
    return IntradayQuote(
        stock_id="2330", price=price, prev_close=1000.0, open=None, high=None, low=None,
        is_live=live,
    )


@pytest.fixture
def fake_quotes(monkeypatch):
    holder: dict = {}

    def _fake(pairs, use_cache=True):
        holder["pairs"] = pairs
        return holder.get("quotes", {})

    monkeypatch.setattr("app.data.intraday.fetch_quotes", _fake)
    return holder


def test_intraday_uses_live_price(db, fake_quotes, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts_mod, "notify", lambda msg, title=None: sent.append((title, msg)) or True)
    alerts_mod.create_rule(db, "2330", "price_below", threshold=950.0)
    # 收盤 1000 沒跌破，但盤中 940 跌破
    assert alerts_mod.check_alerts(db, push=False) == []
    fake_quotes["quotes"] = {"2330": _make_quote(940.0)}
    hits = alerts_mod.check_alerts(db, push=True, intraday=True)
    assert len(hits) == 1 and hits[0].actual_value == 940.0
    assert "盤中即時" in hits[0].message
    assert fake_quotes["pairs"] == [("2330", "twse")]
    assert sent and "盤中" in sent[0][0]
    # 24h 冷卻：再檢查一次不重複推
    assert alerts_mod.check_alerts(db, push=True, intraday=True) == []


def test_intraday_ignores_stale_fallback_quote(db, fake_quotes):
    alerts_mod.create_rule(db, "2330", "price_below", threshold=950.0)
    fake_quotes["quotes"] = {"2330": _make_quote(900.0, live=False)}
    assert alerts_mod.check_alerts(db, push=False, intraday=True) == []


def test_intraday_skips_non_price_rules(db, fake_quotes):
    alerts_mod.create_rule(db, "2330", "score_drop", threshold=5.0)
    assert alerts_mod.check_alerts(db, push=False, intraday=True) == []
    assert "pairs" not in fake_quotes  # 沒有價格規則就不打外部


class _Resp:
    def __init__(self, code=200):
        self.status_code = code
        self.text = "ok"


def test_telegram_channel(monkeypatch):
    calls = []
    monkeypatch.setenv("NOTIFY_CHANNEL", "telegram")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(notifier.requests, "post", lambda url, json, timeout: calls.append((url, json)) or _Resp())
    assert notifier.notify("跌破 950", title="提醒") is True
    url, body = calls[0]
    assert url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert body["chat_id"] == "42" and body["text"] == "提醒\n跌破 950"


def test_ntfy_channel(monkeypatch):
    calls = []
    monkeypatch.setenv("NOTIFY_CHANNEL", "ntfy")
    monkeypatch.setenv("NTFY_TOPIC", "my-topic")
    monkeypatch.setattr(notifier.requests, "post", lambda url, json, timeout: calls.append((url, json)) or _Resp())
    assert notifier.notify("突破 1100", title="提醒") is True
    assert calls[0] == ("https://ntfy.sh", {"topic": "my-topic", "message": "突破 1100", "title": "提醒"})


def test_telegram_missing_config_returns_false(monkeypatch):
    monkeypatch.setenv("NOTIFY_CHANNEL", "telegram")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(notifier, "_get_channel_config", lambda: ("telegram", {}))
    assert notifier.notify("x") is False
