"""Human-run screen inspection; --fixture is safe without desktop access."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path

from gaze_agent.screen import get_screen
from gaze_agent.screen import ax


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--fixture", type=Path, help="compact an AX JSON dump without reading the desktop")
    inputs.add_argument("--dump-ax", type=Path, help="save a human-recorded AX tree, without native handles")
    parser.add_argument("--ax-only", action="store_true", help="read AX only, without taking a screenshot")
    parser.add_argument("--json", action="store_true", help="print the compact snapshot as JSON")
    args = parser.parse_args(argv)
    if args.fixture:
        data = json.loads(args.fixture.read_text())
        snapshot, _ = ax.compact_tree(data["tree"], **{key: data[key] for key in
                                    ("app", "bundle_id", "window_title", "url") if key in data})
    elif args.dump_ax:
        if args.dump_ax.exists():
            parser.error("the AX dump destination already exists; choose a new file")
        dump = {}
        snapshot, _ = ax.read_snapshot(dump=dump)
        # Do not overwrite a previous human capture, or store opaque AX handles.
        with args.dump_ax.open("x") as stream:
            json.dump(dump, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    elif args.ax_only:
        snapshot, _ = ax.read_snapshot()
    else:
        snapshot = get_screen()
    print(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2) if args.json else snapshot.to_prompt())


if __name__ == "__main__":
    main()
