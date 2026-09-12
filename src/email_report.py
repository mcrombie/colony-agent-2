"""Render an evidence-based daily email; delivery and attachments belong to the caller."""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlsplit

from src.commons import DISTRICTS, GUILDS

_INK = "#263e33"
_MUTED = "#687363"
_COLORS = {"Keepers": "#557654", "Makers": "#aa663f", "Riverfolk": "#477f91"}
_METRICS = (
    ("population", "Citizens", "people"), ("food", "Food stores", "food"),
    ("wood", "Timber", "wood"), ("morale", "Morale", "/ 10"),
    ("health", "Health", "/ 10"), ("security", "Security", "/ 10"),
    ("treasury", "Treasury", "coins"), ("trust", "Public trust", "/ 100"),
    ("culture", "Culture", "/ 100"),
)
_LEDGER = (
    ("food_produced", "Food produced"), ("food_consumed", "Food consumed"),
    ("timber_gathered", "Timber gathered"), ("tax_revenue", "Tax revenue"),
    ("maintenance", "Maintenance cost"), ("project_timber", "Project timber used"),
    ("project_coins", "Project coins used"),
    ("surplus_food_exported", "Surplus food exported"),
    ("surplus_timber_exported", "Surplus timber exported"),
    ("export_income", "Export income"),
)


def _text(value: Any) -> str:
    return str(value)


def _html(value: Any) -> str:
    return escape(_text(value), quote=True)


def _safe_https_url(value: str) -> str:
    """Accept explicit HTTPS links without credentials, controls or markup."""
    if not isinstance(value, str) or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return ""
    if any(char in value for char in '<>"\\'):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return ""
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return ""
        parsed.hostname.encode("idna")
    except (ValueError, UnicodeError):
        return ""
    return value


def _heading(title: str) -> str:
    return f'<h2 style="font:24px Georgia,serif;color:{_INK};margin:0 0 14px">{escape(title)}</h2>'


def _section(content: str) -> str:
    return f'<tr><td style="padding:24px 30px;border-top:1px solid #dddccc">{content}</td></tr>'


def _bar(percent: int, color: str) -> str:
    percent = max(0, min(100, percent))
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="background:#dfe3d5"><tr><td width="{percent}%" height="6" '
            f'style="height:6px;font-size:0;line-height:0;background:{color}"></td>'
            f'<td width="{100-percent}%" height="6" style="height:6px;font-size:0;line-height:0"></td></tr></table>')


