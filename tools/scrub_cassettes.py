#!/usr/bin/env python3
"""Fail if any cassette contains a secret (keys, bearer headers, app passwords)."""
import pathlib, re, sys
PAT = [re.compile(p) for p in (r"cd_[0-9a-f]{20,}", r"sk-ant-[A-Za-z0-9_\-]{20,}", r"(?i)authorization\"?\s*:\s*\"?bearer", r"(?i)x-api-key")]
bad = [f"{p}: {rx.pattern}" for p in pathlib.Path("tests/cassettes").rglob("*.json") for rx in PAT if rx.search(p.read_text(errors="ignore"))]
print("\n".join(bad) or "cassettes: clean")
sys.exit(1 if bad else 0)
