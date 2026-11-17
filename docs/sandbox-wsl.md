# Getting a Linux sandbox with WSL

The sandbox needs Docker running **Linux** containers. On Windows the free way is WSL2 (a small Linux inside
Windows). `python -m skillforge sandbox-status` looks for native Docker with Linux containers first, then for
Docker inside WSL, and says exactly what it found.

## State of the development machine (verified 2026-11-17)

**The sandbox works.** `sandbox-status` reports `AVAILABLE: Docker inside WSL is running Linux containers`, and
the real-container tests in `tests/test_sandbox_live.py` pass (7 of 7). They prove, on a real container, that:
output comes back; the network is cut off; the skill folder and the root file system cannot be written (only
`/tmp`); the script runs as an unprivileged user; a runaway script is killed at the time limit; a memory hog
is stopped; and a fork bomb hits the process limit. As a control, the same network probe **connects** without
`--network none` and is **blocked** with it, so the test is not passing by accident.

How it got there:

- WSL 3.0.5 was already installed, but with no Linux distribution (`wsl.exe` printed "has no installed
  distributions"). Turning WSL on is the one step that needs administrator rights, so it was not done here.
- `wsl --install -d Ubuntu` could not work: this network resets connections to `raw.githubusercontent.com`,
  where WSL fetches its distribution list. Ubuntu's own servers and Docker's registry are reachable.
- So `scripts/install-wsl-ubuntu.py` downloaded the official Ubuntu 24.04.5 WSL image from
  `releases.ubuntu.com`, verified its SHA-256, and imported it as the distribution `skillforge-ubuntu` in
  `C:\dev\wsl` (outside OneDrive, because the virtual disk is large). No administrator rights were needed.
- `scripts/setup-wsl-docker.sh` then installed Docker Engine (`docker.io` 29.1.3) inside it and pulled
  `python:3.13-slim` and `node:22-slim`.

To remove all of it later: `wsl --unregister skillforge-ubuntu`, then delete `C:\dev\wsl`.

## The steps, for any machine

1. **Turn WSL on (needs administrator rights, once).** In PowerShell **as administrator**:
   ```powershell
   wsl --install --no-distribution
   ```
   Restart if it asks. If IT blocks this, WSL is not allowed on the machine: use one of the options at the end.
2. **Get an Ubuntu distribution.** Try the normal way first: `wsl --install -d Ubuntu`. If that fails on a
   restrictive network, use the script (no administrator rights needed):
   ```powershell
   python scripts/install-wsl-ubuntu.py --dry-run    # shows the image and checksum it would use
   python scripts/install-wsl-ubuntu.py
   ```
3. **Install Docker inside it** (installs Docker Engine, makes sure it starts by itself, pulls the two images):
   ```powershell
   wsl -d skillforge-ubuntu --exec bash "scripts/setup-wsl-docker.sh"
   ```
   For a distribution you created with a normal user, run it from inside Ubuntu instead; it asks for the Linux
   password once.
4. **Check it.**
   ```powershell
   cd backend
   python -m skillforge sandbox-status           # AVAILABLE: Docker inside WSL is running Linux containers
   python -m pytest tests/test_sandbox_live.py   # real containers: proves the locks hold
   ```

If you have several distributions, set `SKILLFORGE_WSL_DISTRO` to the one with Docker.

## What it does not prove

The locks are Docker's, applied by our command line and checked by the live tests above. That is strong, not
absolute: a container shares the Linux kernel of the WSL virtual machine, and kernel bugs exist. The sandbox is
one layer; the static validators ([validate.md](validate.md)) and a person reading the skill are the others.

## If WSL is not allowed

| Option | Note |
|---|---|
| A Linux machine in the cloud (for example a GitHub Codespace) | Needs no change to your laptop. The sandbox runs there. |
| Docker Desktop | Needs a paid license at larger companies, and WSL2 as well. |
| Windows containers | Works today but the locks are weaker, so the sandbox refuses them. |
