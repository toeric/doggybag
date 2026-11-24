#!/bin/sh
# Install waddlebag into a folder of its own and put the `waddlebag` command on your PATH.
#
#   curl -fsSL https://raw.githubusercontent.com/toeric/waddlebag/main/install.sh | sh
#
# It makes ~/.waddlebag/venv with uv or a Python 3.11+ it finds, installs waddlebag there, links the command into
# ~/.local/bin, asks before adding that folder to your shell's startup file, and then runs `waddlebag setup`.
# Run it again to update. Nothing is installed outside those two folders, except the line in your startup file.
#
# For testing: WADDLEBAG_SOURCE (what pip installs), WADDLEBAG_HOME, WADDLEBAG_BIN, WADDLEBAG_NO_SETUP=1.
set -eu

SOURCE="${WADDLEBAG_SOURCE:-git+https://github.com/toeric/waddlebag}"
HOME_DIR="${WADDLEBAG_HOME:-$HOME/.waddlebag}"
VENV="$HOME_DIR/venv"
BIN="${WADDLEBAG_BIN:-$HOME/.local/bin}"

say() { printf '%s\n' "$*"; }

# 1-2. Its own folder, so it never fights with your other Python packages (and pip doesn't refuse, PEP 668).
# With uv, it brings a Python of its own when needed. Without it, try each Python 3.11+ found: some installs
# are broken (a Homebrew Python whose pyexpat doesn't match macOS can't run pip), so move on to the next one.
mkdir -p "$HOME_DIR"
installed=""
if command -v uv >/dev/null 2>&1; then
    say "Using uv"
    if uv venv --quiet --allow-existing --python ">=3.11" "$VENV" &&
        uv pip install --quiet --python "$VENV/bin/python" --upgrade "$SOURCE"; then
        installed=uv
    else
        rm -rf "$VENV"
    fi
fi
if [ -z "$installed" ]; then
    tried=""
    for candidate in python3.14 python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
        PY="$(command -v "$candidate" 2>/dev/null)" || continue
        case " $tried " in *" $PY "*) continue ;; esac
        tried="$tried $PY"
        "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null || continue
        say "Trying $("$PY" --version 2>&1) at $PY"
        rm -rf "$VENV"
        if "$PY" -m venv "$VENV" >/dev/null 2>&1 &&
            PIP_DISABLE_PIP_VERSION_CHECK=1 "$VENV/bin/python" -m pip install --quiet --upgrade "$SOURCE"; then
            installed="$PY"
            break
        fi
        say "  that one can't make a working venv, trying the next"
    done
fi
if [ -z "$installed" ]; then
    rm -rf "$VENV"
    say ""
    say "I couldn't install waddlebag: it needs a working Python 3.11 or newer."
    say "macOS comes with 3.9. The easiest fix is uv, which brings its own Python:"
    say "  brew install uv     (or: curl -LsSf https://astral.sh/uv/install.sh | sh)"
    say "then run this again. Or install Python from https://www.python.org/downloads/"
    exit 1
fi
mkdir -p "$BIN"
ln -sf "$VENV/bin/waddlebag" "$BIN/waddlebag"
say "Installed waddlebag in $VENV"

# 3. The command on PATH. Ask before touching the startup file; with nobody to answer, only say what to add.
case "$(basename "${SHELL:-sh}")" in
    zsh) RC="$HOME/.zshrc" ;;
    bash) RC="$HOME/.bash_profile" ;;
    *) RC="$HOME/.profile" ;;
esac
SHOWN_BIN="$(printf '%s' "$BIN" | sed "s|^$HOME|\$HOME|")"
LINE="export PATH=\"$SHOWN_BIN:\$PATH\""
case ":$PATH:" in
    *":$BIN:"*) ;;
    *)
        answer=n
        # curl | sh gives the script's stdin to the pipe, so ask on the terminal itself, if there is one
        if (printf 'Add %s to your PATH in %s? [Y/n] ' "$BIN" "$RC" >/dev/tty) 2>/dev/null; then
            if answer="$( (read -r reply </dev/tty && printf '%s' "${reply:-y}") 2>/dev/null)"; then
                :
            else
                answer=n
            fi
        fi
        case "$answer" in
            y* | Y*)
                printf '\n# added by the waddlebag installer\n%s\n' "$LINE" >>"$RC"
                say "Added it to $RC. Open a new terminal, or run: source $RC"
                ;;
            *)
                say "To use waddlebag, add this line to $RC:"
                say "  $LINE"
                say "then run: source $RC"
                ;;
        esac
        ;;
esac

# 4. The rest is setup's job: check Claude Code, make the folders, start the schedule.
if [ "${WADDLEBAG_NO_SETUP:-}" != "1" ]; then
    say ""
    PATH="$BIN:$PATH" "$VENV/bin/waddlebag" setup
fi
