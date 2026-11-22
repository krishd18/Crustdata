#!/usr/bin/env python3
"""Preflight: what do these keys actually unlock?

Run this first at kickoff. It answers in about ten seconds the questions that
are expensive to discover at hour four:

* Are both keys present and valid?
* Can we reach each API at all from this network?
* Which Crustdata endpoints does *this plan* allow? Live company and person
  endpoints are enterprise-only, and a design that assumes them and does not
  get them is a rebuild.
* What does a call actually cost, so DESK_INR_PER_CREDIT can be set from a
  measurement rather than a guess.

Costs a handful of credits. Add --probe-live to also test the enterprise-only
endpoints, which may bill more.

    python3 scripts/doctor.py
    python3 scripts/doctor.py --probe-live
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

BASE = os.environ.get("CRUSTDATA_API_BASE", "https://api.crustdata.com")
VERSION = os.environ.get("CRUSTDATA_API_VERSION", "2025-11-01")

OK = "  ok  "
NO = " FAIL "
WARN = " warn "


def line(status: str, label: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f"  —  {detail}" if detail else ""))


def check_crustdata(probe_live: bool) -> dict:
    key = os.environ.get("CRUSTDATA_API_KEY", "")
    out: dict = {"credits": 0.0, "allowed": [], "denied": []}

    print("\nCRUSTDATA")
    if not key:
        line(NO, "CRUSTDATA_API_KEY", "not set")
        return out
    line(OK, "CRUSTDATA_API_KEY", f"set ({key[:6]}…{key[-4:]}, {len(key)} chars)")

    headers = {
        "Authorization": f"Bearer {key}",
        "x-api-version": VERSION,
        "content-type": "application/json",
    }

    # Free, and does not log itself: the cheapest possible auth check.
    try:
        r = requests.get(
            f"{BASE}/account/usage/events",
            params={"limit": 1},
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as exc:
        line(NO, "reach api.crustdata.com", f"{type(exc).__name__}: {str(exc)[:110]}")
        line(WARN, "", "network or proxy problem, not necessarily the key")
        return out

    if r.status_code == 401:
        line(NO, "authenticate", "401 — key rejected")
        return out
    if r.status_code == 403:
        line(WARN, "usage events", "403 — key valid but lacks this permission")
    elif r.ok:
        line(OK, "authenticate", "usage endpoint reachable (free)")
    else:
        line(WARN, "usage events", f"HTTP {r.status_code} {r.text[:80]}")

    probes = [
        ("POST", "/web/search/live",
         {"query": "Delhivery logistics", "sources": ["news"],
          "location": "IN", "page": 1}),
        ("POST", "/company/identify", {"query": "delhivery.com"}),
        ("POST", "/company/enrich",
         {"company_domain": "delhivery.com", "fields": ["basic_info"]}),
        ("POST", "/company/search",
         {"filters": [{"field": "basic_info.name", "type": "=",
                       "value": "Delhivery"}], "limit": 1}),
        ("POST", "/job/search",
         {"filters": [{"field": "company_name", "type": "in",
                       "value": ["Delhivery"]}], "limit": 1}),
        ("POST", "/person/search",
         {"filters": [{"field": "current_title", "type": "contains",
                       "value": "operations"}], "limit": 1}),
    ]
    if probe_live:
        probes += [
            ("POST", "/company/professional_network/search/live",
             {"query": "Delhivery", "limit": 1}),
            ("POST", "/person/professional_network/search/live",
             {"query": "Delhivery operations", "limit": 1}),
        ]

    print("\n  endpoint                                    status  credits  ms")
    for method, path, body in probes:
        t0 = time.monotonic()
        try:
            resp = requests.request(
                method, BASE + path, json=body, headers=headers, timeout=60
            )
        except requests.RequestException as exc:
            print(f"  {path:<42}  {type(exc).__name__}")
            out["denied"].append(path)
            continue
        ms = int((time.monotonic() - t0) * 1000)
        credits = resp.headers.get("X-Credits-Used", "-")
        print(f"  {path:<42}  {resp.status_code:<6}  {credits:<7}  {ms}")
        try:
            out["credits"] += float(credits)
        except ValueError:
            pass
        if resp.ok:
            out["allowed"].append(path)
        else:
            out["denied"].append(path)
            if resp.status_code in (402, 403):
                print(f"       -> {resp.text[:150]}")

    # One fetch, which bills separately from search.
    if "/web/search/live" in out["allowed"]:
        try:
            s = requests.post(
                f"{BASE}/web/search/live",
                json={"query": "Delhivery Guwahati", "sources": ["news"],
                      "location": "IN", "page": 1},
                headers=headers, timeout=60,
            ).json()
            urls = [r["url"] for r in (s.get("results") or []) if r.get("url")][:1]
            if urls:
                t0 = time.monotonic()
                f = requests.post(
                    f"{BASE}/web/enrich/live", json={"urls": urls},
                    headers=headers, timeout=90,
                )
                ms = int((time.monotonic() - t0) * 1000)
                credits = f.headers.get("X-Credits-Used", "-")
                print(f"  {'/web/enrich/live':<42}  {f.status_code:<6}  "
                      f"{credits:<7}  {ms}")
                try:
                    out["credits"] += float(credits)
                except ValueError:
                    pass
                if f.ok:
                    out["allowed"].append("/web/enrich/live")
                    body = f.json()
                    entries = body if isinstance(body, list) else body.get("results", [])
                    if entries:
                        print(f"       -> entry keys: {sorted(entries[0].keys())}")
        except Exception as exc:  # noqa: BLE001
            print(f"  fetch probe failed: {type(exc).__name__}: {exc}")

    return out


def check_model() -> str | None:
    print("\nMODEL")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        line(NO, "ANTHROPIC_API_KEY", "not set")
        return None
    line(OK, "ANTHROPIC_API_KEY", f"set ({key[:12]}…, {len(key)} chars)")

    try:
        import anthropic
    except ImportError:
        line(NO, "anthropic SDK", "pip install anthropic")
        return None

    client = anthropic.Anthropic(api_key=key)
    wanted = os.environ.get("DESK_MODEL")
    candidates = [wanted] if wanted else [
        "claude-haiku-5-5", "claude-sonnet-5-5", "claude-sonnet-4-5",
    ]
    for model in candidates:
        try:
            msg = client.messages.create(
                model=model, max_tokens=20,
                messages=[{"role": "user", "content": 'Reply {"ok":true}'}],
            )
            line(OK, f"model {model}",
                 f"{msg.usage.input_tokens} in / {msg.usage.output_tokens} out")
            return model
        except Exception as exc:  # noqa: BLE001
            text = str(exc)
            if "credit balance" in text:
                line(NO, f"model {model}", "account has no credit — top it up")
                return None
            if "authentication" in text.lower() or "401" in text:
                line(NO, f"model {model}", "key rejected")
                return None
            line(WARN, f"model {model}", text[:110])
    return None


def check_pricing(credits_spent: float) -> None:
    print("\nPRICING")
    rate = float(os.environ.get("DESK_INR_PER_CREDIT", "0") or 0)
    if rate > 0:
        line(OK, "DESK_INR_PER_CREDIT", f"{rate} INR/credit")
        if credits_spent:
            print(f"       this preflight spent {credits_spent:g} credits "
                  f"= INR {credits_spent * rate:.2f}")
    else:
        line(WARN, "DESK_INR_PER_CREDIT", "not set — cost will report as INR 0.00")
        print("       set it from the plan; a fabricated cost is worse than none")
    if credits_spent:
        print(f"       credits spent by this preflight: {credits_spent:g}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-live", action="store_true",
                    help="also test enterprise-only live endpoints")
    args = ap.parse_args()

    print("Competitor Move Desk — preflight")
    cd = check_crustdata(args.probe_live)
    model = check_model()
    check_pricing(cd["credits"])

    print("\nVERDICT")
    if cd["allowed"]:
        line(OK, f"{len(cd['allowed'])} Crustdata endpoint(s) usable",
             ", ".join(p.split("/")[-2] for p in cd["allowed"][:6]))
    else:
        line(NO, "no Crustdata endpoint reachable", "run offline: cli.py demo")
    if cd["denied"]:
        line(WARN, f"{len(cd['denied'])} denied", ", ".join(cd["denied"][:4]))
    if model:
        line(OK, "model usable", model)
    else:
        line(NO, "no model", "the pipeline will refuse everything; use --offline")

    ready = bool(cd["allowed"]) and bool(model)
    print("\n" + ("READY for a live run." if ready
                  else "NOT ready for a live run. Offline demo still works."))
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
