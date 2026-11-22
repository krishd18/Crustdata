"""Command line: check a request or a deck without the web UI.

    python -m app.cli request.json                 # kickoff-kit request (one, a list, or {"requests": [...]})
    python -m app.cli deck.pdf --company Stockarea --domain stockarea.io
    python -m app.cli https://example.com/teaser --company Acme
    python -m app.cli request.json -o result.json  # write the register JSON to a file

Prints the register as JSON (or a readable table with --table).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    load_dotenv(ROOT / ".env")
    from . import ingest, pipeline, store

    ap = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="request .json, a deck (.pdf/.pptx/.txt), a URL, or '-' for stdin")
    ap.add_argument("--company", help="company name (when the input is a deck)")
    ap.add_argument("--domain", help="company domain")
    ap.add_argument("--city")
    ap.add_argument("-o", "--out", help="write JSON here instead of stdout")
    ap.add_argument("--table", action="store_true", help="print a readable table instead of JSON")
    a = ap.parse_args(argv)

    token = os.getenv("CRUSTDATA_API_TOKEN")
    if not token:
        print("CRUSTDATA_API_TOKEN is not set (see .env.example)", file=sys.stderr)
        return 2
    store.init()

    src = a.input
    if src == "-":
        reqs = ingest.parse_requests(sys.stdin.read()) if not a.company else [ingest.Request(name=a.company, document=sys.stdin.read())]
    elif src.startswith(("http://", "https://")):
        reqs = [ingest.Request(name=a.company, domain=a.domain, city=a.city, document_url=src)]
    else:
        p = Path(src)
        data = p.read_bytes()
        if p.suffix.lower() == ".json" and not a.company:
            reqs = ingest.parse_requests(data.decode("utf-8-sig"))
        else:
            reqs = [ingest.Request(name=a.company, domain=a.domain, city=a.city,
                                   file_b64=base64.b64encode(data).decode(), file_name=p.name)]
    for r in reqs:
        r.name = r.name or a.company
        r.domain = r.domain or a.domain
        r.city = r.city or a.city
        if not r.name and not r.domain:
            print("No company name: pass --company", file=sys.stderr)
            return 2

    results = [pipeline.check_request(r, token) for r in reqs]
    out = results[0] if len(results) == 1 else results

    if a.table:
        for res in results:
            print(f"\n{(res.get('company') or {}).get('name', '?')}  ({res.get('status')})")
            for c in res.get("claims", []):
                print(f"  [{c['verdict']:>23}] {c['type']:<15} {c['claim'][:70]}")
            for q in res.get("ask_them_for", []):
                print(f"  ask for: {q['document']}")
            print(f"  cost: {(res.get('cost') or {}).get('credits')} credits")
        return 0
    text = json.dumps(out, indent=2, ensure_ascii=False, default=str)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out}", file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
