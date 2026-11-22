"""A1 Query Reasoner (STANDARDS §5; prompts/query_reasoner.md). Parameters that drive the run come only from the
term library (config/terms.yaml) applied deterministically; Claude (reason role) proposes the family, premises and
any extra parameters, which are shown as 'proposed — confirm' and never applied silently. Numbers must come from the
query, config or client profile (invented numbers are dropped). Relative time is resolved by the injected clock."""
from __future__ import annotations

import json
import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from ..core.claude import load_prompt
from ..core.errors import ParseFailed, SecretMissing
from .base import BaseAgent, cli

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "twenty-five": 25, "thirty": 30, "fifty": 50, "hundred": 100}
FAMILIES = ["FIND_LIST", "RESEARCH_QA", "ACQUIRE", "VENDOR_CHECK", "DECK_CHECK"]


class Param(BaseModel):
    name: str
    metric_ids: list[str] = Field(default_factory=list)
    field: str | None = None
    operator: str | None = None
    value: Any = None
    role: str
    measured_at: str = "research"
    origin: Literal["from_query", "default", "assumed_confirm", "proposed_confirm", "term_library", "proxy", "clock"] = "from_query"


class Row(BaseModel):
    phrase: str
    intent: str
    parameters: list[Param]


class Window(BaseModel):
    phrase: str
    start: str
    end: str
    rule: str


class Premise(BaseModel):
    text: str
    check_with: list[str] = Field(default_factory=list)


class Question(BaseModel):
    id: str
    text: str
    options: list[str]
    default: str


class ResearchPlan(BaseModel):
    family: str
    n_requested: int | None = None
    country: str | None = None
    sector: str | None = None             # term key: b2b_software | fintech | logistic | payments …
    sector_words: list[str] = Field(default_factory=list)
    year_founded_min: int | None = None
    growth_months: int | None = None
    growth_pct: float | None = None
    headcount_guard: int | None = None
    attributes: list[str] = Field(default_factory=list)
    window_start: str | None = None
    window_end: str | None = None
    window_label: str | None = None
    job_category: str | None = None
    title_filter: str | None = None
    inference: bool = False
    state: str | None = None
    location_basis: str | None = None
    acquirable: bool = False
    premises: list[str] = Field(default_factory=list)


class QueryInput(BaseModel):
    text: str
    client_profile: dict = Field(default_factory=dict)
    use_llm: bool = True


class ReasoningCard(BaseModel):
    family: str
    n_requested: int | None
    rows: list[Row]
    premises: list[Premise]
    time_windows: list[Window]
    questions: list[Question]
    plan: ResearchPlan
    llm: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class LLMCard(BaseModel):
    """Structured output requested from Claude (prompt schema summary)."""
    family: Literal["FIND_LIST", "RESEARCH_QA", "ACQUIRE", "VENDOR_CHECK", "DECK_CHECK"]
    n_requested: int | None
    rows: list[Row]
    premises: list[Premise]
    questions: list[Question]


def _num(word: str) -> int | None:
    w = word.lower().strip()
    return int(w) if w.isdigit() else WORDNUM.get(w)


