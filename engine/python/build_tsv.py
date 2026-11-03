#!/usr/bin/env python3
"""Turn a run's verdicts into A4's TSV, taking every fact from the run's own data.

The agent judges; this writes. A verdict names a card by id and says what the read
concluded, so a URL, a title, a place or a date can only come from what discovery
actually returned. On the 2026-09-24 run 34 of 48 URLs were composed by hand, and each
one passed every check `stage` makes. That is why anything here that cannot be traced
to the run stops the build, and why a refusal writes nothing.

This also carries the previous run's roles forward. `stage` regenerates Roles.xlsx from
one TSV and `append` never touches an existing row, so a new role at a company already
in Review.xlsx lives only in Roles.xlsx. The next run would erase it.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import reconcile
import sync_export
from sync_export import A4_COLUMNS, CHECK_COLUMNS, EVIDENCE_COLUMNS, norm_role_url

INCLUDED = ("pertinente", "adiacente")
LABELS = INCLUDED + ("fuori profilo", "escluso")
RANK = {label: i for i, label in enumerate(INCLUDED)}

WORK_MODE_CELLS = {
    "onsite": "On-site (dichiarato)",
    "hybrid": "Hybrid (dichiarato)",
    "fully_remote": "Fully remote (dichiarato)",
    "to_verify": "To verify",
    None: "Not stated",
}
CURRICULAR_UNKNOWN = "To verify — curricular status"
VERIFIED_ON_PORTAL = "To verify — pagina datore non aperta; testo letto su aggregatore"
HYPOTHESIS = "Area A2 da confermare: ipotesi operativa."

# Enough to say which side of `In Italy?` a place falls on, which A4 requires. A place
# outside this list is not guessed at: the verdict has to state it.
COUNTRIES = frozenset(
    c.lower()
    for c in (
        "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Czech Republic", "Denmark",
        "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Ireland", "Latvia", "Lithuania",
        "Luxembourg", "Malta", "Netherlands", "Poland", "Portugal", "Romania", "Slovakia", "Slovenia",
        "Spain", "Sweden", "Norway", "Switzerland", "United Kingdom", "European Union",
    )
)
ITALY = frozenset({"italy", "italia"})

_NOTE_SPLIT = re.compile(r"(?:(?<=\s)|^)\d+\.\s(?=\[(?:pertinente|adiacente)\])")


class BuildError(Exception):
    pass


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_a2(text: str) -> dict[str, dict]:
    """Each `###` area of an A2, with its presence and its search terms."""
    areas: dict[str, dict] = {}
    for m in re.finditer(r"^### (.+?)\n(.*?)(?=^##+ |\Z)", text, re.M | re.S):
        body = m.group(2)
        presence = re.search(r"\*\*Presenza nel percorso:\*\*\s*(.+)", body)
        terms = re.search(r"\*\*Termini di ricerca[^*]*:\*\*\s*(.+)", body)
        areas[m.group(1).strip()] = {
            "presence": presence.group(1).strip() if presence else "",
            "terms": [t.strip() for t in terms.group(1).split(",") if t.strip()] if terms else [],
        }
    return areas


def _place_side(location: str) -> str | None:
    """'Yes' in Italy, 'No' elsewhere in the list, None when the text does not say."""
    tokens = [t.strip().lower() for t in location.split(",")]
    if any(t in ITALY for t in tokens):
        return "Yes"
    if any(t in COUNTRIES for t in tokens):
        return "No"
    return None


def _alternates(card: dict) -> list[str]:
    value = card.get("alternateUrls") or []
    return [value] if isinstance(value, str) else list(value)


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _known_companies(history: Path) -> set[str]:
    with history.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        next(reader, None)
        return {reconcile.norm_company(row[0]) for row in reader if row and row[0].strip()}


def _excluded_urls(run: Path) -> set[str]:
    data = _read_json(run / "final" / "exclusions.json", {"excluded": []})
    return {norm_role_url(e.get("url", "")) for e in data.get("excluded", [])}


def _check_rows(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader, [])
        idx = [header.index(c) if c in header else None for c in CHECK_COLUMNS]
        return {
            norm_role_url(row[0]): [row[i] if i is not None and i < len(row) else "" for i in idx]
            for row in reader
            if row and row[0].strip()
        }


def _number(values: list) -> str:
    return " | ".join(f"{i}. {v}" for i, v in enumerate(values, 1))


def _unnumber(cell: str, count: int) -> list[str]:
    parts = [re.sub(r"^\d+\.\s*", "", p.strip()) for p in cell.split(" | ")]
    return parts if len(parts) == count else [cell.strip()] * count


def _carried_roles(path: Path) -> list[dict]:
    """The roles of a previous run's TSV, each with what the TSV and its sidecar know."""
    header, rows = sync_export.parse_tsv(path.read_text(encoding="utf-8"))
    evidence = {}
    sidecar = path.parent / "role-evidence.csv"
    if sidecar.exists():
        with sidecar.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                evidence[norm_role_url(r["url"])] = r
    roles = []
    for cells in rows:
        col = dict(zip(header, cells))
        company = col["Company / Outreach Account"].strip()
        titles = reconcile.split_column(col["Matching Job Titles"], "Matching Job Titles")
        count = len(titles)
        scores = reconcile.split_column(col["Matching Score"], "Matching Score")
        notes = [p.strip() for p in _NOTE_SPLIT.split(re.sub(r"^\[[A-Z ]+\]\s*", "", col["Notes"])) if p.strip()]
        if len(notes) != count or len(scores) != count:
            raise BuildError(
                f"cannot carry {company} from {path}: {count} roles, {len(notes)} notes, {len(scores)} scores"
            )
        modes = _unnumber(col["Work Modes"], count)
        curricular = _unnumber(col["Curricular Evidence"], count)
        for i in range(count):
            values = sync_export._role_values(cells, i, count)
            url = values["Primary Job URL"]
            ev = evidence.get(norm_role_url(url), {})
            roles.append(
                {
                    "company": company,
                    "title": values["Job Title"],
                    "location": values["Location"],
                    "score": int(scores[i]) if scores[i].strip().isdigit() else None,
                    "url": url,
                    "mode": modes[i],
                    "curricular": curricular[i],
                    "note": notes[i],
                    "label": re.match(r"\[(\w+)\]", notes[i]).group(1),
                    "themes": [t.strip() for t in col["Master-fit Themes"].split(";") if t.strip()],
                    "sources": [s.strip() for s in col["Sources / Portals"].split(";") if s.strip()],
                    "posted": ev.get("posted", ""),
                    "alternate_urls": ev.get("alternate_urls") or values["Alternate / Portal URLs"],
                    "search_query": ev.get("search_query", ""),
                    "first_seen": ev.get("first_seen") or col["Last Checked"].strip(),
                    "row": col,
                }
            )
    return roles


