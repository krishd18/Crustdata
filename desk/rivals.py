"""Rival registry: an index of names, never a source of facts.

The brief forbids facts from model memory, and a hand-written registry is
model memory in a JSON file. So this module is deliberately incapable of
answering anything. It does two safe things:

* **widens a search** -- if a question names Gati, also look for Gati-KWE and
  Allcargo Gati, because the evidence may be filed under any of them;
* **raises ambiguity** -- if a string could mean the parent group or the
  logistics arm, say so and stop, rather than resolving it quietly.

Both are safe because the worst outcome of a wrong entry is a wasted query or
an unnecessary clarification. Neither can put an unsourced claim in an answer.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

_DATA = os.path.join(os.path.dirname(__file__), "rivals.json")


def _norm(s: str) -> str:
    """Fold case, punctuation and the corporate-suffix noise that makes
    'Mahindra Logistics Ltd.' and 'Mahindra Logistics Limited' look different."""
    s = s.lower().strip()
    s = re.sub(r"[.,'\"()]", " ", s)
    s = re.sub(
        r"\b(private|pvt|limited|ltd|llp|inc|corporation|corp|co|company)\b", " ", s
    )
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Rival:
    key: str
    display_name: str
    domain: str | None = None
    aliases: list[str] = field(default_factory=list)
    former_names: list[str] = field(default_factory=list)
    acquired_brands: list[str] = field(default_factory=list)
    confusable_with: list[str] = field(default_factory=list)
    parent_group: str | None = None
    acquired_by_unverified: str | None = None
    segment_hint: str | None = None
    note_unverified: str | None = None

    def all_names(self) -> list[str]:
        """Every string worth searching for when the question names this rival."""
        names = [self.display_name, *self.aliases, *self.former_names]
        if self.domain:
            names.append(self.domain)
        seen: dict[str, None] = {}
        for n in names:
            if n:
                seen.setdefault(n, None)
        return list(seen)

    def search_terms(self) -> list[str]:
        """Names to search, including brands it may still post jobs under.

        An acquired brand is included because listings and news lag an
        acquisition, which is the stated hard case. It is included as a term
        to search, not as an assertion that the acquisition happened.
        """
        return list(dict.fromkeys([*self.all_names(), *self.acquired_brands]))


@dataclass
class Match:
    rival: Rival
    matched_on: str
    how: str          # exact | alias | former_name | acquired_brand | partial
    caution: str | None = None


class RivalRegistry:
    # Leading words too generic to identify a company on their own.
    _GENERIC_HEAD = {
        "container", "transport", "future", "gateway", "stellar", "om", "leap",
    }

    def __init__(self, rivals: list[Rival]) -> None:
        self.rivals = rivals
        self._by_norm: dict[str, list[tuple[Rival, str, str]]] = {}
        # Bare words that identify a *family* of entities rather than one
        # company. "Mahindra" is the group, the logistics arm and several
        # unrelated businesses, so seeing it alone is grounds to ask which,
        # never grounds to pick. Only rivals that actually have something to
        # be confused with contribute a token here.
        self._ambiguous_head: dict[str, list[Rival]] = {}
        for r in rivals:
            self._index(r, r.display_name, "exact")
            for a in r.aliases:
                self._index(r, a, "alias")
            for f in r.former_names:
                self._index(r, f, "former_name")
            for b in r.acquired_brands:
                self._index(r, b, "acquired_brand")
            if r.domain:
                self._index(r, r.domain, "alias")

            if r.confusable_with or r.parent_group:
                head = _norm(r.display_name).split(" ")[0] if r.display_name else ""
                if len(head) >= 4 and head not in self._GENERIC_HEAD:
                    self._ambiguous_head.setdefault(head, []).append(r)

    def _index(self, rival: Rival, name: str, how: str) -> None:
        self._by_norm.setdefault(_norm(name), []).append((rival, name, how))

    @classmethod
    def load(cls, path: str = _DATA) -> "RivalRegistry":
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        rivals = []
        for item in raw.get("rivals", []):
            rivals.append(
                Rival(
                    key=item["key"],
                    display_name=item["display_name"],
                    domain=item.get("domain"),
                    aliases=item.get("aliases", []),
                    former_names=item.get("former_names", []),
                    acquired_brands=item.get("acquired_brands", []),
                    confusable_with=item.get("confusable_with", []),
                    parent_group=item.get("parent_group"),
                    acquired_by_unverified=item.get("acquired_by_unverified"),
                    segment_hint=item.get("segment_hint"),
                    note_unverified=item.get("note_unverified"),
                )
            )
        return cls(rivals)

    # ------------------------------------------------------------- lookup

    def lookup(self, text: str) -> list[Match]:
        """Find every rival a string could refer to. Order is not preference."""
        key = _norm(text)
        matches: list[Match] = []

        for rival, name, how in self._by_norm.get(key, []):
            matches.append(
                Match(
                    rival=rival,
                    matched_on=name,
                    how=how,
                    caution=self._caution(rival, how),
                )
            )

        if not matches and key:
            for norm_name, entries in self._by_norm.items():
                if key in norm_name or norm_name in key:
                    for rival, name, how in entries:
                        matches.append(
                            Match(
                                rival=rival,
                                matched_on=name,
                                how="partial",
                                caution=self._caution(rival, "partial"),
                            )
                        )

        deduped: dict[str, Match] = {}
        for m in matches:
            deduped.setdefault(m.rival.key, m)
        return list(deduped.values())

    @staticmethod
    def _caution(rival: Rival, how: str) -> str | None:
        if how == "acquired_brand":
            return (
                f"'{rival.display_name}' lists this as an acquired brand. "
                "Confirm the current owner from a live source before answering; "
                "listings can lag an acquisition."
            )
        if how == "former_name":
            return "Matched a former name. Confirm the current name from a live source."
        if rival.acquired_by_unverified:
            # The brand still resolves, but it may no longer be an independent
            # company. Answering about it as one is the acquired-brand trap.
            return (
                f"This brand may now sit under {rival.acquired_by_unverified} "
                "(unverified). Confirm the current owner from a live source "
                "before treating it as an independent company."
            )
        if rival.parent_group:
            return (
                f"May be confused with the parent group ({rival.parent_group}). "
                "Group-level facts do not answer questions about the arm."
            )
        return None

    def ambiguity(self, text: str) -> list[str]:
        """Names this string could also mean, which are not in the registry.

        These come from ``confusable_with``, and exist to force a clarification
        rather than a guess. 'Mahindra' matching Mahindra Logistics does not
        mean the asker meant Mahindra Logistics.
        """
        out: list[str] = []
        for m in self.lookup(text):
            out.extend(m.rival.confusable_with)
            if m.rival.parent_group:
                out.append(m.rival.parent_group)
        return list(dict.fromkeys(out))

    def by_key(self, key: str) -> Rival | None:
        for r in self.rivals:
            if r.key == key:
                return r
        return None

    def mentioned_in(self, question: str) -> list[Match]:
        """Every rival a question appears to name."""
        q = _norm(question)
        found: dict[str, Match] = {}
        for norm_name, entries in self._by_norm.items():
            if not norm_name:
                continue
            if re.search(rf"\b{re.escape(norm_name)}\b", q):
                for rival, name, how in entries:
                    existing = found.get(rival.key)
                    # Prefer the longest matched name: 'mahindra logistics'
                    # beats 'mahindra' when both appear.
                    if existing is None or len(name) > len(existing.matched_on):
                        found[rival.key] = Match(
                            rival=rival,
                            matched_on=name,
                            how=how,
                            caution=self._caution(rival, how),
                        )

        # A bare family word with no full name alongside it. "How many people
        # does Mahindra employ in logistics?" names no company: it names a
        # group that contains several, and answering it picks one on the
        # asker's behalf.
        for head, rivals in self._ambiguous_head.items():
            if not re.search(rf"\b{re.escape(head)}\b", q):
                continue
            if any(head in _norm(m.matched_on).split(" ")
                   and len(_norm(m.matched_on).split(" ")) > 1
                   for m in found.values()):
                continue  # the fuller name is present; it wins
            for rival in rivals:
                found.setdefault(
                    rival.key,
                    Match(
                        rival=rival,
                        matched_on=head,
                        how="partial",
                        caution=self._caution(rival, "partial"),
                    ),
                )
        return list(found.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.rivals),
            "keys": [r.key for r in self.rivals],
        }
