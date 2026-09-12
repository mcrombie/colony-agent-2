from copy import deepcopy
from html.parser import HTMLParser

import pytest

from src.email_report import build_report


@pytest.fixture
def colony():
    return {
        "day": 13, "colony_name": "Varenhold", "last_run_date": "2026-09-23",
        "population": 102, "food": 116, "wood": 51, "morale": 7, "health": 8, "security": 5,
        "recent_events": [{
            "day": 12, "run_date": "2026-09-23", "event_type": "river_market",
            "summary": "Barges brought grain and news.", "season": "High summer",
            "effects": {"food": 8, "wood": -3}, "civic_effects": {"treasury": 7, "culture": 2},
            "notes": ["A new household joined the river commons."],
            "ledger": {"food_produced": 13, "food_consumed": 9, "tax_revenue": 4,
                       "surplus_food_exported": 6, "export_income": 2},
        }],
        "commons": {
            "treasury": 38, "trust": 56, "culture": 14,
            "guilds": {"Keepers": 45, "Makers": 58, "Riverfolk": 61},
            "council": {"guild": "Riverfolk", "term": 2, "term_start": 8},
            "districts": {"grove": {"level": 1, "progress": 0},
                          "lantern": {"level": 0, "progress": 3},
                          "harbor": {"level": 0, "progress": 0},
                          "forum": {"level": 0, "progress": 0}},
            "active_project": "lantern",
            "completed_projects": [
                {"day": 11, "title": "Old completion must not be today's news"},
                {"day": 12, "title": "A quay garden opened"},
            ],
        },
    }


def test_report_contains_real_day_events_civic_metrics_and_attachment_instructions(colony):
    report = build_report(colony)
    assert set(report) == {"subject", "text", "html"}
    assert "Day 12" in report["subject"]
    for phrase in ("2026-09-23", "High summer", "Barges brought grain and news.",
                   "A new household joined", "Food stores: 116 food; daily change: +8",
                   "Timber: 51 wood; daily change: -3", "Culture: 14 / 100; daily change: +2",
                   "Council: Riverfolk", "Makers support: 58%", "Public atelier",
                   "3/6 funded work days", "active project", "A quay garden opened",
                   "Surplus food exported: 6", "Export income: 2", "HTML", "SVG"):
        assert phrase in report["text"]
    assert "Old completion must not" not in report["text"]
    assert "Old completion must not" not in report["html"]
    assert '<table role="presentation"' in report["html"]


def test_renderer_has_no_mutations_and_can_use_full_event_log(colony):
    original = deepcopy(colony)
    records = [{"day": 11, "summary": "STALE_EVENT"}, *colony["recent_events"],
               {"day": 99, "summary": "FUTURE_EVENT"}]
    record_copy = deepcopy(records)
    report = build_report(colony, records)
    assert "Barges brought" in report["text"]
    assert "STALE_EVENT" not in report["text"]
    assert "FUTURE_EVENT" not in report["text"]
    assert colony == original and records == record_copy


def test_missing_latest_event_does_not_present_stale_event_or_invent_zero_deltas(colony):
    report = build_report(colony, [{"day": 11, "summary": "STALE_EVENT", "effects": {"food": 900}}])
    assert "No event record is available" in report["text"]
    assert "STALE_EVENT" not in report["text"]
    assert "daily change: Not recorded" in report["text"]
    assert "+900" not in report["text"]
    assert "daily change: +0" not in report["text"]
    assert "High summer" not in report["text"]


def test_missing_legacy_civic_data_is_not_silently_migrated(colony):
    colony.pop("commons")
    colony.pop("last_run_date")
    colony["recent_events"] = []
    report = build_report(colony)
    assert "Date not recorded" in report["text"]
    assert "charter data is not recorded" in report["text"]
    assert "Treasury:" not in report["text"]
    assert "Council:" not in report["text"]


def test_matching_date_wins_over_wrong_date_duplicate(colony):
    matching = deepcopy(colony["recent_events"][0])
    stale = {**matching, "run_date": "2026-09-22", "summary": "WRONG_DATE"}
    report = build_report(colony, [matching, stale])
    assert "Barges brought" in report["text"]
    assert "WRONG_DATE" not in report["text"]


def test_untrusted_text_is_escaped_and_subject_has_no_header_injection(colony):
    colony["colony_name"] = 'City <script>alert("x")</script>\r\nBcc: other@example.test'
    colony["recent_events"][0]["summary"] = '<img src="https://tracking.test/pixel" onerror="x">'
    colony["recent_events"][0]["notes"] = ['<a href="javascript:x">unsafe</a>']
    colony["commons"]["completed_projects"][-1]["title"] = '<iframe src="bad"></iframe>'
    report = build_report(colony)
    assert "\n" not in report["subject"] and "\r" not in report["subject"]
    assert "<script" not in report["html"]
    assert "<img" not in report["html"]
    assert "<iframe" not in report["html"]
    assert "&lt;img" in report["html"]
    assert "&lt;iframe" in report["html"]
    assert "<script" in report["text"]


@pytest.mark.parametrize("url", ["http://example.com", "javascript:alert(1)", "data:text/html,x",
                                  "//example.com", "https://user:password@example.com", "https://",
                                  "https://example.com/\r\nInjected", 'https://example.com/"x',
                                  "https://example.com:99999", "https://example.com\\@evil.test"])
def test_unsafe_optional_links_are_omitted(colony, url):
    report = build_report(colony, dashboard_url=url, run_url=url)
    assert 'href="' not in report["html"]
    assert "Open the dashboard:" not in report["text"]
    assert "View the daily run:" not in report["text"]


def test_valid_links_are_optional_escaped_and_email_has_no_active_assets(colony):
    dashboard = "https://example.com/atlas?day=12&view=city"
    run = "https://github.com/mcrombie/colony-agent-2/actions/runs/123"
    report = build_report(colony, dashboard_url=dashboard, run_url=run)
    assert dashboard in report["text"] and run in report["text"]
    assert 'href="https://example.com/atlas?day=12&amp;view=city"' in report["html"]

    class Audit(HTMLParser):
        def handle_starttag(self, tag, attrs):
            assert tag not in {"script", "svg", "img", "iframe", "object", "link", "form"}
            assert not any(key.lower().startswith("on") for key, _ in attrs)

    Audit().feed(report["html"])
