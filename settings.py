"""Configuração externa. Credenciais nunca entram no executável ou no servidor HTTP."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


class AppError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


DEFAULTS = {
    "sessionid": "",
    "start_url": "https://www.instagram.com/ad_tools/?context=main_navigation",
    "browser_channel": "msedge",
    "headless": True,
    "timeout_seconds": 45,
    "settle_seconds": 6,
    "port": 8765,
    "listen_host": "0.0.0.0",
    "data_dir": "data",
    "dom_selectors": {},
}


def app_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def resource_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def load_config(path: Path) -> dict:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError()
        cfg = DEFAULTS | raw
        env = {}
        dotenv = path.parent / ".env"
        if dotenv.exists():
            for line in dotenv.read_text(encoding="utf-8-sig").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("\"'")
        cfg["sessionid"] = os.environ.get("INSTAGRAM_SESSIONID", env.get("INSTAGRAM_SESSIONID", cfg["sessionid"]))
        if not isinstance(cfg["sessionid"], str):
            raise ValueError()
        cfg["sessionid"] = cfg["sessionid"].strip()
        url = urlsplit(cfg["start_url"])
        if url.scheme != "https" or url.hostname not in {"www.instagram.com", "instagram.com"} or url.username or url.password:
            raise ValueError()
        if cfg["browser_channel"] not in {"msedge", "chrome", "chromium"}:
            raise ValueError()
        if type(cfg["headless"]) is not bool:
            raise ValueError()
        if cfg["listen_host"] not in {"127.0.0.1", "0.0.0.0"}:
            raise ValueError()
        for key, low, high in (("port", 0, 65535), ("timeout_seconds", 5, 120), ("settle_seconds", 1, 20)):
            if type(cfg[key]) is not int or not low <= cfg[key] <= high:
                raise ValueError()
        if not isinstance(cfg["dom_selectors"], dict):
            raise ValueError()
        folder = Path(cfg["data_dir"])
        cfg["data_path"] = (folder if folder.is_absolute() else path.parent / folder).resolve()
        return cfg
    except (ValueError, TypeError, KeyError, OSError):
        raise AppError("config_invalid", "Configuração inválida. Confira config.json e use config.example.json como referência.") from None


class SecretFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.secrets: set[str] = set()

    def add(self, secret: str):
        if secret:
            self.secrets.update((secret, unquote(secret)))

    def filter(self, record):
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[OCULTO]")
        message = re.sub(r"(?i)(sessionid|access_token|csrftoken)([=: ]+)[^\s,;]+", r"\1\2[OCULTO]", message)
        record.msg, record.args = message, ()
        record.exc_info = None
        record.exc_text = None
        return True