def build_report(state: dict[str, Any], records: list[dict[str, Any]] | None = None,
                 *, dashboard_url: str = "", run_url: str = "") -> dict[str, str]:
    """Return subject, text and HTML without I/O, state mutation or made-up history.

    Only an event matching the latest completed day supplies event text or deltas.
    Missing measurements remain explicitly unrecorded. The transport attaches the
    complete offline atlas HTML (with its map inline) and standalone SVG map.
    """
    completed_day = state["day"] - 1
    source = records if records is not None else state.get("recent_events", [])
    candidates = [record for record in source if record.get("day") == completed_day]
    dated = [record for record in candidates
             if record.get("run_date") == state.get("last_run_date")]
    latest = (dated or candidates)[-1] if candidates else None
    city = state.get("commons", {})
    name = _text(state.get("colony_name", "Varenhold"))
    day_label = f"Day {completed_day}" if completed_day >= 0 else "No completed turn"
    date_label = _text((latest or {}).get("run_date") or state.get("last_run_date") or "Date not recorded")
    season = (latest or {}).get("season")
    event_title = _text(latest.get("event_type", "Recorded event")).replace("_", " ").title() if latest else "State update"
    summary = _text(latest.get("summary", "No event summary was recorded.")) if latest else "No event record is available for this completed turn. The values below are the saved state."
    notes = [_text(note) for note in (latest or {}).get("notes", [])]
    subject = " ".join(f"{name} · {day_label}: {event_title}".split())[:180]
    date_line = f"{day_label} · {date_label}" + (f" · {season}" if season else "")
    plain = [f"{name} — The River Commons", date_line, "", event_title, summary, *notes, "", "SAVED STATE AND RECORDED DAILY CHANGES"]
    sections = []
    event_html = (f'<p style="font-size:11px;letter-spacing:1px;color:{_MUTED};margin:0 0 9px">{_html(date_line)}</p>'
                  + _heading(event_title)
                  + f'<p style="font:19px/1.6 Georgia,serif;margin:0;color:{_INK}">{_html(summary)}</p>')
    if notes:
        event_html += '<ul style="padding-left:19px;margin:14px 0 0">' + ''.join(
            f'<li style="margin:7px 0;color:{_MUTED};font-size:14px;line-height:1.5">{_html(note)}</li>' for note in notes) + '</ul>'
    sections.append(_section(event_html))
    deltas = {**(latest or {}).get("effects", {}), **(latest or {}).get("civic_effects", {})}
    metric_rows = []
    for key, label, unit in _METRICS:
        container = city if key in {"treasury", "trust", "culture"} else state
        if key not in container:
            continue
        delta = deltas.get(key)
        change = f"{delta:+d}" if type(delta) is int else "Not recorded"
        value = f"{container[key]} {unit}"
        plain.append(f"{label}: {value}; daily change: {change}")
        color = "#557654" if type(delta) is int and delta > 0 else "#a75f43" if type(delta) is int and delta < 0 else _MUTED
        metric_rows.append(f'<tr><td style="padding:9px 0;border-bottom:1px solid #e6e5d8">{label}</td>'
                           f'<td align="right" style="padding:9px 8px;border-bottom:1px solid #e6e5d8;font-weight:bold">{_html(value)}</td>'
                           f'<td align="right" style="padding:9px 0;border-bottom:1px solid #e6e5d8;color:{color}">{_html(change)}</td></tr>')
    metrics = (_heading("The city's pulse")
               + '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="font-size:13px">'
               + '<tr><th align="left" style="font-size:10px;color:#687363">MEASURE</th><th align="right" style="font-size:10px;color:#687363;padding-right:8px">CURRENT</th><th align="right" style="font-size:10px;color:#687363">CHANGE</th></tr>'
               + ''.join(metric_rows) + '</table>'
               + f'<p style="font-size:11px;color:{_MUTED};margin:12px 0 0">Changes appear only when recorded in this turn. An omitted change is not an inferred historical measurement.</p>')
    sections.append(_section(metrics))
    if city:
        council = city.get("council", {})
        guild = council.get("guild", "Not recorded")
        council_line = f"Council: {guild}"
        if "term" in council:
            council_line += f" · term {council['term']}"
        if "term_start" in council:
            council_line += f" · term began on day {council['term_start']}"
        plain.extend(["", "COUNCIL AND PUBLIC WORKS", council_line])
        civic_html = _heading("A city, in common") + f'<p style="font-size:14px;margin:0 0 16px">{_html(council_line)}</p>'
        for guild_name in GUILDS:
            support = city.get("guilds", {}).get(guild_name)
            if type(support) is not int:
                continue
            plain.append(f"{guild_name} support: {support}%")
            civic_html += (f'<p style="font-size:12px;margin:14px 0 6px">{guild_name} <strong>{support}%</strong></p>'
                           + _bar(support, _COLORS[guild_name]))
        projects = []
        for key, district_name, _, project_name, _ in DISTRICTS:
            district = city.get("districts", {}).get(key)
            if not district:
                continue
            active = city.get("active_project") == key
            level = district.get("level", "Not recorded")
            progress = district.get("progress")
            progress_label = f"{progress}/6 funded work days" if type(progress) is int else "Work progress not recorded"
            project_line = f"{district_name}: {project_name} · level {level}/4 · {progress_label}"
            project_line += " · active project" if active else " · awaiting rotation"
            plain.append(project_line)
            projects.append(f'<tr><td style="padding:13px 12px;background:{"#f1ebd9" if active else "#f3f2e8"};border-bottom:5px solid #faf9f2">'
                            f'<strong style="font-size:13px">{district_name}{" · ACTIVE" if active else ""}</strong>'
                            f'<p style="font:17px Georgia,serif;margin:5px 0">{project_name}</p>'
                            f'<p style="font-size:11px;color:{_MUTED};margin:0 0 7px">Level {_html(level)}/4 · {_html(progress_label)}</p>'
                            + (_bar(round(progress / 6 * 100), "#b18443") if type(progress) is int and active else "") + '</td></tr>')
        civic_html += '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:19px">' + ''.join(projects) + '</table>'
        completions = [entry for entry in city.get("completed_projects", []) if entry.get("day") == completed_day]
        if completions:
            plain.append("Completed this turn:")
            civic_html += f'<p style="font-size:12px;color:{_MUTED};margin:15px 0 5px">Completed this turn</p><ul style="padding-left:19px;margin:0">'
            for entry in completions:
                title = _text(entry.get("title", "Public work completion recorded"))
                plain.append(f"- {title}")
                civic_html += f'<li style="font-size:13px;line-height:1.6">{_html(title)}</li>'
            civic_html += '</ul>'
        sections.append(_section(civic_html))
    else:
        plain.extend(["", "River Commons charter data is not recorded for this state."])
    ledger = (latest or {}).get("ledger", {})
    ledger_lines = [f"{label}: {ledger[key]}" for key, label in _LEDGER if key in ledger]
    if ledger_lines:
        plain.extend(["", "THE DAILY ECONOMY", *ledger_lines])
        sections.append(_section(_heading("The daily economy")
                                 + '<p style="font-size:13px;line-height:1.85;margin:0">'
                                 + '<br>'.join(_html(line) for line in ledger_lines) + '</p>'))
    links = [(label, _safe_https_url(url)) for label, url in
             (("Open the dashboard", dashboard_url), ("View the daily run", run_url))]
    links = [(label, url) for label, url in links if url]
    attachment_note = "Attached: the complete offline atlas (HTML, including the illustrated map) and a separate SVG map. Download the HTML attachment and open it in your browser to explore the visual state; it needs no internet connection."
    plain.extend(["", "EXPLORE THE CITY", attachment_note])
    footer = _heading("Your atlas is attached") + f'<p style="font-size:13px;line-height:1.7;color:{_MUTED};margin:0">{attachment_note}</p>'
    if links:
        footer += '<p style="margin:18px 0 0;font-size:13px;line-height:1.9">'
        for label, url in links:
            plain.append(f"{label}: {url}")
            footer += f'<a href="{_html(url)}" style="color:#456c55;text-decoration:underline">{label}</a><br>'
        footer += '</p>'
    sections.append(_section(footer))
    html = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_html(subject)}</title></head>'
            f'<body style="margin:0;padding:20px 10px;background:#eaece1;color:{_INK};font-family:Arial,Helvetica,sans-serif">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td align="center">'
            '<table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:640px;background:#faf9f2">'
            f'<tr><td style="padding:30px;background:#263e33;color:#f4efdc"><p style="font-size:10px;letter-spacing:2px;margin:0 0 12px">THE RIVER COMMONS</p>'
            f'<h1 style="font:39px Georgia,serif;font-weight:normal;margin:0 0 10px">{_html(name)}, along the river.</h1>'
            '<p style="font-size:12px;line-height:1.7;margin:0;color:#d5ddc7">Three guilds. Four districts. One river to share.</p></td></tr>'
            + ''.join(sections)
            + '<tr><td style="padding:19px 30px;background:#edf0e4;font-size:10px;color:#6c7662;line-height:1.6">A daily record of the saved colony. No external images, tracking pixels or scripts.</td></tr>'
            + '</table></td></tr></table></body></html>')
    return {"subject": subject, "text": "\n".join(plain).rstrip() + "\n", "html": html}
