#!/bin/sh
# AutoCV installer for macOS and Linux.
#
#   curl -LsSf https://raw.githubusercontent.com/atenreiro/autocv/main/install.sh | sh
#
# What it does, and nothing else:
#   1. installs uv (Astral's Python tool installer) into ~/.local/bin, unless you already have it;
#   2. installs or upgrades AutoCV from PyPI (`autocv-app`) in its own environment, on a Python that uv
#      downloads and manages itself: your system's Python (and Homebrew's) is never used or changed;
#   3. makes sure the `autocv` command is on your PATH, in this terminal and new ones;
#   4. starts AutoCV, which opens in your browser.
# No sudo, nothing outside your home folder. Run it again to update.
#
# Options (after `sh -s --` when piping, e.g. `curl … | sh -s -- --no-launch`):
#   --no-launch   install or update only; don't start AutoCV
#   --uninstall   remove AutoCV (your profile and applications are kept)
# Environment: AUTOCV_PACKAGE overrides what gets installed (default: autocv-app; e.g. autocv-app==0.2.0).

set -eu

# Everything runs from main(), called on the last line: when this script is piped into sh, nothing
# happens until the whole file has arrived.

# The Python AutoCV runs on: one CI tests, so every dependency has a ready-made wheel for it.
PYTHON_VERSION=3.13

say() { printf '%s\n' "$*"; }
fail() { printf 'AutoCV installer: %s\n' "$*" >&2; exit 1; }

find_uv() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
  for candidate in "${XDG_BIN_HOME:-$HOME/.local/bin}/uv" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$candidate" ]; then say "$candidate"; return; fi
  done
}

install_uv() {
  say "Installing uv (https://docs.astral.sh/uv/) into ~/.local/bin…"
  tmp=$(mktemp)
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh -o "$tmp" </dev/null || { rm -f "$tmp"; fail "couldn't download uv's installer from astral.sh. Check your internet connection and try again."; }
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$tmp" https://astral.sh/uv/install.sh </dev/null || { rm -f "$tmp"; fail "couldn't download uv's installer from astral.sh. Check your internet connection and try again."; }
  else
    rm -f "$tmp"
    fail "needs curl or wget to download uv. Install one of them, or install uv yourself (https://docs.astral.sh/uv/getting-started/installation/), then run this again."
  fi
  sh "$tmp" </dev/null >/dev/null || { rm -f "$tmp"; fail "uv's installer failed (see above)."; }
  rm -f "$tmp"
}

# An update or uninstall under a running AutoCV would swap its files out from under it.
refuse_if_running() {
  command -v pgrep >/dev/null 2>&1 || return 0
  if pgrep -f "$1/autocv-app/" >/dev/null 2>&1; then
    fail "AutoCV is running. Stop it first (press Ctrl+C in the terminal window where it runs), then run this again."
  fi
}

main() {
  launch=1
  uninstall=0
  for arg in "$@"; do
    case "$arg" in
      --no-launch) launch=0 ;;
      --uninstall) uninstall=1 ;;
      -h|--help) say "Usage: install.sh [--no-launch] [--uninstall]"; return 0 ;;
      *) fail "unknown option: $arg (use --no-launch or --uninstall)" ;;
    esac
  done

  case "$(uname -s)" in
    Darwin|Linux) ;;
    *) fail "this script is for macOS and Linux. On Windows, run in PowerShell: irm https://raw.githubusercontent.com/atenreiro/autocv/main/install.ps1 | iex" ;;
  esac
  if [ "$(id -u)" = 0 ]; then
    fail "don't run this with sudo or as root: AutoCV installs into your own user folder. Run it again without sudo."
  fi

  # Use the system's certificate store (works behind company proxies that inspect HTTPS), and only
  # uv-managed Pythons (probing macOS's /usr/bin/python3 stub would pop up an Xcode tools prompt, and a
  # Homebrew Python upgrade would break AutoCV's environment).
  UV_SYSTEM_CERTS=${UV_SYSTEM_CERTS:-1}; UV_NATIVE_TLS=${UV_NATIVE_TLS:-1}; UV_MANAGED_PYTHON=1
  export UV_SYSTEM_CERTS UV_NATIVE_TLS UV_MANAGED_PYTHON

  uv=$(find_uv)
  if [ "$uninstall" = 1 ]; then
    [ -n "$uv" ] || fail "uv isn't installed, so AutoCV isn't either."
    refuse_if_running "$("$uv" tool dir)"
    "$uv" tool uninstall autocv-app </dev/null
    say ""
    say "AutoCV is removed. Your profile and applications are still in your data folder:"
    if [ "$(uname -s)" = Darwin ]; then say "  ~/Library/Application Support/AutoCV"; else say "  ${XDG_DATA_HOME:-~/.local/share}/AutoCV"; fi
    say "Delete that folder yourself if you want them gone. uv stays installed."
    return 0
  fi

  if [ -z "$uv" ]; then
    install_uv
    uv=$(find_uv)
    [ -n "$uv" ] || fail "uv was installed but can't be found. Open a new terminal and run this again."
  else
    say "Using uv at $uv"
  fi

  bindir=$("$uv" tool dir --bin 2>/dev/null) || fail "your uv ($("$uv" --version)) is too old. Update it (\`uv self update\`, or \`brew upgrade uv\` if you installed it with Homebrew), then run this again."
  refuse_if_running "$("$uv" tool dir)"
  case ":$PATH:" in
    *":$bindir:"*) ;;
    *) "$uv" tool update-shell </dev/null >/dev/null 2>&1 || true  # new terminals find `autocv`
       PATH="$bindir:$PATH"; export PATH ;;                        # and so does this one
  esac

  package=${AUTOCV_PACKAGE:-autocv-app}
  say "Installing AutoCV ($package)…"
  "$uv" tool install --upgrade --python "$PYTHON_VERSION" "$package" </dev/null
  autocv="$bindir/autocv"
  [ -x "$autocv" ] || fail "AutoCV was installed but $autocv is missing."

  say ""
  say "$("$autocv" --version) is installed."
  say "  Start it any time with:  autocv serve   (in a new terminal)"
  say "  Update with:             the same command you just ran"
  say "  Check your setup with:   autocv doctor"
  if [ "$launch" = 1 ]; then
    say ""
    say "Starting AutoCV. It opens in your browser; press Ctrl+C here to stop it."
    exec "$autocv" serve </dev/null
  fi
}

main "$@"
