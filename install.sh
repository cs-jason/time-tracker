#!/bin/bash
# Install tt time tracker

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TT_PATH="$SCRIPT_DIR/tt"

# Make tt executable
chmod +x "$TT_PATH"

# Prefer ~/.local/bin, fall back to /usr/local/bin
if [[ -d "$HOME/.local/bin" ]] || mkdir -p "$HOME/.local/bin" 2>/dev/null; then
    INSTALL_DIR="$HOME/.local/bin"
    ln -sf "$TT_PATH" "$INSTALL_DIR/tt"
    echo "✓ Installed tt to $INSTALL_DIR/tt"

    # Check if ~/.local/bin is in PATH
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        echo ""
        echo "Add to your shell config (~/.zshrc or ~/.bashrc):"
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
        echo ""
        echo "Then restart your terminal or run: source ~/.zshrc"
    fi
else
    echo "Installing to /usr/local/bin (requires sudo)..."
    sudo ln -sf "$TT_PATH" /usr/local/bin/tt
    echo "✓ Installed tt to /usr/local/bin/tt"
fi

echo ""
echo "Run 'tt help' to get started."
