"""Dependency-free, offline atlas generated only from saved colony evidence."""

from __future__ import annotations

from html import escape
from typing import Any

from src.commons import DISTRICTS, GUILDS, migrate_state, season_for

COLORS = {"Keepers": "#557654", "Makers": "#aa663f", "Riverfolk": "#477f91"}


def render_map(state: dict[str, Any]) -> str:
    city = state["commons"]
    parts = ['''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 550" role="img" aria-labelledby="map-title map-desc">
<title id="map-title">Varenhold, the River Commons</title>
<desc id="map-desc">Four districts connected by river paths. Buildings grow with completed public works; the active district has a gold outline.</desc>
<defs><pattern id="paper" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r=".7" fill="#b9b49d" opacity=".24"/></pattern>
<pattern id="water" width="44" height="20" patternUnits="userSpaceOnUse"><path d="M2 10q8-5 16 0t16 0" fill="none" stroke="#bad1ca" stroke-width="1.3" opacity=".55"/></pattern></defs>
<rect width="1000" height="550" fill="#e8e5d5"/><rect width="1000" height="550" fill="url(#paper)"/>
<path d="M-40 385C180 380 185 260 414 280S630 190 717 215 930 135 1050 160" fill="none" stroke="#cad6c5" stroke-width="142"/>
<path d="M-40 385C180 380 185 260 414 280S630 190 717 215 930 135 1050 160" fill="none" stroke="#759b94" stroke-width="108"/>
<path d="M-40 385C180 380 185 260 414 280S630 190 717 215 930 135 1050 160" fill="none" stroke="url(#water)" stroke-width="103"/>
<g stroke="#c0ac8d" stroke-width="14" fill="none"><path d="M230 150L315 260 285 410"/><path d="M740 128L693 227 757 398"/><path d="M280 411Q523 448 757 398"/><path d="M230 150Q460 57 740 128"/></g>
<g stroke="#f6edda" stroke-width="5" fill="none" stroke-dasharray="2 8"><path d="M230 150L315 260 285 410"/><path d="M740 128L693 227 757 398"/></g>
<g fill="#637c5e" opacity=".65">''']
    for x, y in ((68, 95), (90, 110), (105, 86), (435, 112), (465, 105), (465, 143),
                 (909, 444), (940, 431), (923, 467), (500, 476), (520, 490), (54, 479)):
        parts.append(f'<path d="M{x} {y-18}l-13 29h26z"/><path d="M{x} {y-6}l-16 28h32z"/>')
    parts.append('</g><g font-family="Georgia,serif" fill="#3d6465"><text x="424" y="286" transform="rotate(-11 424 286)" font-size="19" font-style="italic">The river Aven</text></g>')
    coordinates = {"grove": (230, 151), "lantern": (740, 119), "harbor": (757, 390), "forum": (285, 410)}
    for key, name, guild, project, _ in DISTRICTS:
        x, y = coordinates[key]
        district = city["districts"][key]
        color = COLORS[guild]
        active = key == city["active_project"]
        outline = "#c4903d" if active else "#c9c8ae"
        parts.append(f'<a href="#district-{key}"><g><title>{escape(name)}: {escape(project)}, level {district["level"]}; {district["progress"]}/6 work days</title>')
        parts.append(f'<ellipse cx="{x}" cy="{y}" rx="127" ry="69" fill="#daddc5" stroke="{outline}" stroke-width="{3 if active else 1}"/>')
        if key == "grove":
            for i in range(5):
                parts.append(f'<path d="M{x-78+i*17} {y+20}l22-44" stroke="#92a276" stroke-width="8"/>')
        if key == "harbor":
            parts.append(f'<path d="M{x-88} {y-46}l-18-48m7 19l31-8" stroke="#886c51" stroke-width="10"/>')
        if key == "forum":
            parts.append(f'<ellipse cx="{x}" cy="{y+7}" rx="29" ry="17" fill="#aaa78b"/><ellipse cx="{x}" cy="{y+3}" rx="20" ry="10" fill="#739990"/>')
        for i in range(3 + district["level"]):
            hx = x - 60 + (i % 4) * 36
            hy = y - 19 + (i // 4) * 31
            parts.append(f'<rect x="{hx}" y="{hy}" width="25" height="22" rx="1" fill="#ece1c6" stroke="#afa17e"/><path d="M{hx-4} {hy}l16-15 17 15z" fill="{color}"/><rect x="{hx+10}" y="{hy+9}" width="6" height="13" fill="#6c6a55"/>')
        if active:
            parts.append(f'<path d="M{x+76} {y+14}v-35m-12 35v-35m-3 9h30m-30 13h30" stroke="#b58849" stroke-width="3"/>')
        ly = y + 79
        parts.append(f'<rect x="{x-120}" y="{ly-18}" width="240" height="47" rx="5" fill="#f6f2e7" opacity=".96"/><text x="{x}" y="{ly}" text-anchor="middle" font-family="Georgia,serif" font-size="21" fill="#273e35">{name}</text><text x="{x}" y="{ly+18}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" letter-spacing="1" fill="#677264">{guild.upper()} · WORKS LEVEL {district["level"]}</text></g></a>')
    parts.append('''<g transform="translate(558 205) rotate(-18)"><path d="M-24 0h48l-9 13h-28z" fill="#614f3d"/><path d="M0 0v-35l22 29H0" fill="#f3e3bf" stroke="#796a51"/></g>
<g transform="translate(945 55)" fill="#516c5b"><path d="M0-22l-8 29 8-6 8 6z"/><text y="-29" text-anchor="middle" font-size="12" font-family="Arial">N</text></g>
<text x="30" y="524" fill="#5c6f62" font-family="Arial,sans-serif" font-size="12">PUBLIC WORKS ATLAS · gold outline marks today's project</text></svg>''')
    return "".join(parts)


def _sparkline(records: list[dict[str, Any]], key: str, value: int, color: str) -> str:
    points = [(event["day"], event["snapshot"][key]) for event in records[-60:]
              if key in event.get("snapshot", {})]
    if not points:
        return '<p class="empty">Trend recording begins with the next daily turn.</p>'
    low = min(number for _, number in points)
    high = max(number for _, number in points)
    span = max(1, high-low)
    coords = [(12+i*326/max(1, len(points)-1), 73-(number-low)*55/span)
              for i, (_, number) in enumerate(points)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    title = f"{key.title()} from day {points[0][0]} to {points[-1][0]}, range {low} to {high}; latest {value}"
    x, y = coords[-1]
    return (f'<svg viewBox="0 0 350 108" role="img" aria-label="{escape(title)}">'
            f'<path d="M12 80H338" stroke="#dad8c8"/><polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.5"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>'
            f'<text x="12" y="102">Day {points[0][0]}</text><text x="338" y="102" text-anchor="end">Day {points[-1][0]} · {low}–{high}</text></svg>')


def render_dashboard(state: dict[str, Any], records: list[dict[str, Any]]) -> tuple[str, str]:
    legacy = "commons" not in state
    state = migrate_state(state)
    city = state["commons"]
    colony_map = render_map(state)
    name = escape(state["colony_name"])
    observed_day = max(0, state["day"] - 1)
    date = escape(state.get("last_run_date", "Awaiting next daily run"))
    latest = records[-1] if records else None
    latest_summary = escape(latest["summary"]) if latest else "The river city awaits its first recorded day."
    latest_notes = " ".join(escape(note) for note in (latest or {}).get("notes", []))
    last_source = (latest or {}).get("director", {}).get("source", "legacy record")
    update_note = ('The River Commons charter takes effect on the next daily turn. Existing people, stores and history are preserved.'
                   if legacy else 'A living record: one civic turn each UTC day. Public works and council decisions shape the map.')
    stat_cards = "".join(
        f'<div class="stat"><span>{label}</span><strong>{state[key]}</strong><small>{unit}</small></div>'
        for key, label, unit in (("population", "Citizens", "people at home"),
                                 ("food", "Granary", "food in store"),
                                 ("wood", "Timber yard", "wood available")))
    health_bars = "".join(
        f'<div class="meter-label"><span>{key.title()}</span><b>{state[key]} / 10</b></div>'
        f'<div class="meter"><i style="width:{state[key]*10}%"></i></div>'
        for key in ("morale", "health", "security"))
    guild_cards = "".join(
        f'<div class="guild"><div><span class="dot" style="background:{COLORS[guild]}"></span>{guild}'
        f'{"<em>in council</em>" if guild == city["council"]["guild"] else ""}<b>{city["guilds"][guild]}%</b></div>'
        f'<div class="meter"><i style="width:{city["guilds"][guild]}%;background:{COLORS[guild]}"></i></div></div>' for guild in GUILDS)
    projects = ""
    for key, title, guild, project, benefit in DISTRICTS:
        district = city["districts"][key]
        active = key == city["active_project"]
        status = f'{district["progress"]} of 6 work days' if active else 'Awaiting its next rotation'
        projects += (f'<article class="project {"active" if active else ""}" id="district-{key}">'
                     f'<div class="project-top"><span>{title}</span><b>{"IN PROGRESS" if active else "LEVEL " + str(district["level"])}</b></div>'
                     f'<h3>{project}</h3><p>{guild} · strengthens {benefit}</p>'
                     f'<div class="blocks" aria-label="{status}">'
                     + ''.join(f'<i class="{"filled" if i < district["progress"] else ""}"></i>' for i in range(6))
                     + f'</div><small>{status} · level {district["level"]}/4</small></article>')
    trends = "".join(
        f'<article class="trend"><span>{label}</span><strong>{value}</strong>{_sparkline(records, key, value, color)}</article>'
        for key, label, value, color in (("food", "Food stores", state["food"], "#557654"),
                                         ("wood", "Timber stores", state["wood"], "#aa663f"),
                                         ("treasury", "Treasury · coins", city["treasury"], "#477f91")))
    chronicle = ""
    for event in reversed(records[-10:]):
        effects = {**event.get("effects", {}), **event.get("civic_effects", {})}
        changes = " · ".join(f'{escape(key)} {value:+d}' for key, value in effects.items()) or "No recorded stat change"
        chronicle += (f'<article class="entry"><div class="entry-day">DAY <b>{event["day"]}</b></div><div>'
                      f'<h3>{escape(event["event_type"].replace("_", " ").title())}</h3>'
                      f'<p>{escape(event["summary"])} {" ".join(escape(note) for note in event.get("notes", []))}</p>'
                      f'<small>{changes}</small></div></article>')
    attempts = city.get("api_attempts", 0)
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="The daily atlas of Varenhold: a river city of guilds, culture and public works.">
<title>{name} · The River Commons</title><style>
:root{{--ink:#233d33;--muted:#6f7867;--paper:#f4f1e7;--line:#dcdcca;--green:#557654;--gold:#b18443}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}a{{color:inherit;text-underline-offset:4px}}.shell{{max-width:1380px;margin:auto;padding:0 48px}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);padding:23px 0;gap:20px}}.brand{{font-size:12px;letter-spacing:.2em;font-weight:750}}.brand:before{{content:"✳";font-size:23px;margin-right:12px;color:var(--green)}}nav{{display:flex;gap:23px;font-size:12px}}nav a{{text-decoration:none}}.hero{{display:flex;align-items:end;justify-content:space-between;padding:48px 0 32px;gap:30px}}.eyebrow{{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);font-weight:650}}h1{{font:normal clamp(48px,6vw,78px)/1.04 Georgia,serif;letter-spacing:-.055em;margin:11px 0 14px}}.hero p{{color:var(--muted);max-width:590px;margin:0}}.stamp{{text-align:right;white-space:nowrap}}.stamp strong{{display:block;font:32px Georgia,serif}}.stamp small{{display:block;color:var(--muted);font-size:11px;margin-top:6px}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-bottom:30px}}.stat{{padding:19px 25px;border-right:1px solid var(--line);display:grid;grid-template-columns:1fr auto}}.stat:first-child{{padding-left:0}}.stat:last-child{{border:0}}.stat span{{font-size:11px;letter-spacing:.1em;text-transform:uppercase}}.stat strong{{grid-row:span 2;font:38px Georgia,serif}}.stat small{{color:var(--muted);font-size:11px}}.main-grid{{display:grid;grid-template-columns:minmax(0,2.65fr) minmax(250px,1fr);gap:25px}}.map-panel{{background:#e8e5d5;border:1px solid #d9dac5;overflow:hidden;border-radius:4px}}.panel-heading{{display:flex;align-items:center;justify-content:space-between;padding:19px 23px;border-bottom:1px solid #d3d6bf}}h2{{font:24px Georgia,serif;margin:0}}.pill{{font-size:10px;letter-spacing:.09em;text-transform:uppercase;border:1px solid #bcc4ae;border-radius:20px;padding:5px 11px}}.map-panel svg{{width:100%;display:block}}.map-caption{{padding:0 23px 17px;color:#657561;font-size:11px}}aside{{background:#e9ecdf;border-radius:4px;padding:25px}}aside h2{{margin:8px 0 12px}}.council-note{{font-size:12px;color:var(--muted);margin:0 0 24px}}.guild{{margin:15px 0 18px;font-size:12px}}.guild>div:first-child{{display:flex;align-items:center;gap:7px;margin-bottom:7px}}.guild b{{margin-left:auto;font-weight:600}}.guild em{{font:10px system-ui;color:var(--muted);margin-left:2px}}.dot{{width:7px;height:7px;border-radius:50%}}.meter{{height:5px;background:#d8decd;border-radius:5px;overflow:hidden}}.meter i{{height:100%;display:block;background:var(--green)}}.civic-stats{{display:flex;gap:30px;border-top:1px solid #cdd6c2;margin-top:25px;padding-top:20px}}.civic-stats strong{{font:28px Georgia,serif;display:block}}.civic-stats small{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}.wellbeing{{margin-top:23px}}.meter-label{{display:flex;justify-content:space-between;font-size:11px;margin:13px 0 6px}}.meter-label b{{font-weight:500}}.dispatch{{margin:26px 0 39px;display:grid;grid-template-columns:150px 1fr;gap:24px;padding:26px 0;border-bottom:1px solid var(--line)}}.dispatch h2{{font-size:23px}}.dispatch p{{margin:0;font-family:Georgia,serif;font-size:22px;line-height:1.5}}.dispatch small{{display:block;color:var(--muted);margin-top:11px;font-size:11px}}.section-head{{display:flex;justify-content:space-between;align-items:center;margin:32px 0 20px;gap:15px}}.section-head p{{color:var(--muted);font-size:11px;margin:0}}.projects{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.project{{border:1px solid var(--line);padding:19px 17px;border-radius:4px;scroll-margin-top:20px}}.project.active{{border-color:#bc9b61;background:#f1ebd9}}.project:target{{outline:3px solid var(--gold);outline-offset:3px}}.project-top{{display:flex;justify-content:space-between;font-size:10px;color:var(--muted);gap:8px}}.project-top b{{font-size:8px;color:var(--gold);white-space:nowrap}}h3{{font:20px Georgia,serif;margin:13px 0 7px}}.project p{{font-size:11px;color:var(--muted);margin:0}}.blocks{{display:flex;gap:5px;margin:22px 0 8px}}.blocks i{{height:5px;flex:1;background:#dfe0cf}}.blocks i.filled{{background:#b18443}}.project small{{font-size:10px;color:var(--muted)}}.trends{{display:grid;grid-template-columns:repeat(3,1fr);gap:28px}}.trend{{border-bottom:1px solid var(--line);padding:4px 0 10px}}.trend span{{font-size:11px;color:var(--muted)}}.trend strong{{float:right;font:24px Georgia,serif}}.trend svg{{display:block;width:100%;margin-top:14px}}.trend svg text{{font:10px system-ui;fill:#78816e}}.empty{{font-size:12px;color:var(--muted);padding:25px 0}}.entries{{margin-bottom:45px}}.entry{{display:grid;grid-template-columns:76px 1fr;gap:17px;border-top:1px solid var(--line);padding:21px 0}}.entry-day{{font-size:9px;letter-spacing:.13em;color:var(--muted)}}.entry-day b{{display:block;font:27px Georgia,serif;color:var(--ink)}}.entry h3{{margin:0 0 6px}}.entry p{{font-size:13px;margin:0;color:#576750;max-width:980px}}.entry small{{font-size:10px;display:block;color:#7f856e;margin-top:10px}}footer{{border-top:1px solid var(--line);padding:25px 0 35px;color:var(--muted);font-size:11px;display:flex;justify-content:space-between;gap:20px}}.footnote{{font-size:11px;color:var(--muted);margin-top:14px}}
@media(max-width:1000px){{.shell{{padding:0 26px}}.main-grid{{grid-template-columns:1fr}}aside{{display:grid;grid-template-columns:1fr 1fr;gap:0 30px}}.projects{{grid-template-columns:1fr 1fr}}.wellbeing{{margin-top:0}}.civic-stats{{margin-top:0}}}}@media(max-width:600px){{.shell{{padding:0 18px}}header{{padding:17px 0}}nav{{gap:12px}}nav a:last-child{{display:none}}.hero{{padding-top:30px;display:block}}.stamp{{text-align:left;margin-top:20px}}.stamp strong{{display:inline;font-size:22px}}.stamp small{{display:inline;margin-left:12px}}.stats{{gap:0}}.stat{{padding:14px 10px;display:block}}.stat strong{{display:block;font-size:29px}}.stat small{{font-size:9px}}.stat span{{font-size:9px}}.panel-heading{{padding:15px}}h2{{font-size:21px}}.map-panel svg{{min-height:260px}}aside{{display:block}}.projects,.trends{{grid-template-columns:1fr}}.dispatch{{grid-template-columns:1fr;gap:13px}}.dispatch p{{font-size:20px}}.section-head{{align-items:start}}.section-head p{{max-width:140px;text-align:right}}footer{{display:block}}footer span{{display:block;margin-top:8px}}}}
</style></head><body><div class="shell">
<header><div class="brand">THE RIVER COMMONS</div><nav aria-label="Sections"><a href="#atlas">Atlas</a><a href="#works">Public works</a><a href="#chronicle">Chronicle</a></nav></header>
<main><section class="hero"><div><div class="eyebrow">A daily colony journal · Varenhold</div><h1>A city, in common.</h1><p>Three guilds. Four districts. One river to share.<br>{update_note}</p></div><div class="stamp"><div class="eyebrow">Latest completed turn</div><strong>Day {observed_day:03d}</strong><small>{date}</small></div></section>
<div class="stats">{stat_cards}</div><section class="main-grid" id="atlas"><div class="map-panel"><div class="panel-heading"><h2>{name}, along the Aven</h2><span class="pill">{season_for(observed_day)}</span></div>{colony_map}<div class="map-caption">Select a district to inspect its public works. Buildings reflect completed improvements.</div></div>
<aside><div><div class="eyebrow">The seven-day council</div><h2>{city['council']['guild']} take the chair.</h2><p class="council-note">Term {city['council']['term']} · next handover on day {city['council']['term_start']+7}<br>Guild support shapes the next rotation.</p>{guild_cards}</div><div><div class="civic-stats"><div><strong>{city['trust']}<small> / 100</small></strong><small>Public trust</small></div><div><strong>{city['culture']}<small> / 100</small></strong><small>Culture</small></div></div><div class="wellbeing">{health_bars}</div></div></aside></section>
<section class="dispatch"><div><div class="eyebrow">From the chronicle</div><h2>The latest dispatch</h2></div><div><p>{latest_summary}</p><small>{latest_notes or 'The original record is retained as part of the city’s history.'}</small></div></section>
<section id="works"><div class="section-head"><h2>Built by everyone.</h2><p>Six funded work days per improvement.</p></div><div class="projects">{projects}</div><p class="footnote">Each work day uses 3 timber and 2 coins. Investment rotates across all districts; level 4 districts receive restoration work.</p></section>
<section><div class="section-head"><h2>The city's pulse.</h2><p>Actual recorded turns · up to 60 days</p></div><div class="trends">{trends}</div><p class="footnote">Each trend uses its own labeled range. Legacy entries without snapshots are excluded.</p></section>
<section id="chronicle"><div class="section-head"><h2>Days along the river.</h2><p>Latest 10 entries · <a href="history.md">full chronicle</a></p></div><div class="entries">{chronicle or '<p class="empty">No events recorded yet.</p>'}</div></section></main>
<footer><div>Varenhold · The River Commons<br>Offline atlas generated from the saved simulation. No external assets or tracking.</div><span>Latest director: {escape(last_source)}<br>API attempts since charter: {attempts} · local turns use no API<br><a href="colony.svg">Download the map</a></span></footer></div></body></html>'''
    return html, colony_map
