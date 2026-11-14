"""通知推播抽象層。

支援多個 backend，由 config.yaml 的 `notify.channel` 或環境變數 `NOTIFY_CHANNEL` 決定。
目前實作：discord / telegram / ntfy。

config.yaml 範例：
    notify:
      channel: telegram
      discord:
        webhook_url: "https://discord.com/api/webhooks/..."
      telegram:
        bot_token: "123456:ABC..."   # 跟 @BotFather 申請
        chat_id: "123456789"         # 自己的聊天 id
      ntfy:
        topic: "my-secret-topic-xyz" # 手機裝 ntfy App 訂閱同名主題
        server: "https://ntfy.sh"    # 可省略

環境變數覆寫：
    NOTIFY_CHANNEL          覆寫 channel（"none" 會關掉推播）
    DISCORD_WEBHOOK_URL     覆寫 discord.webhook_url
    TELEGRAM_BOT_TOKEN      覆寫 telegram.bot_token
    TELEGRAM_CHAT_ID        覆寫 telegram.chat_id
    NTFY_TOPIC              覆寫 ntfy.topic
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)


def _get_channel_config() -> tuple[str, dict]:
    """讀 config.yaml + env var，回傳 (channel, channel_cfg)。"""
    channel = ""
    channel_cfg: dict = {}
    try:
        from app.config import Config
        cfg = Config.load()
        notify_cfg = getattr(cfg, "notify", None) or {}
        channel = str(notify_cfg.get("channel", "")).lower()
        channel_cfg = dict(notify_cfg.get(channel, {})) if channel else {}
    except Exception as e:
        logger.debug("讀取 config 失敗，回退到 env var：%s", e)

    env_channel = os.environ.get("NOTIFY_CHANNEL")
    if env_channel:
        channel = env_channel.lower()
        channel_cfg = {}  # 以 env 為主時從頭組

    # 各 channel 專屬的 env 覆寫
    if channel == "discord":
        env_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if env_url:
            channel_cfg["webhook_url"] = env_url
    elif channel == "telegram":
        for env_key, cfg_key in (("TELEGRAM_BOT_TOKEN", "bot_token"), ("TELEGRAM_CHAT_ID", "chat_id")):
            if os.environ.get(env_key):
                channel_cfg[cfg_key] = os.environ[env_key]
    elif channel == "ntfy":
        if os.environ.get("NTFY_TOPIC"):
            channel_cfg["topic"] = os.environ["NTFY_TOPIC"]

    return channel, channel_cfg


def notify(message: str, title: str | None = None) -> bool:
    """發一則通知。失敗不拋，只記 log，回傳成功與否。"""
    channel, channel_cfg = _get_channel_config()
    if channel in ("", "none"):
        logger.info("notify channel 未設定，跳過推播")
        return False
    if channel == "discord":
        return _send_discord(message, title, channel_cfg)
    if channel == "telegram":
        return _send_telegram(message, title, channel_cfg)
    if channel == "ntfy":
        return _send_ntfy(message, title, channel_cfg)
    logger.warning("未知的 notify channel: %s", channel)
    return False


def _send_discord(message: str, title: str | None, cfg: dict) -> bool:
    url = cfg.get("webhook_url")
    if not url:
        logger.warning("Discord webhook_url 未設定")
        return False
    # Discord 單則 content 上限 2000 字
    body_parts = []
    if title:
        body_parts.append(f"**{title}**")
    body_parts.append(message)
    content = "\n".join(body_parts)[:1990]
    try:
        r = requests.post(url, json={"content": content}, timeout=10)
        if r.status_code in (200, 204):
            logger.info("Discord 推播成功")
            return True
        logger.warning("Discord 回 %s: %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        logger.warning("Discord 推播失敗: %s", e)
        return False


def _send_telegram(message: str, title: str | None, cfg: dict) -> bool:
    token = cfg.get("bot_token")
    chat_id = cfg.get("chat_id")
    if not token or not chat_id or "YOUR_" in str(token):
        logger.warning("Telegram bot_token / chat_id 未設定")
        return False
    # Telegram 單則訊息上限 4096 字；用純文字避免 Markdown 特殊字元解析失敗
    text = (f"{title}\n{message}" if title else message)[:4000]
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": str(chat_id), "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        if r.status_code == 200:
            logger.info("Telegram 推播成功")
            return True
        logger.warning("Telegram 回 %s: %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        # 例外訊息可能含 token（URL 內），不印原文
        logger.warning("Telegram 推播失敗: %s", type(e).__name__)
        return False


def _send_ntfy(message: str, title: str | None, cfg: dict) -> bool:
    topic = cfg.get("topic")
    if not topic or "YOUR_" in str(topic):
        logger.warning("ntfy topic 未設定")
        return False
    server = str(cfg.get("server") or "https://ntfy.sh").rstrip("/")
    try:
        r = requests.post(
            server,
            json={"topic": str(topic), "message": message[:3900], **({"title": title} if title else {})},
            timeout=10,
        )
        if r.status_code == 200:
            logger.info("ntfy 推播成功")
            return True
        logger.warning("ntfy 回 %s: %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        logger.warning("ntfy 推播失敗: %s", e)
        return False
