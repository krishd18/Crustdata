"""Loads every config/*.yaml, computes sha256 per file and a combined config_version; hot reload by
mtime (plan §3.1C). An invalid file keeps the last good config and logs an error."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import yaml

from .ids import sha256
from .logging import get_logger
from .settings import ROOT

CONFIG_DIR = ROOT / "config"
log = get_logger("config")


class Config:
    def __init__(self, directory: Path = CONFIG_DIR):
        self.dir = Path(directory)
        self.data: dict[str, Any] = {}
        self.shas: dict[str, str] = {}
        self.mtimes: dict[str, float] = {}
        self._lock = threading.RLock()
        self.reload()

    def reload(self) -> bool:
        """Re-read changed files. Returns True if anything changed."""
        changed = False
        with self._lock:
            for p in sorted(self.dir.glob("*.yaml")) + sorted(self.dir.glob("*.json")):
                m = p.stat().st_mtime
                if self.mtimes.get(p.name) == m:
                    continue
                raw = p.read_bytes()
                try:
                    val = yaml.safe_load(raw) if p.suffix == ".yaml" else __import__("json").loads(raw)
                    if val is None:
                        val = {}
                except Exception as e:  # noqa: BLE001
                    log.error("config.invalid", file=p.name, error=str(e)[:200])
                    self.mtimes[p.name] = m
                    continue
                self.data[p.stem] = val
                self.shas[p.stem] = sha256(raw)
                self.mtimes[p.name] = m
                changed = True
        return changed

    def __getitem__(self, k: str) -> Any:
        return self.data.get(k, {})

    def get(self, k: str, default: Any = None) -> Any:
        return self.data.get(k, default)

    @property
    def version(self) -> str:
        return sha256("|".join(f"{k}:{v}" for k, v in sorted(self.shas.items())))[:12]

    @property
    def rubric_version(self) -> str:
        return f"{self['rubric'].get('version', '?')} (sha {self.shas.get('rubric', '')[:8]})"

    def template(self, name: str) -> str:
        return (self.dir / "templates" / f"{name}.md.j2").read_text()

    def watch(self, every_s: float = 2.0) -> threading.Thread:
        def loop() -> None:
            while True:
                time.sleep(every_s)
                try:
                    if self.reload():
                        log.info("config.reloaded", version=self.version)
                except Exception as e:  # noqa: BLE001
                    log.error("config.reload_failed", error=str(e)[:200])
        t = threading.Thread(target=loop, daemon=True)
        t.start()
        return t


_CFG: Config | None = None


def get_config() -> Config:
    global _CFG
    if _CFG is None:
        _CFG = Config()
    return _CFG
