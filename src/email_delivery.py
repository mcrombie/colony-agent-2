"""Send a saved colony report over TLS SMTP, independently of advancing its world."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, parseaddr
import hashlib
import io
import json
import os
from pathlib import Path
import smtplib
import ssl
import tempfile
import zipfile

from src.config import load_local_env
from src.email_report import build_report
from src.run_day import colony_lock

ROOT = Path(__file__).resolve().parents[1]


class DeliveryError(RuntimeError):
    """A safe-to-log delivery failure with no provider response or private data."""


def _value(env, name, default=""):
    return env.get(name, default).strip()


def _address(value, setting):
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise DeliveryError(f"Invalid {setting} address")
    _, address = parseaddr(value)
    if not address or "@" not in address or any(c in address for c in ",; \t"):
        raise DeliveryError(f"Invalid {setting} address")
    # Only one mailbox, including for the envelope, is supported.
    if parseaddr(value)[1] != address or "," in value or ";" in value:
        raise DeliveryError(f"{setting} must contain one mailbox")
    return address


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    security: str
    username: str
    password: str
    sender: str
    recipient: str

    @classmethod
    def from_env(cls, env):
        required = ("SMTP_HOST", "SMTP_FROM", "COLONY_EMAIL_TO")
        missing = [name for name in required if not _value(env, name)]
        if missing:
            raise DeliveryError("Email is enabled but missing settings: " + ", ".join(missing))
        security = (_value(env, "SMTP_SECURITY") or "ssl").lower()
        if security not in {"ssl", "starttls"}:
            raise DeliveryError("SMTP_SECURITY must be ssl or starttls; unencrypted mail is not supported")
        try:
            port = int(_value(env, "SMTP_PORT") or ("465" if security == "ssl" else "587"))
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise DeliveryError("SMTP_PORT must be a valid port number") from None
        sender, recipient = _value(env, "SMTP_FROM"), _value(env, "COLONY_EMAIL_TO")
        _address(sender, "SMTP_FROM")
        recipient = _address(recipient, "COLONY_EMAIL_TO")
        username, password = _value(env, "SMTP_USERNAME"), _value(env, "SMTP_PASSWORD")
        if bool(username) != bool(password):
            raise DeliveryError("Set both SMTP_USERNAME and SMTP_PASSWORD, or neither for an authenticated relay")
        return cls(_value(env, "SMTP_HOST"), port, security, username, password, sender, recipient)


def _snapshot(data_dir: Path, atlas_dir: Path):
    if (data_dir / ".pending-day.json").exists():
        raise DeliveryError("Finish the pending colony save before sending its report")
    state = json.loads((data_dir / "state.json").read_text(encoding="utf-8"))
    records = state.get("event_log", state.get("recent_events", []))
    if not state.get("last_run_date"):
        raise DeliveryError("Advance the colony successfully before sending a dated daily report")
    date.fromisoformat(state["last_run_date"])
    completed = state["day"] - 1
    if not records or records[-1].get("day") != completed:
        raise DeliveryError("The saved day has no matching event report")
    if records[-1].get("run_date") != state["last_run_date"]:
        raise DeliveryError("The saved day and event report have different run dates")
    attachments = {}
    for name in ("index.html", "colony.svg", "history.md"):
        path = atlas_dir / name
        if path.exists():
            attachments[name] = path.read_bytes()
    if not {"index.html", "colony.svg"} <= attachments.keys():
        raise DeliveryError("Refresh the atlas before sending; its HTML and SVG are required")
    if sum(map(len, attachments.values())) > 8_000_000:
        raise DeliveryError("Atlas attachments exceed the 8 MB email budget")
    return state, records, attachments


def delivery_key(state, recipient):
    identity = "|".join((state["colony_name"], state["last_run_date"], str(state["day"] - 1), recipient.casefold()))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def build_message(state, records, attachments, config, *, dashboard_url="", run_url=""):
    report = build_report(state, records, dashboard_url=dashboard_url, run_url=run_url)
    key = delivery_key(state, config.recipient)
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = config.recipient
    message["Subject"] = report["subject"]
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["Message-ID"] = f"<{key}@colony-reports.invalid>"
    message.set_content(report["text"])
    message.add_alternative(report["html"], subtype="html")
    message.add_attachment(attachments["index.html"], maintype="text", subtype="html", filename="index.html")
    message.add_attachment(attachments["colony.svg"], maintype="image", subtype="svg+xml", filename="colony.svg")
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in attachments.items():
            archive.writestr(name, content)
    message.add_attachment(bundle.getvalue(), maintype="application", subtype="zip", filename="colony-atlas.zip")
    return message


def _send(message, config):
    server = None
    try:
        context = ssl.create_default_context()
        if config.security == "ssl":
            server = smtplib.SMTP_SSL(config.host, config.port, timeout=30, context=context)
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=30)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
        if config.username:
            server.login(config.username, config.password)
        refused = server.send_message(message, from_addr=_address(config.sender, "SMTP_FROM"), to_addrs=[config.recipient])
        if refused:
            raise DeliveryError("The SMTP server refused the report recipient")
    except DeliveryError:
        raise
    except Exception as exc:
        raise DeliveryError(f"SMTP delivery failed ({type(exc).__name__}); no delivery receipt was recorded") from None
    finally:
        # QUIT failure after accepted DATA must not turn a delivered message into a retry.
        if server is not None:
            try:
                server.quit()
            except Exception:
                try:
                    server.close()
                except Exception:
                    pass


def _write_receipt(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".mail-receipt-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def send_latest_report(data_dir=ROOT / "src", atlas_dir=ROOT / "docs", *, env=None):
    env = os.environ if env is None else env
    if _value(env, "COLONY_EMAIL_ENABLED", "false").lower() not in {"true", "1", "yes"}:
        return "disabled"
    config = MailConfig.from_env(env)
    with colony_lock(data_dir):
        state, records, attachments = _snapshot(data_dir, atlas_dir)
        receipt_path = data_dir / "email_delivery.json"
        ledger = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {"version": 1, "sent": []}
        if ledger.get("version") != 1 or not isinstance(ledger.get("sent"), list):
            raise DeliveryError("Invalid email delivery ledger; refusing an untracked resend")
        key = delivery_key(state, config.recipient)
        if any(item.get("id") == key for item in ledger["sent"]):
            return "already_sent"
        message = build_message(state, records, attachments, config,
                                dashboard_url=_value(env, "COLONY_DASHBOARD_URL"),
                                run_url=_value(env, "COLONY_RUN_URL"))
        _send(message, config)
        ledger["sent"] = (ledger["sent"] + [{"id": key, "day": state["day"] - 1,
                          "run_date": state["last_run_date"], "sent_at": datetime.now(timezone.utc).isoformat()}])[-90:]
        try:
            _write_receipt(receipt_path, ledger)
        except Exception:
            raise DeliveryError("SMTP accepted the email but saving its receipt failed; inspect your inbox before retrying") from None
        return "sent"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "src")
    parser.add_argument("--atlas-dir", type=Path, default=ROOT / "docs")
    parser.add_argument("--preview", type=Path, help="Write a local .eml preview without SMTP or receipts")
    args = parser.parse_args()
    load_local_env()
    try:
        if args.preview:
            with colony_lock(args.data_dir):
                state, records, attachments = _snapshot(args.data_dir, args.atlas_dir)
                config = MailConfig("", 465, "ssl", "", "", "Colony report <preview@example.invalid>", "preview@example.invalid")
                message = build_message(state, records, attachments, config)
                args.preview.parent.mkdir(parents=True, exist_ok=True)
                args.preview.write_bytes(message.as_bytes())
            print("Local email preview created; nothing sent.")
        else:
            status = send_latest_report(args.data_dir, args.atlas_dir)
            print({"disabled": "Daily email is disabled; configure SMTP and enable it to begin delivery.",
                   "already_sent": "This daily report was already sent; no duplicate email.",
                   "sent": "Daily email accepted by SMTP; receipt saved."}[status])
    except DeliveryError as exc:
        parser.exit(1, f"Email delivery: {exc}\n")
    except Exception as exc:
        parser.exit(1, f"Email delivery failed ({type(exc).__name__}); inspect local state and configuration.\n")


if __name__ == "__main__":
    main()
