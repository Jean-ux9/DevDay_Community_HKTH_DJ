"""Launcher modes (scripts/start.sh, dev.sh, dev-browser.sh) against stub tools only.

Copies of the scripts run in a temporary checkout with a synthetic .env. node, pnpm, uv, curl, open,
pgrep and vite are stubs that log their arguments and environment, so no Electron, browser, real
agent, OpenAI call or desktop action can start. The only real processes are the stubs and `sh`.
"""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("start.sh", "dev.sh", "dev-browser.sh")
KEY = "synthetic-launcher-key-7"
REAL_AGENT = "uv run --project agent python -m gaze_agent.server"

# Every stub appends one line to $LAUNCH_LOG. `wait_term` stays up until SIGTERM/SIGINT, like a server.
STUBS = {
    "pnpm": 'echo "pnpm $* | MODE=${GAZE_AGENT_MODE-<unset>} CMD=${GAZE_AGENT_CMD-<unset>} '
            'SOURCE=${GAZE_SOURCE-<unset>} DEMO=${DEMO_MODE-<unset>} KEY=${OPENAI_API_KEY:+present}" >> "$LAUNCH_LOG"',
    "uv": 'echo "uv $* | TOKEN=${GAZE_TOKEN-} PORT=${GAZE_PORT-}" >> "$LAUNCH_LOG"\n'
          'case "$*" in *fake_agent.py*) wait_term uv ;; esac',
    # Version check passes; each free-port request gets the next number.
    "node": 'case "$*" in *createServer*) n=$(cat "$LAUNCH_LOG.port" 2>/dev/null || echo 41000); '
            'echo $((n + 1)) > "$LAUNCH_LOG.port"; echo $((n + 1)) ;; esac',
    "curl": "exit 0",
    "open": 'echo "open $*" >> "$LAUNCH_LOG"',
    "pgrep": 'echo "pgrep $*" >> "$LAUNCH_LOG"; for pid in ${FAKE_PGREP_PIDS-}; do echo "$pid"; done',
}
WAIT_TERM = ('wait_term() { trap \'echo "$1 got TERM" >> "$LAUNCH_LOG"; exit 0\' TERM INT; '
             'while :; do sleep 0.05; done; }\n')


@dataclass
class Sandbox:
    tmp: Path
    root: Path
    bin: Path
    log: Path

    def write_env(self, text):
        (self.root / ".env").write_text(text)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def environ(self, extra=None):
        # Nothing inherited: no real key, PATH reaches only stubs and system utilities.
        base = {"PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.tmp),
                "LAUNCH_LOG": str(self.log), "LANG": "C", "NO_OPEN": "1"}
        return base | (extra or {})

    def run(self, *args, script="start.sh", env=None, timeout=20):
        return subprocess.run(["/bin/sh", str(self.root / "scripts" / script), *args], cwd=self.tmp,
                              env=self.environ(env), capture_output=True, text=True, timeout=timeout)


