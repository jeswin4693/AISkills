#!/usr/bin/env bash
# Run this INSIDE Ubuntu on WSL. It installs Docker Engine there and pre-pulls the images SkillForge AI uses,
# so that `python -m skillforge sandbox-status` can report a Linux sandbox. It asks for your Linux password once.
set -euo pipefail

if ! grep -qi microsoft /proc/version 2>/dev/null; then
  echo "This script is meant for Ubuntu running inside WSL. Nothing was changed." >&2
  exit 1
fi

# Works as root (an imported distribution) or as a normal user with sudo.
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

echo "==> Installing Docker Engine (docker.io from Ubuntu's own repositories)"
$SUDO apt-get update
$SUDO apt-get install -y docker.io

if [ "$(id -u)" -ne 0 ]; then
  echo "==> Letting your user run docker without sudo"
  $SUDO usermod -aG docker "$USER"
fi

# Docker has to start by itself whenever WSL starts. That needs systemd.
if [ "$(ps -p 1 -o comm= | tr -d ' ')" != "systemd" ]; then
  echo "==> Turning on systemd for this distribution (takes effect after a WSL restart)"
  if ! grep -q '^systemd=true' /etc/wsl.conf 2>/dev/null; then
    printf '[boot]\nsystemd=true\n' | $SUDO tee -a /etc/wsl.conf >/dev/null
  fi
  NEEDS_RESTART=1
else
  $SUDO systemctl enable --now docker
  NEEDS_RESTART=0
fi

echo "==> Pulling the images (needs internet once; the sandbox itself never uses the network)"
$SUDO service docker start || true
$SUDO docker pull python:3.13-slim
$SUDO docker pull node:22-slim
$SUDO docker version --format 'Docker engine OS: {{.Server.Os}}' || true

echo
echo "Done. Now close this window and, in PowerShell, run:"
echo "    wsl --shutdown"
if [ "$NEEDS_RESTART" = "1" ]; then
  echo "(this restart is required: it turns on systemd, so Docker starts automatically from now on)"
fi
echo "Then check it from the project:"
echo "    cd backend; python -m skillforge sandbox-status"
