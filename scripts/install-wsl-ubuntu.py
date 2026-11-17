"""Install an Ubuntu distribution for WSL when `wsl --install -d Ubuntu` does not work.

Typical reason: a network that blocks the list WSL downloads (raw.githubusercontent.com) while allowing Ubuntu's
own servers. WSL itself must already be installed (that is the one step that needs administrator rights:
`wsl --install --no-distribution` in an elevated PowerShell). Importing a distribution needs no administrator
rights.

What it does: reads Ubuntu's published checksum list, picks the newest 24.04 WSL image, downloads it from
releases.ubuntu.com, verifies the SHA-256, and imports it as a WSL 2 distribution outside OneDrive.
The checksum comes from the same Ubuntu server over HTTPS, so it protects against a damaged download, not against
a compromised server.

    python scripts/install-wsl-ubuntu.py --dry-run       # show what it would do
    python scripts/install-wsl-ubuntu.py                 # do it
Afterwards run scripts/setup-wsl-docker.sh inside the distribution (see docs/sandbox-wsl.md).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = "https://releases.ubuntu.com/noble/"
LINE = re.compile(r"^([0-9a-f]{64}) \*(ubuntu-24\.04\.(\d+)-wsl-amd64\.wsl)$", re.M)


def wsl(*args: str, timeout: int = 600) -> tuple[int, str]:
    p = subprocess.run(["wsl.exe", *args], capture_output=True, timeout=timeout)
    raw = p.stdout + p.stderr
    text = raw.decode("utf-16-le", "replace") if b"\x00" in raw else raw.decode("utf-8", "replace")
    return p.returncode, text.replace("\x00", "").strip()


def newest_image() -> tuple[str, str]:
    """(file name, sha256) of the newest Ubuntu 24.04 WSL image in Ubuntu's published list."""
    sums = urllib.request.urlopen(BASE + "SHA256SUMS", timeout=30).read().decode()
    found = [(int(m.group(3)), m.group(2), m.group(1)) for m in LINE.finditer(sums)]
    if not found:
        sys.exit("Could not find a WSL image in Ubuntu's checksum list.")
    _, name, digest = max(found)
    return name, digest


def download(url: str, dest: Path, expected: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
        while chunk := r.read(1024 * 1024):
            f.write(chunk)
            sha.update(chunk)
    if sha.hexdigest() != expected:
        dest.unlink(missing_ok=True)
        sys.exit("The checksum does not match, so the file was deleted. Nothing was installed.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", default="skillforge-ubuntu", help="name of the WSL distribution to create")
    ap.add_argument("--dir", default=r"C:\dev\wsl", help="where to keep the image and the virtual disk (not OneDrive)")
    ap.add_argument("--no-default", action="store_true", help="do not make it the default WSL distribution")
    ap.add_argument("--dry-run", action="store_true", help="only show what would be done")
    args = ap.parse_args()

    code, status = wsl("--status")
    if code != 0 or "not installed" in status.lower():
        sys.exit("WSL itself is not installed. In PowerShell as administrator run: wsl --install --no-distribution")
    _, listed = wsl("-l", "-q")
    if args.name in [x.strip() for x in listed.splitlines()]:
        print(f"A distribution named '{args.name}' already exists. Nothing to do.")
        return 0

    name, digest = newest_image()
    root = Path(args.dir)
    print(f"Image : {BASE}{name}\nSHA-256: {digest}\nDisk  : {root / args.name}")
    if args.dry_run:
        print("Dry run: nothing downloaded or installed.")
        return 0

    image = root / "downloads" / name
    print("Downloading (about 400 MB)...")
    download(BASE + name, image, digest)
    print("Checksum OK. Importing as WSL 2...")
    code, out = wsl("--import", args.name, str(root / args.name), str(image), "--version", "2")
    print(out)
    if code != 0:
        return code
    if not args.no_default:
        print(wsl("--set-default", args.name)[1])
    print(f"Done. Next, run scripts/setup-wsl-docker.sh inside it: wsl -d {args.name} --exec bash scripts/setup-wsl-docker.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
