"""Profile/settings JSON store (spec §10). Owned by Task B.

PHASE 0 STUB: returns an in-memory fake persona; reads and writes no files.
"""
from __future__ import annotations

import copy
from typing import Any

_STUB_PROFILE: dict[str, Any] = {
    "name": "Sam Rivera",
    "favorites": {"artist": "Taylor Swift", "playlist": "Deep Focus", "sites": ["ticketmaster.com"]},
    "contacts": {"Mom": ["+1 555 0100"]},
    "style": {"tone": "casual", "signature": "", "phrases": ["on my way", "sounds good"]},
    "address": {"full_name": "", "city": "", "email": ""},
}


def load_profile() -> dict[str, Any]:
    return copy.deepcopy(_STUB_PROFILE)


def profile_summary(profile: dict[str, Any], include_address: bool = False) -> str:
    fav = profile["favorites"]
    lines = [f"Name: {profile['name']}",
             f"Favorites: artist={fav['artist']}, playlist={fav['playlist']}, sites={', '.join(fav['sites'])}",
             f"Contacts: {', '.join(profile['contacts'])}",
             f"Style: {profile['style']['tone']}"]
    if include_address:
        addr = profile["address"]
        lines.append(f"Address: {addr['full_name']}, {addr['city']}, {addr['email']}")
    return "\n".join(lines)