def _new_role(verdict: dict, card: dict, posting: dict, areas: dict, checked: dict, date: str) -> dict:
    jid = verdict["id"]
    label = verdict["label"]
    for area in verdict.get("area") or []:
        if area not in areas:
            raise BuildError(f"{jid}: A2 has no area {area!r}")
        if areas[area]["presence"].lower().startswith("non prevista"):
            raise BuildError(f"{jid}: A2 rules out area {area!r}")
    if not verdict.get("area"):
        raise BuildError(f"{jid}: an included role needs an A2 area")
    if not verdict.get("quotes"):
        raise BuildError(f"{jid}: an included role needs a quote from its description")
    if posting.get("closedOnPage") in (True, "True", "true"):
        raise BuildError(f"{jid}: the posting is closed, so it cannot be included")
    mode = verdict.get("workMode")
    if mode not in WORK_MODE_CELLS:
        raise BuildError(f"{jid}: unknown work mode {mode!r}")

    url = verdict.get("url") or card["url"]
    alternates = _alternates(card)
    if url != card["url"]:
        if norm_role_url(url) not in checked and url not in alternates:
            raise BuildError(f"{jid}: {url} is neither the card's URL nor one the probe checked")
        alternates = [card["url"]] + [a for a in alternates if a != url]

    location = verdict.get("location") or card["location"]
    if verdict.get("location"):
        source = f"{card['location']} {posting.get('desc', '')}".lower()
        for token in (t.strip().lower() for t in location.split(",")):
            if token not in COUNTRIES and token not in ITALY and token not in source:
                raise BuildError(f"{jid}: stated location {location!r} is not in the posting")
    if _place_side(location) is None:
        raise BuildError(f"{jid}: cannot tell the country of {location!r}; the verdict must state `location`")

    quote = "; ".join(f"«{q}»" for q in verdict["quotes"])
    return {
        "company": verdict.get("company") or card["company"],
        # `|` separates A4's numbered values and nothing marks one inside a value.
        "title": re.sub(r"\s*\|\s*", " / ", card["title"]),
        "location": location,
        "score": verdict.get("score"),
        "url": url,
        "card_url": card["url"],
        "mode": WORK_MODE_CELLS[mode],
        "curricular": verdict.get("curricular") or CURRICULAR_UNKNOWN,
        "note": f"[{label}] {quote}: {verdict['reason']} Letto il {date}: LinkedIn.",
        "label": label,
        "themes": list(verdict["area"]),
        "sources": ["LinkedIn Jobs"],
        "posted": card.get("posted", ""),
        "alternate_urls": "; ".join(alternates),
        "search_query": card.get("discoveryQuery", ""),
        "first_seen": date,
        "row": None,
    }


