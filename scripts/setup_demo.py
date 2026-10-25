"""First-run form: writes the private demo config that `scripts/start.sh live` selects.

    uv run --project agent python scripts/setup_demo.py [PATH]   # default ~/GazeDemoPrivate/demo.json

Asks for your name, sign-off style, the Mail account to send from and the people the agent may
message. Run it again to edit: current values are the defaults (press Enter to keep). The file
stays outside the repo (chmod 600); nothing is uploaded.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
from gaze_agent import demo_config  # noqa: E402

DEFAULT_PATH = Path.home() / "GazeDemoPrivate" / "demo.json"
PHONE = re.compile(r"\+[1-9][0-9]{7,14}")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def ask(question: str, default: str = "", *, check=None, hint: str = "") -> str:
    while True:
        shown = f" [{default}]" if default else ""
        answer = input(f"{question}{shown}: ").strip() or default
        if check is None or check(answer):
            return answer
        print(f"  {hint or 'Please try again.'}")


def handle_ok(value: str) -> bool:
    return bool(PHONE.fullmatch(value) or EMAIL.fullmatch(value))


def ask_contacts(current: dict[str, list[str]]) -> dict[str, list[str]]:
    print("\nPeople the agent may message. Use an alias you will say, e.g. TeamMail or Mom.")
    print("Address: an email (Mail or iMessage) or a phone number like +15551234567 (no spaces).")
    contacts: dict[str, list[str]] = {}
    for alias, handles in current.items():
        if ask(f"Keep {alias} -> {handles[0]}? (y/n)", "y").lower().startswith("y"):
            contacts[alias] = handles[:1]
    while True:
        alias = ask("Add a contact alias (Enter to finish)")
        if not alias:
            if contacts:
                return contacts
            print("  Add at least one contact.")
            continue
        handle = ask(f"  {alias}'s address", check=handle_ok,
                     hint="Use an email address or +countrycode and digits, no spaces.")
        contacts[alias] = [handle]


def main() -> int:
    path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_PATH
    old = json.loads(path.read_text()) if path.is_file() else {}
    persona = old.get("persona", {})
    print("Gaze Copilot demo setup. Press Enter to keep the value in [brackets].\n")
    name = ask("Your name", persona.get("name", ""), check=bool, hint="A name is required.")
    tone = ask("Message tone (e.g. casual, friendly, formal)", persona.get("style", {}).get("tone", "casual"))
    signature = ask("Sign-off for messages", persona.get("style", {}).get("signature", f"– {name}"))
    phrases = ask("Phrases you often use, comma-separated",
                  ", ".join(persona.get("style", {}).get("phrases", ["on my way", "sounds good"])))
    sender = ask("Mail account to send FROM (exactly as in Mail > Settings > Accounts)",
                 persona.get("address", {}).get("email", ""), check=lambda v: bool(EMAIL.fullmatch(v)),
                 hint="Enter the email address of an account set up in Apple Mail.")
    city = ask("City", persona.get("address", {}).get("city", ""))
    contacts = ask_contacts(persona.get("contacts", {}))
    favorites = persona.get("favorites", {})
    artist = ask("\nFavorite artist", favorites.get("artist", "Taylor Swift"))
    playlist = ask("Favorite playlist", favorites.get("playlist", "Deep Focus"))
    sites = ask("Favorite sites, comma-separated", ", ".join(favorites.get("sites", ["ticketmaster.com"])))

    root = path.parent
    data = {
        "format": demo_config.MANIFEST_FORMAT,
        "config_id": old.get("config_id", "hackathon-demo"),
        "persona": {
            "name": name,
            "favorites": {"artist": artist, "playlist": playlist,
                          "sites": [s.strip() for s in sites.split(",") if s.strip()]},
            "contacts": contacts,
            "style": {"tone": tone, "signature": signature,
                      "phrases": [p.strip() for p in phrases.split(",") if p.strip()]},
            "address": {"full_name": name, "city": city, "email": sender},
        },
        "approved_recipients": contacts,
        "data_dir": old.get("data_dir", str(root / "data")),
        "cache_dir": old.get("cache_dir", str(root / "cache")),
    }
    for key in ("data_dir", "cache_dir"):
        Path(data[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.chmod(0o600)
    try:
        demo_config.load_manifest(tmp)
    except demo_config.DemoConfigError as error:
        tmp.unlink(missing_ok=True)
        print(f"\nNot saved: {error}")
        return 1
    os.replace(tmp, path)
    # The agent keeps a working copy of the profile; drop it so the new answers take effect.
    (Path(data["data_dir"]) / "profile.json").unlink(missing_ok=True)
    print(f"\nSaved {path}. Contacts: {', '.join(contacts)}. Edit later: scripts/start.sh setup")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled; nothing saved.")
        raise SystemExit(1)
