#!/bin/bash
# Remote installer for tt time tracker
# Usage: curl -fsSL https://raw.githubusercontent.com/cs-jason/time-tracker/main/install-remote.sh | bash

set -e

REPO="cs-jason/time-tracker"
INSTALL_DIR="$HOME/.tt-app"
BIN_DIR="$HOME/.local/bin"

echo "Installing tt time tracker..."

# Create directories
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

# Download latest release (or clone repo)
if command -v git &> /dev/null; then
    echo "Cloning repository..."
    git clone --depth 1 "https://github.com/$REPO.git" "$INSTALL_DIR" 2>/dev/null || \
        (cd "$INSTALL_DIR" && git pull)
else
    echo "Downloading..."
    curl -fsSL "https://github.com/$REPO/archive/main.tar.gz" | tar -xz -C "$INSTALL_DIR" --strip-components=1
fi

# Make executable and create symlink
chmod +x "$INSTALL_DIR/tt"
ln -sf "$INSTALL_DIR/tt" "$BIN_DIR/tt"

# Check PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo ""
    echo "Add to your ~/.zshrc or ~/.bashrc:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    echo "Then run: source ~/.zshrc"
fi

echo ""
echo "✓ Installed tt to $BIN_DIR/tt"
echo ""
echo "Get started:"
echo "  tt help          Show commands"
echo "  tt start         Start tracking"
echo "  tt projects add  Add a project"
