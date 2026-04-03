#!/usr/bin/env bash
#
# AISE Build Script — generates self-extracting installer: aise-{VERSION}.sh
#
# Usage:
#   ./packaging/build.sh [--version X.Y.Z] [--output DIR]
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Defaults
VERSION=""
OUTPUT_DIR="$PROJECT_ROOT/dist"

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version|-v) VERSION="$2"; shift 2 ;;
        --output|-o)  OUTPUT_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--version X.Y.Z] [--output DIR]"
            echo ""
            echo "Options:"
            echo "  --version, -v   Version string (default: read from pyproject.toml)"
            echo "  --output, -o    Output directory (default: dist/)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Auto-detect version from pyproject.toml
if [[ -z "$VERSION" ]]; then
    VERSION=$(grep '^version' "$PROJECT_ROOT/pyproject.toml" | head -1 | sed 's/.*"\(.*\)".*/\1/')
    if [[ -z "$VERSION" ]]; then
        echo "ERROR: Cannot detect version. Use --version X.Y.Z"
        exit 1
    fi
fi

echo "=========================================="
echo "  AISE Installer Builder v${VERSION}"
echo "=========================================="

# Create staging area
STAGE_DIR=$(mktemp -d)
trap "rm -rf '$STAGE_DIR'" EXIT

PAYLOAD_DIR="$STAGE_DIR/aise-${VERSION}"
mkdir -p "$PAYLOAD_DIR"

# Copy source
echo "[1/5] Copying source files..."
cp -r "$PROJECT_ROOT/src" "$PAYLOAD_DIR/"
cp -r "$PROJECT_ROOT/config" "$PAYLOAD_DIR/"
cp "$PROJECT_ROOT/pyproject.toml" "$PAYLOAD_DIR/"
cp "$PROJECT_ROOT/README.md" "$PAYLOAD_DIR/" 2>/dev/null || true
cp "$PROJECT_ROOT/LICENSE" "$PAYLOAD_DIR/" 2>/dev/null || true

# Copy packaging runtime
echo "[2/5] Embedding runtime installer..."
cp "$SCRIPT_DIR/installer_runtime.sh" "$PAYLOAD_DIR/.installer_runtime.sh"
chmod +x "$PAYLOAD_DIR/.installer_runtime.sh"

# Write version marker
echo "$VERSION" > "$PAYLOAD_DIR/.aise_version"

# Build metadata
echo "[3/5] Writing build metadata..."
cat > "$PAYLOAD_DIR/.build_meta.json" <<METAEOF
{
  "version": "$VERSION",
  "build_time": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "build_host": "$(hostname)",
  "git_commit": "$(cd "$PROJECT_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo 'unknown')",
  "python_requires": ">=3.11"
}
METAEOF

# Create tarball
echo "[4/5] Creating compressed archive..."
TARBALL="$STAGE_DIR/payload.tar.gz"
(cd "$STAGE_DIR" && tar czf "$TARBALL" "aise-${VERSION}")

# Compose self-extracting installer
echo "[5/5] Building self-extracting installer..."
mkdir -p "$OUTPUT_DIR"
INSTALLER="$OUTPUT_DIR/aise-${VERSION}.sh"

cat > "$INSTALLER" <<'HEADER_EOF'
#!/usr/bin/env bash
#
# AISE Self-Extracting Installer
# Generated — do not edit manually.
#
# Usage:
#   ./aise-VERSION.sh install [OPTIONS]
#   ./aise-VERSION.sh upgrade [OPTIONS]
#   ./aise-VERSION.sh uninstall [OPTIONS]
#   ./aise-VERSION.sh info
#
set -euo pipefail

AISE_INSTALLER_VERSION="__AISE_VERSION__"

# --- Self-extraction ---
ARCHIVE_MARKER="__ARCHIVE_BELOW__"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

_extract_payload() {
    local target="$1"
    local line_num
    line_num=$(grep -an "^${ARCHIVE_MARKER}$" "$SCRIPT_PATH" | tail -1 | cut -d: -f1)
    if [[ -z "$line_num" ]]; then
        echo "ERROR: Archive marker not found. Installer may be corrupt."
        exit 1
    fi
    tail -n +"$((line_num + 1))" "$SCRIPT_PATH" | tar xzf - -C "$target"
}

# --- Dispatch to embedded runtime ---
_run() {
    local tmp
    tmp=$(mktemp -d)
    trap "rm -rf '$tmp'" EXIT
    _extract_payload "$tmp"
    local runtime="$tmp/aise-${AISE_INSTALLER_VERSION}/.installer_runtime.sh"
    if [[ ! -f "$runtime" ]]; then
        echo "ERROR: Installer runtime not found in archive."
        exit 1
    fi
    export AISE_EXTRACT_DIR="$tmp/aise-${AISE_INSTALLER_VERSION}"
    export AISE_INSTALLER_VERSION
    bash "$runtime" "$@"
}

if [[ $# -eq 0 ]]; then
    echo "AISE Installer v${AISE_INSTALLER_VERSION}"
    echo ""
    echo "Usage:"
    echo "  $0 install  [OPTIONS]   Install AISE"
    echo "  $0 upgrade  [OPTIONS]   Upgrade existing installation"
    echo "  $0 uninstall [OPTIONS]  Uninstall AISE"
    echo "  $0 info                 Show package info"
    echo ""
    echo "Run '$0 install --help' for install options."
    exit 0
fi

_run "$@"
exit $?
HEADER_EOF

# Patch version
sed -i "s/__AISE_VERSION__/${VERSION}/g" "$INSTALLER"

# Append archive marker and payload
echo "" >> "$INSTALLER"
echo "__ARCHIVE_BELOW__" >> "$INSTALLER"
cat "$TARBALL" >> "$INSTALLER"

chmod +x "$INSTALLER"

INSTALLER_SIZE=$(du -h "$INSTALLER" | cut -f1)
echo ""
echo "=========================================="
echo "  ✅ Built: $INSTALLER"
echo "     Size:  $INSTALLER_SIZE"
echo "     Version: $VERSION"
echo "=========================================="