def _company_row(roles: list[dict], known: set[str], date: str, unconfirmed: set[str]) -> tuple[tuple, list[str], list[dict]]:
    roles = sorted(roles, key=lambda r: (RANK[r["label"]], -(r["score"] or 0)))
    name = roles[0]["company"]
    # A carried place may name no country. Its previous row answered that, so nothing is
    # guessed here; a new role with no country was already refused.
    sides = {_place_side(r["location"]) or r["row"]["In Italy?"].strip() for r in roles}
    fresh = any(r["row"] is None for r in roles)
    previous = next((r["row"] for r in roles if r["row"]), None) or {}
    themes = list(dict.fromkeys(t for r in roles for t in r["themes"]))
    curricular = {r["curricular"] for r in roles}
    note_text = " ".join(f"{i}. {r['note']}" for i, r in enumerate(roles, 1))
    if set(t for r in roles if r["row"] is None for t in r["themes"]) & unconfirmed and HYPOTHESIS not in note_text:
        note_text += " " + HYPOTHESIS
    prefix = "[UPDATE EXISTING ROW]" if reconcile.norm_company(name) in known else "[NEW COMPANY]"
    cells = dict.fromkeys(A4_COLUMNS, "")
    cells.update({k: previous.get(k, "") for k in ("First Contact Date", "Recall", "Contact Name", "Contact Role", "Contact Email / LinkedIn")})
    cells.update(
        {
            "Company / Outreach Account": name,
            "In Italy?": sides.pop() if len(sides) == 1 else "Mixed",
            "Locations": _number([r["location"] for r in roles]),
            "Master-fit Themes": "; ".join(themes),
            "Matching Job Titles": _number([r["title"] for r in roles]),
            "Matching Score": _number(["" if r["score"] is None else r["score"] for r in roles]),
            "Job Links": _number([r["url"] for r in roles]),
            "Role Count": str(len(roles)),
            "Curricular Evidence": curricular.pop() if len(curricular) == 1 else _number([r["curricular"] for r in roles]),
            "Work Modes": _number([r["mode"] for r in roles]),
            "Sources / Portals": "; ".join(dict.fromkeys(s for r in roles for s in r["sources"])),
            "Previously Contacted?": previous.get("Previously Contacted?") or "To verify",
            "Contact Search Status": previous.get("Contact Search Status") or "New job found",
            "Outreach Decision": previous.get("Outreach Decision") or "Review",
            "Notes": f"{prefix} {note_text}",
            "Verification Status": VERIFIED_ON_PORTAL if fresh else previous.get("Verification Status", ""),
            "Last Checked": date if fresh else previous.get("Last Checked", date),
        }
    )
    # A4: pertinente first, then the higher score, then more roles. An adiacente 90 does
    # not lift a company whose best label is on a pertinente 70.
    order = (RANK[roles[0]["label"]], -(roles[0]["score"] or 0), -len(roles))
    return order, [_squeeze(cells[c]) if c != "Notes" else cells[c].strip() for c in A4_COLUMNS], roles


def write_declared(run: Path, admitted_languages: list[str]) -> Path:
    """The fields `admit` rules on, from the verdicts, with each URL from its card."""
    run = Path(run)
    cards = {c["sourceJobId"]: c for c in _read_json(run / "cards.json", [])}
    posted = {d.get("sourceJobId"): d for d in _read_json(run / "descriptions.json", [])}
    roles = []
    for v in _read_json(run / "verdicts.json", []):
        card = cards.get(v.get("id"))
        if card is None or not (v.get("label") in INCLUDED or v.get("ground") == "admit"):
            continue
        closed = (posted.get(v["id"]) or {}).get("closedOnPage") in (True, "True", "true")
        row = {
            "title": card["title"],
            "company": v.get("company") or card["company"],
            "url": card["url"],
            "stageNature": v.get("stageNature", True),
            "applicationOpen": v.get("applicationOpen", not closed),
        }
        if v.get("requiredLanguages"):
            row["requiredLanguages"] = v["requiredLanguages"]
            row["languageRequirement"] = v.get("languageRequirement", "all")
        if v.get("workMode"):
            row["workMode"] = v["workMode"]
        roles.append(row)
    target = run / "final" / "declared.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"admittedLanguages": admitted_languages, "roles": roles}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return target