def _stub(path, body):
    path.write_text("#!/bin/sh\n" + WAIT_TERM + body + "\n")
    path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy2(ROOT / "scripts" / name, root / "scripts" / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        _stub(bin_dir / name, body)
    vite = root / "overlay/node_modules/.bin/vite"
    vite.parent.mkdir(parents=True)
    _stub(vite, 'echo "vite $*" >> "$LAUNCH_LOG"\nwait_term vite')
    return Sandbox(tmp_path, root, bin_dir, tmp_path / "calls.log")


def launched(sandbox):
    """The `pnpm dev` call that would start Electron, or None."""
    return next((line for line in sandbox.calls() if line.startswith("pnpm dev")), None)


def test_launcher_scripts_parse():
    for name in SCRIPTS:
        subprocess.run(["/bin/sh", "-n", str(ROOT / "scripts" / name)], check=True)


def test_stubs_shadow_every_tool_that_could_start_something(sandbox):
    env = sandbox.environ()
    for tool in ("node", "pnpm", "uv", "curl", "open", "pgrep"):
        assert shutil.which(tool, path=env["PATH"]) == str(sandbox.bin / tool)


@pytest.mark.parametrize("args", [[], ["preview"], ["fake"]])
def test_default_and_preview_start_the_fake_agent(sandbox, args):
    sandbox.write_env(f"OPENAI_API_KEY={KEY}\nGAZE_AGENT_CMD={REAL_AGENT}\n")
    result = sandbox.run(*args)
    assert result.returncode == 0, result.stderr
    assert "pnpm install --frozen-lockfile --reporter=silent" in sandbox.calls()[0]
    # Electron main maps preview to the fake agent; an empty GAZE_AGENT_CMD also masks the .env one.
    assert launched(sandbox).endswith("| MODE=preview CMD= SOURCE=mouse DEMO=<unset> KEY=")
    assert not any(line.startswith("uv ") for line in sandbox.calls())
    assert "PREVIEW: fake agent" in result.stdout and "scripts/start.sh live" in result.stdout


def test_preview_never_runs_an_inherited_agent_command(sandbox):
    result = sandbox.run("preview", env={"GAZE_AGENT_CMD": REAL_AGENT})
    assert result.returncode == 0, result.stderr
    assert "| MODE=preview CMD= " in launched(sandbox)
    assert "Ignoring GAZE_AGENT_CMD" in result.stdout


@pytest.mark.parametrize("dotenv, shell", [
    (None, {}),
    ("OPENAI_API_KEY=\n", {}),
    ('OPENAI_API_KEY=""\n', {}),
    ("OPENAI_API_KEY=   # fill me in\n", {}),
    (f"# OPENAI_API_KEY={KEY}\nOPENAI_MODEL_AGENT=m\n", {}),
    (f"OPENAI_API_KEY={KEY}\nOPENAI_API_KEY=\n", {}),  # the last assignment wins, as in dotenv
    (f"OPENAI_API_KEY={KEY}\n", {"OPENAI_API_KEY": ""}),  # set in the shell wins, even empty
    (None, {"REPLAY": "record"}),
])
def test_live_without_a_key_fails_before_anything_starts(sandbox, dotenv, shell):
    if dotenv is not None:
        sandbox.write_env(dotenv)
    result = sandbox.run("live", env=shell)
    assert result.returncode == 1
    assert "LIVE needs OPENAI_API_KEY" in result.stderr and "Nothing was started" in result.stderr
    assert sandbox.calls() == []  # no install, no uv sync, no Electron
    assert KEY not in result.stdout + result.stderr


@pytest.mark.parametrize("mode, dotenv, shell", [
    ("live", f"OPENAI_API_KEY={KEY}\n", {}),
    ("live", f"export OPENAI_API_KEY='{KEY}'\n", {}),
    ("live", "", {"OPENAI_API_KEY": KEY}),
    ("live", "REPLAY=replay\n", {}),  # strict replay makes no OpenAI call
    ("real", f'OPENAI_API_KEY="{KEY}"  # comment\n', {}),
])
def test_live_starts_the_real_agent_only_when_asked(sandbox, mode, dotenv, shell):
    sandbox.write_env(dotenv)
    result = sandbox.run(mode, env=shell)
    assert result.returncode == 0, result.stderr
    calls = sandbox.calls()
    assert "uv sync --project agent --quiet" in calls[1]
    expected_key = "present" if "OPENAI_API_KEY" in shell else ""
    assert launched(sandbox).endswith(f"| MODE=live CMD= SOURCE=webgazer DEMO=1 KEY={expected_key}")
    assert "LIVE: the real agent calls OpenAI and clicks and types on this Mac." in result.stdout
    assert KEY not in result.stdout + result.stderr + sandbox.log.read_text().replace(f"KEY={expected_key}", "")


def test_live_settings_precedence_and_banner(sandbox):
    # .env DEMO_MODE/GAZE_SOURCE lose to the launcher's defaults; the shell wins over both.
    sandbox.write_env(f"OPENAI_API_KEY={KEY}\nDEMO_MODE=0\nGAZE_SOURCE=mouse\nREPLAY=record\n")
    result = sandbox.run("live")
    assert "| MODE=live CMD= SOURCE=webgazer DEMO=1 " in launched(sandbox)
    assert "DEMO_MODE=1  GAZE_SOURCE=webgazer  REPLAY=record" in result.stdout
    sandbox.log.unlink()
    result = sandbox.run("live", env={"DEMO_MODE": "0", "GAZE_SOURCE": "mouse", "REPLAY": "some-secret-ish-value"})
    assert "| MODE=live CMD= SOURCE=mouse DEMO=0 " in launched(sandbox)
    assert "REPLAY=invalid" in result.stdout and "some-secret-ish-value" not in result.stdout


def test_live_selects_the_saved_private_profile_without_a_form(sandbox):
    sandbox.write_env(f"OPENAI_API_KEY={KEY}\n")
    config = sandbox.tmp / "GazeDemoPrivate" / "demo.json"  # HOME is the sandbox
    config.parent.mkdir()
    config.write_text("{}")
    sandbox.run("live")
    assert "setup_demo.py" not in sandbox.log.read_text()  # not a TTY, and the file exists


def test_live_replaces_a_custom_agent_command_with_the_real_agent(sandbox):
    sandbox.write_env(f"OPENAI_API_KEY={KEY}\n")
    result = sandbox.run("live", env={"GAZE_AGENT_CMD": "uv run scripts/fake_agent.py"})
    assert result.returncode == 0, result.stderr
    assert "| MODE=live CMD= " in launched(sandbox)


@pytest.mark.parametrize("args, code", [(["bogus"], 2), (["LIVE"], 2), (["help"], 0)])
def test_unknown_mode_starts_nothing(sandbox, args, code):
    result = sandbox.run(*args)
    assert result.returncode == code
    assert "Usage: scripts/start.sh [live|preview|browser|stop]" in result.stderr
    assert sandbox.calls() == []


def test_dev_sh_is_the_preview_unless_a_custom_command_is_given(sandbox):
    result = sandbox.run(script="dev.sh")
    assert "| MODE=preview CMD=<unset> SOURCE=mouse " in launched(sandbox)
    assert "PREVIEW: fake agent" in result.stdout
    sandbox.log.unlink()
    result = sandbox.run("--flag", script="dev.sh", env={"GAZE_AGENT_CMD": "uv run scripts/fake_agent.py --delay 2"})
    assert launched(sandbox).startswith("pnpm dev --flag | MODE=custom CMD=uv run scripts/fake_agent.py --delay 2 ")
    assert "CUSTOM agent from GAZE_AGENT_CMD" in result.stdout


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_browser_preview_runs_only_the_fake_agent_and_stops_it(sandbox):
    sandbox.write_env(f"OPENAI_API_KEY={KEY}\n")
    process = subprocess.Popen(["/bin/sh", str(sandbox.root / "scripts/start.sh"), "browser"], cwd=sandbox.tmp,
                               env=sandbox.environ(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert _wait_for(lambda: sum(line.startswith(("uv run", "vite")) for line in sandbox.calls()) == 2)
        time.sleep(0.3)
        process.send_signal(signal.SIGTERM)  # what closing the terminal or Ctrl+C does
        stdout, _ = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
    calls = sandbox.calls()
    assert process.returncode == 130
    agent = next(line for line in calls if line.startswith("uv run"))
    assert agent.startswith("uv run scripts/fake_agent.py --delay 0.6 --quiet | TOKEN=dev-token PORT=")
    assert not any("gaze_agent.server" in line or line.startswith("pnpm dev") for line in calls)
    assert "uv got TERM" in calls and "vite got TERM" in calls
    # Starting the preview clears only old dev servers, never a live overlay or agent.
    assert [line for line in calls if line.startswith("pgrep")] == ["pgrep -f vite/bin/vite.js|scripts/fake_agent.py"]
    assert "Browser PREVIEW: fake agent" in stdout and "Overlay:  http://127.0.0.1:" in stdout


def test_stop_ends_leftovers_from_this_checkout_only(sandbox):
    # Stand-ins for leftovers: one quits on SIGINT, one only on SIGTERM; one runs elsewhere.
    polite = "trap 'echo \"polite got INT\" >> \"$LAUNCH_LOG\"; exit 0' INT; while :; do sleep 0.05; done"
    stubborn = ("trap '' INT; trap 'echo \"stubborn got TERM\" >> \"$LAUNCH_LOG\"; exit 0' TERM; "
                "while :; do sleep 0.05; done")
    outside = sandbox.tmp / "elsewhere"
    outside.mkdir()
    env = sandbox.environ()
    procs = [subprocess.Popen(["/bin/sh", "-c", body], cwd=cwd, env=env)
             for body, cwd in ((polite, sandbox.root), (stubborn, sandbox.root / "scripts"), ("sleep 30", outside))]
    try:
        time.sleep(0.3)
        result = sandbox.run("stop", env={"FAKE_PGREP_PIDS": " ".join(str(p.pid) for p in procs)}, timeout=30)
        assert result.returncode == 0, result.stderr
        assert procs[0].wait(timeout=5) == 0 and procs[1].wait(timeout=5) == 0
        assert procs[2].poll() is None  # another checkout's process is never touched
        calls = sandbox.calls()
        assert "polite got INT" in calls and "stubborn got TERM" in calls
        pattern = next(line for line in calls if line.startswith("pgrep"))
        for name in ("vite/bin/vite.js", "scripts/fake_agent.py", "electron-vite", r"Electron\.app", r"gaze_agent\.server"):
            assert name in pattern
        assert not any(line.startswith(("pnpm", "uv", "node")) for line in calls)
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait()


def test_no_launcher_reads_or_prints_the_real_env_file(sandbox):
    # The scripts resolve .env from their own checkout: this run sees only the sandbox (none here).
    assert not (sandbox.root / ".env").exists()
    result = sandbox.run("live")
    assert result.returncode == 1 and str(sandbox.root) in result.stderr
    assert str(ROOT) not in result.stdout + result.stderr
    assert os.environ.get("OPENAI_API_KEY") is None  # the suite-wide guard removed any real key