def parse(text: str, terms: dict, clock) -> tuple[ResearchPlan, list[Row], list[Window], list[Question]]:
    """Deterministic term-library parse → plan + card rows (STANDARDS §5.2)."""
    t = " " + text.lower().replace("’", "'") + " "
    T = terms.get("terms", {})
    rows: list[Row] = []
    wins: list[Window] = []
    qs: list[Question] = []
    # family
    if "acquir" in t:
        fam = "ACQUIRE"
    elif re.search(r"\b(vendor|carrier|onboarding)\b", t):
        fam = "VENDOR_CHECK"
    elif re.search(r"\b(deck|fact-check|pitch)\b", t):
        fam = "DECK_CHECK"
    elif re.search(r"^\s*(find|list|give me|show me|name|identify|get)\b", t):
        fam = "FIND_LIST"
    else:
        fam = "RESEARCH_QA"
    p = ResearchPlan(family=fam)
    # N
    m = re.search(r"\b(?:top\s+)?(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|twenty-five|thirty|fifty)\s+(?:indian\s+)?(?:[a-z0-9\-]+\s+){0,4}?(?:companies|firms|startups|fintechs|operators|players|businesses)\b", t)
    if m:
        p.n_requested = _num(m.group(1))
        rows.append(Row(phrase=m.group(1), intent="output size (never padded)", parameters=[Param(name="n", value=p.n_requested, role="output", origin="from_query")]))
    elif fam == "RESEARCH_QA":
        p.n_requested = 10
        rows.append(Row(phrase="(output size)", intent="top 10", parameters=[Param(name="n", value=10, role="output", origin="default")]))
    # country
    if re.search(r"\bindian?\b|\bin india\b", t):
        p.country = "IND"
        rows.append(Row(phrase="Indian", intent=T.get("indian", {}).get("intent", "HQ country"),
                        parameters=[Param(name="hq_country", field="locations.country", operator="in", value=["IND"], role="hard", origin="from_query")]))
    # sector
    if re.search(r"b2b\s+(software|saas)|\bsaas\b|software compan", t):
        p.sector = "b2b_software"
        rows.append(Row(phrase="B2B software", intent=T["b2b_software"]["intent"], parameters=[
            Param(name="industry", field="taxonomy.professional_network_industry", operator="in", value=T["b2b_software"]["industry_values_seed"], role="search_filter", origin="term_library"),
            Param(name="b2b", metric_ids=["classifier:b2b"], role="hard", origin="term_library")]))
    elif re.search(r"\bfintech|\bpayments?\b|\blending\b|\bneobank|\binsurtech|\bwealthtech", t):
        p.sector = "fintech"
        p.sector_words = [w for w in ("payments", "lending", "insurtech", "wealth") if w in t]
        rows.append(Row(phrase="fintech" if "fintech" in t else (p.sector_words or ["fintech"])[0], intent=T["fintech"]["intent"], parameters=[
            Param(name="sector", field="taxonomy.categories | taxonomy.professional_network_industry", operator="in", value="autocomplete(fin, pay, lend, insur, wealth, bank) | Financial Services", role="search_filter", origin="term_library"),
            Param(name="fintech", metric_ids=["classifier:fintech"], role="hard", origin="term_library", value=T["fintech"]["exclude"])]))
    elif re.search(r"\blogistic", t):
        p.sector = "logistic"
        rows.append(Row(phrase="logistic", intent="sector", parameters=[Param(name="industry", metric_ids=["ID-05"], value=T["logistic"]["values"], role="hard", origin="term_library")]))
    # founded since
    m = re.search(r"founded\s+(?:since|after|in or after|from)\s+(\d{4})|founded in\s+(\d{4})\s+or later|founded\s+(?:in\s+)?(\d{4})\s*(?:\+|onwards)", t)
    if m:
        y = int(next(g for g in m.groups() if g))
        if "after" in m.group(0) and "or after" not in m.group(0):
            y += 1
        p.year_founded_min = y
        rows.append(Row(phrase=m.group(0).strip(), intent="founding year ≥ YEAR", parameters=[
            Param(name="year_founded", field="basic_info.year_founded", operator="=>", value=y, role="hard", origin="from_query"),
            Param(name="cross_check", value="CIN year / earliest Wayback capture; conflict → excluded", role="hard", origin="term_library")]))
    # growth
    tg = T.get("team_grew", {})
    m = re.search(r"(?:team|headcount|staff|employees?)\s+(?:grew|grow|increased|expanded)\s+by\s+(half|a third|\d+(?:\.\d+)?\s*%)|(doubled|double)\s+(?:their|its)\s+(?:team|headcount)|grew\s+(\d+)\s*%", t)
    if m:
        word = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        pct = tg.get("word_values", {}).get(word)
        if pct is None:
            pct = float(re.sub(r"[^\d.]", "", word))
        mm = re.search(r"(?:last|past)\s+(\d+|one|three|six|twelve)\s+months?|in\s+(\d+|one|three|six|twelve)\s+months?|in\s+a\s+(month|year)|last\s+(year|month)", t)
        months = None
        if mm:
            g = next(x for x in mm.groups() if x)
            months = {"month": 1, "year": 12}.get(g) or _num(g)
        if months not in tg.get("allowed_N", [1, 3, 6, 12]):
            months = min(tg.get("allowed_N", [6]), key=lambda n: abs(n - (months or 6)))
        p.growth_months, p.growth_pct = months, float(pct)
        g = tg.get("guard", {})
        p.headcount_guard = g.get("value", 10)
        w0, w1 = clock.last_n_months(months)
        wins.append(Window(phrase=f"last {months} months", start=w0.isoformat(), end=w1.isoformat(), rule="now − N months (IST)"))
        rows.append(Row(phrase=m.group(0).strip(), intent="headcount growth", parameters=[
            Param(name="growth", field=f"headcount.growth_percent.{months}m", operator="=>", value=pct, role="hard", origin="from_query"),
            Param(name="headcount_guard", field=g.get("field", "headcount.total"), operator="=>", value=p.headcount_guard, role="hard", origin="proposed_confirm")]))
        qs.append(Question(id="guard", text=f"Require at least {p.headcount_guard} staff today, so a 2 → 3 jump is not counted as growth?", options=["Yes (recommended)", "No"], default="Yes (recommended)"))
    # attributes
    if re.search(r"who founded|their founders|founders", t):
        p.attributes.append("founders")
        rows.append(Row(phrase="who founded each" if "who founded" in t else "with their founders", intent="founders", parameters=[
            Param(name="founders", field="people.founders", role="attribute", origin="term_library")]))
    if re.search(r"what (?:they|each) did before|did before|previous(?:ly)? (?:roles|worked)|prior roles", t):
        p.attributes.append("prior_roles")
        rows.append(Row(phrase="what they did before", intent="1–2 most recent roles before founding", parameters=[
            Param(name="prior_roles", field="experience.employment_details.past", role="attribute", value="🟢 P5 unless T1/T1-M", origin="term_library")]))
    # windows
    if "this quarter" in t:
        s, e, lbl = clock.quarter_window()
        p.window_start, p.window_end, p.window_label = s.isoformat(), e.isoformat(), lbl
        wins.append(Window(phrase="this quarter", start=s.isoformat(), end=e.isoformat(), rule=f"calendar quarter containing now (IST) — {lbl}"))
    m = re.search(r"(?:last|past)\s+(\d+)\s+days", t)
    if m:
        s, e = clock.last_n_days(int(m.group(1)))
        p.window_start, p.window_end, p.window_label = s.isoformat(), e.isoformat(), f"last {m.group(1)} days"
        wins.append(Window(phrase=m.group(0), start=s.isoformat(), end=e.isoformat(), rule="now − N days (IST)"))
    # hiring
    if re.search(r"hiring|job postings|openings|posted", t):
        hm = T.get("hiring_the_most", {})
        p.job_category = "Engineering" if re.search(r"engineer|developer|tech", t) else None
        tm = re.search(r"hiring the most ([a-z ]+?) engineers", t)
        if tm and tm.group(1).strip() not in ("", "software"):
            p.title_filter = tm.group(1).strip() + " engineer"
        if not p.window_start:
            s, e, lbl = clock.quarter_window()
            p.window_start, p.window_end, p.window_label = s.isoformat(), e.isoformat(), lbl
            wins.append(Window(phrase="(window)", start=s.isoformat(), end=e.isoformat(), rule="default: this quarter — confirm"))
        rows.append(Row(phrase="hiring the most engineers" if p.job_category else "hiring", intent="rank by deduped job postings (proxy)", parameters=[
            Param(name="ranking", metric_ids=["deduped_job_postings"], field="job_details.category", operator="=", value=p.job_category or "any", role="metric", origin="proxy"),
            Param(name="title_filter", value=p.title_filter, role="search_filter", origin="from_query")] if p.title_filter else [
            Param(name="ranking", metric_ids=["deduped_job_postings"], field="job_details.category", operator="=", value=p.job_category or "any", role="metric", origin="proxy")]))
        if p.family == "FIND_LIST":
            p.family = "RESEARCH_QA"
    if re.search(r"say about|launch next|likely (?:building|to launch|next)|what (?:are|is) (?:they|it) (?:likely )?building|signal about", t):
        p.inference = True
        rows.append(Row(phrase="what will each launch next", intent="themes in the window's postings", parameters=[
            Param(name="themes", metric_ids=["IS"], value="themes.yaml → Inference Strength", role="inference", origin="term_library")]))
    # state
    codes = T.get("in_state", {}).get("gst_state_codes", {})
    for st in codes:
        if re.search(rf"\b(?:in|operating in|based in)\s+{st.lower()}\b", t):
            p.state, p.location_basis = st, T["in_state"].get("location_basis_default", "operates")
            rows.append(Row(phrase=f"in {st}", intent="geography", parameters=[
                Param(name="location", value={"state": st, "gst_state_code": codes[st], "basis": p.location_basis}, metric_ids=["FP-01", "RG-02"], role="hard", origin="assumed_confirm")]))
            qs.append(Question(id="basis", text=f'What does "in {st}" mean?', options=["Operates there", "Majority of operations there (≥ 40%)", "Headquartered there"], default="Operates there"))
    if p.family == "ACQUIRE":
        p.acquirable = True
        aq = T.get("acquirable", {})
        rows.insert(0, Row(phrase="acquirable", intent=aq.get("intent", ""), parameters=[
            Param(name="AQ-01..03", metric_ids=list(aq.get("hard", [])), role="hard", origin="term_library", measured_at="step1"),
            Param(name="AQ-04..06", metric_ids=list(aq.get("soft", {}).keys()), value=aq.get("soft"), role="soft", origin="term_library", measured_at="step1"),
            *[Param(name=k, metric_ids=[k], operator=">=", value=v, role="min_band", origin="term_library", measured_at="check") for k, v in aq.get("min_band", {}).items()]]))
        qs.append(Question(id="listed", text="Include listed companies?", options=["No", "Yes"], default="No"))
    # premises: "that listed on NSE in October 2026", "that raised …", "that were acquired …"
    for m in re.finditer(r"\b(?:that|which|who)\s+((?:listed|went public|ipo'?d|raised|were acquired|got acquired|received|won)\b[^,?.]*)", t):
        p.premises.append(re.split(r"\s+(?:are|is|and|have|has|were)\s+(?!acquired|listed)", m.group(1).strip())[0])
    return p, rows, wins, qs[:3]


NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def invented_numbers(card: LLMCard, text: str, terms_yaml: str, profile: dict) -> list[str]:
    """Numbers in Claude's parameter values that appear nowhere in the query, term library or client profile."""
    allowed = set(NUM.findall(text)) | set(NUM.findall(terms_yaml)) | set(NUM.findall(json.dumps(profile)))
    bad = []
    for r in card.rows:
        for prm in r.parameters:
            for n in NUM.findall(json.dumps(prm.value, default=str)):
                if n not in allowed:
                    bad.append(f"{prm.name}={n}")
    return bad


class QueryReasoner(BaseAgent[QueryInput, ReasoningCard]):
    name, input_model, output_model = "a01_query_reasoner", QueryInput, ReasoningCard
    deterministic = False

    def run(self, inp: QueryInput, ctx) -> ReasoningCard:
        terms = ctx.config["terms"]
        plan, rows, wins, qs = parse(inp.text, terms, ctx.clock)
        notes: list[str] = []
        llm_meta: dict = {}
        premises = [Premise(text=x, check_with=["media", "registry"]) for x in plan.premises]
        if inp.use_llm:
            terms_yaml = yaml.safe_dump(terms, sort_keys=False)
            user = (f"NOW: {ctx.clock.now().isoformat()}\nCLIENT PROFILE: {json.dumps(inp.client_profile)}\n"
                    f"TERM LIBRARY: {terms_yaml}\nREQUEST: \"\"\"{inp.text}\"\"\"")
            try:
                card, usage = ctx.claude.generate_json("reason", load_prompt("query_reasoner"), user, LLMCard, task="query_reasoner")
                llm_meta = {"model": usage.get("model"), "cached": usage.get("cached", False), "family": card.family}
                bad = invented_numbers(card, inp.text, terms_yaml, inp.client_profile)
                if bad:
                    notes.append(f"dropped invented numbers from the LLM: {', '.join(bad[:5])}")
                known = {p.name for r in rows for p in r.parameters}
                for r in card.rows:
                    extra = [p for p in r.parameters if p.name not in known and not any(b.startswith(p.name + "=") for b in bad)]
                    if extra and not any(r.phrase.lower() in x.phrase.lower() or x.phrase.lower() in r.phrase.lower() for x in rows):
                        for p in extra:
                            p.origin = "proposed_confirm"
                        rows.append(Row(phrase=r.phrase, intent=r.intent + " (proposed — confirm; not applied)", parameters=extra))
                have = {x.text.lower() for x in premises}
                qwords = set(re.findall(r"[a-z0-9]{3,}", inp.text.lower()))
                for pr in card.premises:
                    pw = set(re.findall(r"[a-z0-9]{3,}", pr.text.lower())) - {"the", "and", "that", "are", "for", "with", "companies"}
                    grounded = pw and len(pw & qwords) / len(pw) >= 0.6   # premise must come from the question's own words
                    if grounded and pr.text.lower() not in have and len(premises) < 3:
                        premises.append(pr)
                        plan.premises.append(pr.text)
                if card.family != plan.family:
                    notes.append(f"LLM read the family as {card.family}; term-library parse says {plan.family} (parse kept — confirm)")
            except (ParseFailed, SecretMissing) as e:
                notes.append(f"LLM reasoning unavailable ({type(e).__name__}); card built from the term library only")
        return ReasoningCard(family=plan.family, n_requested=plan.n_requested, rows=rows, premises=premises, time_windows=wins,
                             questions=qs, plan=plan, llm=llm_meta, notes=notes)


AGENT = QueryReasoner()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