def build(run, *, a2_path, history, date: str, carry=None) -> dict:
    run = Path(run)
    final = run / "final"
    cards = {c["sourceJobId"]: c for c in _read_json(run / "cards.json", [])}
    postings = {d.get("sourceJobId"): d for d in _read_json(run / "descriptions.json", []) if d.get("desc")}
    verdicts = _read_json(run / "verdicts.json")
    if verdicts is None:
        raise BuildError(f"no verdicts.json in {run}")
    areas = parse_a2(Path(a2_path).read_text(encoding="utf-8"))
    unconfirmed = {a for a, v in areas.items() if v["presence"].lower().startswith("da confermare")}
    known = _known_companies(Path(history))
    excluded_urls = _excluded_urls(run)
    checks = _check_rows(run / "employer-checks.csv")

    new_roles, read_exclusions = [], []
    seen_ids: set = set()
    dropped_by_admit = 0
    for v in verdicts:
        jid = v.get("id")
        if jid in seen_ids:
            raise BuildError(f"{jid}: two verdicts for one card")
        seen_ids.add(jid)
        card = cards.get(jid)
        if card is None:
            raise BuildError(f"{jid}: no card with this id in this run")
        posting = postings.get(jid)
        if posting is None:
            raise BuildError(f"{jid}: no read description, so it cannot carry a label (A1)")
        label = v.get("label")
        if label not in LABELS:
            raise BuildError(f"{jid}: label must be one of {', '.join(LABELS)}")
        text = _squeeze(posting["desc"])
        for quote in v.get("quotes") or []:
            if _squeeze(quote) not in text:
                raise BuildError(f"{jid}: quote not in its description: {quote}")
        in_admit = norm_role_url(card["url"]) in excluded_urls
        if v.get("ground") == "admit" and not in_admit:
            raise BuildError(f"{jid}: verdict says admit excludes it, and admit did not")
        if label in INCLUDED and in_admit:
            dropped_by_admit += 1
            continue
        if label in INCLUDED:
            new_roles.append(_new_role(v, card, posting, areas, checks, date))
        elif v.get("ground") != "admit":
            if label == "escluso" and not v.get("ground"):
                raise BuildError(f"{jid}: an exclusion needs a ground")
            read_exclusions.append(
                {
                    "company": card["company"],
                    "title": card["title"],
                    "url": card["url"],
                    "label": label,
                    "ground": v.get("ground", ""),
                    "reason": v.get("reason", ""),
                    "quotes": v.get("quotes") or [],
                }
            )

    carried: list[dict] = []
    if carry:
        taken = {norm_role_url(u) for r in new_roles for u in (r["url"], r["card_url"])}
        for role in _carried_roles(Path(carry)):
            urls = [role["url"]] + [a.strip() for a in role["alternate_urls"].split(";") if a.strip()]
            if not taken & {norm_role_url(u) for u in urls}:
                carried.append(role)
        checks = {**_check_rows(Path(carry).parent / "employer-checks.csv"), **checks}

    groups: dict[str, list[dict]] = {}
    for role in carried + new_roles:
        groups.setdefault(reconcile.norm_company(role["company"]), []).append(role)
    built = sorted((_company_row(g, known, date, unconfirmed) for g in groups.values()), key=lambda b: b[0])

    unresolved = []
    for jid, card in cards.items():
        if jid in seen_ids:
            continue
        missing = "giudizio" if jid in postings else "descrizione"
        unresolved.append(
            {
                "company": card["company"],
                "title": card["title"],
                "location": card["location"],
                "url": card["url"],
                "posted": card.get("posted"),
                "missing": missing,
            }
        )

    final.mkdir(parents=True, exist_ok=True)
    with (final / "run.tsv").open("w", encoding="utf-8") as f:
        f.write("\t".join(A4_COLUMNS) + "\n")
        for _, cells, _ in built:
            f.write("\t".join(cells) + "\n")
    with (final / "role-evidence.csv").open("w", encoding="utf-8", newline="") as f:
        columns = EVIDENCE_COLUMNS + ["first_seen"]
        w = csv.writer(f, delimiter=";")
        w.writerow(columns)
        for _, _, roles in built:
            for r in roles:
                w.writerow([r["url"], r["posted"], r["alternate_urls"], r["search_query"], r["first_seen"]])
    if checks:
        with (final / "employer-checks.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(CHECK_COLUMNS)
            w.writerows(checks.values())
    (final / "exclusions-read.json").write_text(json.dumps(read_exclusions, ensure_ascii=False, indent=1), encoding="utf-8")
    (final / "unresolved.json").write_text(json.dumps(unresolved, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {
        "roles_new": len(new_roles),
        "roles_carried": len(carried),
        "roles_out": len(new_roles) + len(carried),
        "companies_out": len(built),
        "excluded_by_admit": dropped_by_admit + sum(1 for v in verdicts if v.get("ground") == "admit"),
        "excluded_after_read": len(read_exclusions),
        "unresolved": len(unresolved),
    }
    (final / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary
