"""Install or remove the weekly local refresh for the logged-in macOS user."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from estimate import ROOT

LABEL = "org.clusterinfo.patients-helped"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "status", "remove"])
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("The built-in scheduler uses macOS launchd. Elsewhere schedule estimate.py directly.")
    domain = f"gui/{os.getuid()}"
    service = domain + "/" + LABEL
    path = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    ctl = "/bin/launchctl"
    if args.action == "status":
        sys.exit(subprocess.run([ctl, "print", service]).returncode)
    loaded = subprocess.run([ctl, "print", service], capture_output=True).returncode == 0
    if args.action == "remove":
        if loaded:
            subprocess.run([ctl, "bootout", service], check=True)
        path.unlink(missing_ok=True)
        return
    logs = ROOT / "reports"
    logs.mkdir(parents=True, exist_ok=True)
    # The project's key is supplied by the user's interactive zsh environment.
    # The generated plist and the repository never contain its value.
    config = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/zsh", "-ic", 'exec "$@"', LABEL, sys.executable, str(ROOT / "estimate.py")],
        "WorkingDirectory": str(ROOT), "RunAtLoad": True,
        "StartCalendarInterval": {"Weekday": 1, "Hour": 7, "Minute": 15},
        "StandardOutPath": str(logs / "refresh.log"), "StandardErrorPath": str(logs / "refresh.err"),
    }
    contents = plistlib.dumps(config)
    if path.exists() and path.read_bytes() == contents and loaded:
        print(f"{LABEL} is already installed.")
        return
    if loaded:
        subprocess.run([ctl, "bootout", service], check=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    subprocess.run([ctl, "bootstrap", domain, str(path)], check=True)
    print(f"Registered {LABEL} for Mondays at 07:15 local time and requested its first run.")


if __name__ == "__main__":
    main()
