"""Privately configure SMTP for both colonies using an explicitly authenticated gh CLI.

Run this yourself in a terminal. Password input is hidden and sent to GitHub on
standard input, never saved in this checkout or placed in process arguments.
"""

import argparse
from getpass import getpass
import subprocess
import sys

REPOSITORIES = ("mcrombie/colony-agent", "mcrombie/colony-agent-2")


def github(*arguments, secret=None):
    result = subprocess.run(["gh", *arguments], input=secret, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError("GitHub command failed. Check your gh login and repository permissions; no secret was printed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="The single address that receives both reports")
    parser.add_argument("--sender", required=True, help="The SMTP sender mailbox")
    parser.add_argument("--host", required=True, help="SMTP hostname; Gmail uses smtp.gmail.com")
    parser.add_argument("--username", help="SMTP login; defaults to sender")
    parser.add_argument("--security", choices=("ssl", "starttls"), default="ssl")
    parser.add_argument("--port", type=int, help="Default: 465 for ssl, 587 for starttls")
    args = parser.parse_args()
    try:
        # Do not extract or reuse git credentials. gh must already be authorized.
        github("auth", "status", "--hostname", "github.com")
    except (OSError, RuntimeError):
        parser.exit(1, "First install GitHub CLI if needed and run: gh auth login --hostname github.com\nThen rerun this setup command.\n")
    if not sys.stdin.isatty():
        parser.exit(1, "Run this setup interactively in your own terminal so the password stays private.\n")
    print("This configures daily email for both colonies and sends each latest saved report once.")
    password = getpass("SMTP password / provider app password (hidden): ")
    if not password:
        parser.exit(1, "No password supplied; nothing changed.\n")
    settings = {"COLONY_EMAIL_TO": args.to, "SMTP_FROM": args.sender,
                "SMTP_HOST": args.host, "SMTP_PORT": str(args.port or (465 if args.security == "ssl" else 587)),
                "SMTP_SECURITY": args.security, "SMTP_USERNAME": args.username or args.sender,
                "SMTP_PASSWORD": password}
    try:
        for repo in REPOSITORIES:
            for name, value in settings.items():
                github("secret", "set", name, "--repo", repo, secret=value)
            github("variable", "set", "COLONY_EMAIL_ENABLED", "--repo", repo, "--body", "true")
            github("workflow", "run", "advance-colony.yml", "--repo", repo, "-f", "email_only=true")
            print(f"Configured {repo}; requested the latest report without advancing its world.")
    except (OSError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\nSetup may be partly complete. Rerunning is safe; saved receipts prevent normal duplicate delivery.\n")
    print("Daily email is enabled. Check both Actions runs and your inbox for delivery.")


if __name__ == "__main__":
    main()
