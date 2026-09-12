"""Shared SMTP transport regressions; every connection and credential is fake."""

from copy import deepcopy
from email import policy
from email.parser import BytesParser
import io
import json
import smtplib
import ssl
from types import SimpleNamespace
import zipfile

import pytest

from src import email_delivery as delivery


@pytest.fixture
def mail_world(tmp_path, monkeypatch):
    data, atlas = tmp_path / "src", tmp_path / "docs"
    data.mkdir()
    atlas.mkdir()
    state = {
        "day": 8, "colony_name": "Blergen", "last_run_date": "2026-09-11",
        "population": 12, "food": 120, "wood": 40, "health": 7,
        "morale": 7, "security": 5,
        "event_log": [{"day": 7, "run_date": "2026-09-11", "summary": "Élia mapped the river."}],
    }
    (data / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (data / "history.md").write_text("# Old history\nÉlia mapped the river.\n", encoding="utf-8")
    (atlas / "index.html").write_text("<!doctype html><html><body>Élia's atlas</body></html>", encoding="utf-8")
    (atlas / "colony.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><title>River map</title></svg>', encoding="utf-8")
    (atlas / "history.md").write_text("# Full chronicle\nÉlia mapped the river.\n", encoding="utf-8")
    env = {
        "COLONY_EMAIL_ENABLED": "true", "SMTP_HOST": "smtp.example.invalid",
        "SMTP_FROM": "Colony reports <sender@example.invalid>",
        "COLONY_EMAIL_TO": "reader@example.invalid", "SMTP_SECURITY": "ssl",
        "SMTP_USERNAME": "private-test-user", "SMTP_PASSWORD": "private-test-password",
    }
    def report(current, records, **kwargs):
        return {
            "subject": f"{current['colony_name']} · Day {current['day'] - 1}",
            "text": f"Élia's daily report: {records[-1]['summary']}",
            "html": "<html><body><p>Élia's daily report</p></body></html>",
        }
    monkeypatch.setattr(delivery, "build_report", report)
    # Passing env explicitly must not read, load, or depend on real local keys.
    monkeypatch.setattr(delivery, "load_local_env", lambda: pytest.fail("Explicit env loaded local secrets"))
    return SimpleNamespace(data=data, atlas=atlas, state=state, env=env)


@pytest.fixture
def smtp_mock(monkeypatch):
    scenario = SimpleNamespace(stage=None, failure=None, refused={}, quit_failure=False,
                               constructors=[], clients=[], messages=[], envelopes=[])

    class Server:
        def __init__(self):
            self.calls = []

        def step(self, name):
            self.calls.append(name)
            if scenario.stage == name:
                raise scenario.failure

        def ehlo(self):
            self.step("ehlo")
            return 250, b"mock hello"

        def starttls(self, *, context):
            assert context.check_hostname is True
            assert context.verify_mode == ssl.CERT_REQUIRED
            self.step("starttls")
            return 220, b"mock TLS"

        def login(self, username, password):
            assert username == "private-test-user"
            assert password == "private-test-password"
            self.step("login")

        def send_message(self, message, *, from_addr, to_addrs):
            self.step("send")
            scenario.messages.append(message)
            scenario.envelopes.append((from_addr, to_addrs))
            return scenario.refused

        def quit(self):
            self.calls.append("quit")
            if scenario.quit_failure:
                raise smtplib.SMTPServerDisconnected("mock QUIT failure after accepted DATA")

        def close(self):
            self.calls.append("close")

    def construct(kind, host, port, **kwargs):
        scenario.constructors.append((kind, host, port, kwargs))
        if scenario.stage == "connect":
            raise scenario.failure
        if kind == "ssl":
            assert kwargs["context"].check_hostname is True
            assert kwargs["context"].verify_mode == ssl.CERT_REQUIRED
        server = Server()
        scenario.clients.append(server)
        return server

    monkeypatch.setattr(delivery.smtplib, "SMTP_SSL", lambda host, port, **kwargs: construct("ssl", host, port, **kwargs))
    monkeypatch.setattr(delivery.smtplib, "SMTP", lambda host, port, **kwargs: construct("starttls", host, port, **kwargs))
    return scenario


def send(world, env=None):
    return delivery.send_latest_report(world.data, world.atlas, env=world.env if env is None else env)


def read_receipt(world):
    return json.loads((world.data / "email_delivery.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("enabled", [None, "false", "0", "no", "nonsense"])
def test_disabled_email_needs_no_snapshot_or_smtp_configuration(mail_world, smtp_mock, enabled):
    env = {} if enabled is None else {"COLONY_EMAIL_ENABLED": enabled}
    (mail_world.data / "state.json").unlink()
    assert send(mail_world, env) == "disabled"
    assert smtp_mock.constructors == []
    assert not (mail_world.data / "email_delivery.json").exists()


@pytest.mark.parametrize("missing", ["SMTP_HOST", "SMTP_FROM", "COLONY_EMAIL_TO", "SMTP_USERNAME", "SMTP_PASSWORD"])
def test_partial_enabled_configuration_fails_before_network(mail_world, smtp_mock, missing):
    env = {key: value for key, value in mail_world.env.items() if key != missing}
    with pytest.raises(delivery.DeliveryError):
        send(mail_world, env)
    assert smtp_mock.constructors == []
    assert not (mail_world.data / "email_delivery.json").exists()


def test_success_deduplicates_then_allows_next_day_and_changed_recipient(mail_world, smtp_mock):
    assert send(mail_world) == "sent"
    assert send(mail_world) == "already_sent"
    assert len(smtp_mock.messages) == 1
    first_id = smtp_mock.messages[0]["Message-ID"]

    state = deepcopy(mail_world.state)
    state.update(day=9, last_run_date="2026-09-12")
    state["event_log"].append({"day": 8, "run_date": "2026-09-12", "summary": "The second report."})
    (mail_world.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert send(mail_world) == "sent"
    second_id = smtp_mock.messages[-1]["Message-ID"]
    changed = {**mail_world.env, "COLONY_EMAIL_TO": "second-reader@example.invalid"}
    assert send(mail_world, changed) == "sent"
    assert send(mail_world, changed) == "already_sent"

    receipt = read_receipt(mail_world)
    assert len(smtp_mock.messages) == len(receipt["sent"]) == 3
    assert len({item["id"] for item in receipt["sent"]}) == 3
    assert first_id != second_id
    assert second_id != smtp_mock.messages[-1]["Message-ID"]
    assert receipt["sent"][0]["day"] == 7
    assert receipt["sent"][-1]["run_date"] == "2026-09-12"
    raw = (mail_world.data / "email_delivery.json").read_text(encoding="utf-8")
    for private in ("reader@example.invalid", "second-reader@example.invalid", "private-test-password", "private-test-user", "sender@example.invalid"):
        assert private not in raw


def test_sending_preserves_state_history_and_atlas_bytes(mail_world, smtp_mock):
    source_files = [mail_world.data / "state.json", mail_world.data / "history.md",
                    mail_world.atlas / "index.html", mail_world.atlas / "colony.svg",
                    mail_world.atlas / "history.md"]
    before = {path: path.read_bytes() for path in source_files}
    assert send(mail_world) == "sent"
    assert all(path.read_bytes() == value for path, value in before.items())
    assert smtp_mock.envelopes == [("sender@example.invalid", ["reader@example.invalid"])]
    kind, host, port, kwargs = smtp_mock.constructors[0]
    assert (kind, host, port) == ("ssl", "smtp.example.invalid", 465)
    assert 0 < kwargs["timeout"] <= 30


@pytest.mark.parametrize("stage,failure", [
    ("connect", TimeoutError("private-test-password reader@example.invalid")),
    ("login", smtplib.SMTPAuthenticationError(535, b"private-test-password reader@example.invalid")),
    ("send", smtplib.SMTPDataError(554, b"private-test-password reader@example.invalid")),
    ("send", smtplib.SMTPRecipientsRefused({"reader@example.invalid": (550, b"private-test-password")})),
])
def test_transport_failure_leaves_no_receipt_or_private_error_details(mail_world, smtp_mock, capsys, stage, failure):
    smtp_mock.stage, smtp_mock.failure = stage, failure
    with pytest.raises(delivery.DeliveryError) as error:
        send(mail_world)
    assert not (mail_world.data / "email_delivery.json").exists()
    captured = capsys.readouterr()
    output = str(error.value) + captured.out + captured.err
    assert "private-test-password" not in output
    assert "reader@example.invalid" not in output
    assert len(smtp_mock.constructors) == 1


def test_recipient_refusal_dictionary_is_not_recorded_as_success(mail_world, smtp_mock):
    smtp_mock.refused = {"reader@example.invalid": (550, b"provider refused")}
    with pytest.raises(delivery.DeliveryError, match="refused"):
        send(mail_world)
    assert not (mail_world.data / "email_delivery.json").exists()


def test_starttls_is_verified_and_precedes_credentials(mail_world, smtp_mock):
    env = {**mail_world.env, "SMTP_SECURITY": "starttls"}
    assert send(mail_world, env) == "sent"
    assert smtp_mock.clients[0].calls == ["ehlo", "starttls", "ehlo", "login", "send", "quit"]
    assert smtp_mock.constructors[0][2] == 587


def test_failed_starttls_never_logs_in_or_sends(mail_world, smtp_mock, capsys):
    smtp_mock.stage = "starttls"
    smtp_mock.failure = smtplib.SMTPNotSupportedError("private-test-password reader@example.invalid")
    with pytest.raises(delivery.DeliveryError) as error:
        send(mail_world, {**mail_world.env, "SMTP_SECURITY": "starttls"})
    assert "login" not in smtp_mock.clients[0].calls
    assert "send" not in smtp_mock.clients[0].calls
    assert not (mail_world.data / "email_delivery.json").exists()
    captured = capsys.readouterr()
    assert "private-test-password" not in str(error.value) + captured.out + captured.err


def test_failed_quit_after_accepted_data_still_records_success(mail_world, smtp_mock):
    smtp_mock.quit_failure = True
    assert send(mail_world) == "sent"
    assert smtp_mock.clients[0].calls[-2:] == ["quit", "close"]
    assert len(read_receipt(mail_world)["sent"]) == 1
    assert send(mail_world) == "already_sent"
    assert len(smtp_mock.messages) == 1


def test_receipt_write_failure_explicitly_reports_accepted_email(mail_world, smtp_mock, monkeypatch, capsys):
    def broken_write(*args, **kwargs):
        raise OSError("private-test-password reader@example.invalid")
    monkeypatch.setattr(delivery, "_write_receipt", broken_write)
    with pytest.raises(delivery.DeliveryError, match="SMTP accepted.*receipt failed.*inbox before retrying") as error:
        send(mail_world)
    assert len(smtp_mock.messages) == 1
    assert not (mail_world.data / "email_delivery.json").exists()
    captured = capsys.readouterr()
    assert "private-test-password" not in str(error.value) + captured.out + captured.err


def test_pending_world_transaction_blocks_send(mail_world, smtp_mock):
    pending = mail_world.data / ".pending-day.json"
    pending.write_text("pending", encoding="utf-8")
    with pytest.raises(delivery.DeliveryError, match="pending colony save"):
        send(mail_world)
    assert smtp_mock.constructors == []
    assert pending.read_text(encoding="utf-8") == "pending"
    assert not (mail_world.data / "email_delivery.json").exists()


def test_mime_contains_unicode_digest_and_complete_atlas_attachments(mail_world, smtp_mock):
    assert send(mail_world) == "sent"
    message = BytesParser(policy=policy.default).parsebytes(smtp_mock.messages[0].as_bytes())
    assert message.get_content_type() == "multipart/mixed"
    alternative = list(message.iter_parts())[0]
    assert alternative.get_content_type() == "multipart/alternative"
    assert "Élia" in message.get_body(preferencelist=("plain",)).get_content()
    assert "Élia" in message.get_body(preferencelist=("html",)).get_content()
    parts = {part.get_filename(): part for part in message.iter_attachments()}
    assert set(parts) == {"index.html", "colony.svg", "colony-atlas.zip"}
    assert parts["index.html"].get_content_type() == "text/html"
    assert parts["colony.svg"].get_content_type() == "image/svg+xml"
    assert parts["colony-atlas.zip"].get_content_type() == "application/zip"
    assert parts["index.html"].get_payload(decode=True) == (mail_world.atlas / "index.html").read_bytes()
    assert parts["colony.svg"].get_payload(decode=True) == (mail_world.atlas / "colony.svg").read_bytes()
    with zipfile.ZipFile(io.BytesIO(parts["colony-atlas.zip"].get_payload(decode=True))) as archive:
        assert set(archive.namelist()) == {"index.html", "colony.svg", "history.md"}
        for name in archive.namelist():
            assert archive.read(name) == (mail_world.atlas / name).read_bytes()


@pytest.mark.parametrize("setting,value", [
    ("SMTP_FROM", "sender@example.invalid\r\nBcc: unwanted@example.invalid"),
    ("COLONY_EMAIL_TO", "reader@example.invalid\nBcc: unwanted@example.invalid"),
    ("COLONY_EMAIL_TO", "one@example.invalid,two@example.invalid"),
    ("COLONY_EMAIL_TO", "one@example.invalid;two@example.invalid"),
])
def test_header_injection_and_extra_recipients_are_rejected(mail_world, smtp_mock, setting, value):
    with pytest.raises(delivery.DeliveryError):
        send(mail_world, {**mail_world.env, setting: value})
    assert smtp_mock.constructors == []
    assert not (mail_world.data / "email_delivery.json").exists()


def test_claude_recent_events_snapshot_uses_same_transport(mail_world, smtp_mock):
    state = deepcopy(mail_world.state)
    state["colony_name"] = "Varenhold"
    state["recent_events"] = state.pop("event_log")
    (mail_world.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
    assert send(mail_world) == "sent"
    assert "Varenhold" in smtp_mock.messages[0]["Subject"]


@pytest.mark.parametrize("change", ["missing_date", "different_day", "different_date", "missing_atlas"])
def test_inconsistent_snapshot_fails_before_network(mail_world, smtp_mock, change):
    state = deepcopy(mail_world.state)
    if change == "missing_date":
        state.pop("last_run_date")
    elif change == "different_day":
        state["event_log"][-1]["day"] -= 1
    elif change == "different_date":
        state["event_log"][-1]["run_date"] = "2026-09-10"
    else:
        (mail_world.atlas / "colony.svg").unlink()
    (mail_world.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(delivery.DeliveryError):
        send(mail_world)
    assert smtp_mock.constructors == []
