#!/usr/bin/env bash
#
# AISE Installer Runtime — dispatched by self-extracting header
#
# Environment (set by header):
#   AISE_EXTRACT_DIR       — extracted payload root
#   AISE_INSTALLER_VERSION — version string
#
set -euo pipefail

VERSION="${AISE_INSTALLER_VERSION:?}"
EXTRACT_DIR="${AISE_EXTRACT_DIR:?}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

_info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ============================================================
# Default configuration
# ============================================================
DEFAULT_INSTALL_DIR="/opt/aise"
DEFAULT_PORT=8000
DEFAULT_HOST="127.0.0.1"
DEFAULT_DATA_DIR=""  # defaults to INSTALL_DIR/data
DEFAULT_LOG_DIR=""   # defaults to INSTALL_DIR/logs
DEFAULT_CONFIG=""    # optional external config file path
DEFAULT_VENV="bundled"  # "bundled" | "system" | path-to-venv
DEFAULT_USER=""      # run as specific user
DEFAULT_WORKERS=1
SYSTEMD_UNIT="aise"
PIDFILE_NAME="aise.pid"

# ============================================================
# Helpers
# ============================================================
_check_python() {
    local py=""
    for candidate in python3.12 python3.11 python3; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
            if [[ -n "$ver" ]]; then
                local major minor
                major=$(echo "$ver" | cut -d. -f1)
                minor=$(echo "$ver" | cut -d. -f2)
                if (( major == 3 && minor >= 11 )); then
                    py="$candidate"
                    break
                fi
            fi
        fi
    done
    if [[ -z "$py" ]]; then
        _error "Python >= 3.11 required but not found."
        _info "Install Python 3.11+: https://www.python.org/downloads/"
        exit 1
    fi
    echo "$py"
}

_resolve_dir() {
    mkdir -p "$1" 2>/dev/null || true
    cd "$1" && pwd
}

_read_installed_version() {
    local install_dir="$1"
    if [[ -f "$install_dir/.aise_version" ]]; then
        cat "$install_dir/.aise_version"
    else
        echo ""
    fi
}

_pid_alive() {
    local pidfile="$1"
    if [[ -f "$pidfile" ]]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi
    return 1
}

_stop_service() {
    local install_dir="$1"
    local pidfile="$install_dir/$PIDFILE_NAME"

    # Try systemd first
    if systemctl is-active --quiet "$SYSTEMD_UNIT" 2>/dev/null; then
        _info "Stopping systemd service ${SYSTEMD_UNIT}..."
        sudo systemctl stop "$SYSTEMD_UNIT" 2>/dev/null || true
        return 0
    fi

    # PID file
    if pid=$(_pid_alive "$pidfile"); then
        _info "Stopping AISE (PID $pid)..."
        kill "$pid" 2>/dev/null || true
        local i=0
        while kill -0 "$pid" 2>/dev/null && (( i < 10 )); do
            sleep 1
            (( i++ ))
        done
        if kill -0 "$pid" 2>/dev/null; then
            _warn "Force killing PID $pid"
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$pidfile"
        return 0
    fi
    return 0
}

_start_service() {
    local install_dir="$1"
    local host="$2"
    local port="$3"
    local workers="$4"
    local run_user="$5"
    local venv_python="$install_dir/venv/bin/python"
    local pidfile="$install_dir/$PIDFILE_NAME"
    local log_dir="$install_dir/logs"

    mkdir -p "$log_dir"

    # If systemd unit exists, use it
    if [[ -f "/etc/systemd/system/${SYSTEMD_UNIT}.service" ]]; then
        _info "Starting via systemd..."
        sudo systemctl daemon-reload
        sudo systemctl start "$SYSTEMD_UNIT"
        sudo systemctl enable "$SYSTEMD_UNIT" 2>/dev/null || true
        _ok "Service started: systemctl status $SYSTEMD_UNIT"
        return 0
    fi

    # Direct launch
    _info "Starting AISE on ${host}:${port}..."
    local cmd="$venv_python -m uvicorn aise.web.app:create_app --factory --host $host --port $port --workers $workers"

    if [[ -n "$run_user" ]] && [[ "$(id -un)" == "root" ]]; then
        nohup sudo -u "$run_user" bash -c "cd '$install_dir' && $cmd" \
            > "$log_dir/aise.log" 2>&1 &
    else
        (cd "$install_dir" && nohup $cmd > "$log_dir/aise.log" 2>&1 &)
    fi

    local bg_pid=$!
    echo "$bg_pid" > "$pidfile"
    sleep 2

    if kill -0 "$bg_pid" 2>/dev/null; then
        _ok "AISE started (PID $bg_pid)"
        _info "Web console: http://${host}:${port}"
        _info "Logs: $log_dir/aise.log"
        _info "PID file: $pidfile"
    else
        _error "Failed to start. Check $log_dir/aise.log"
        exit 1
    fi
}

_generate_systemd_unit() {
    local install_dir="$1"
    local host="$2"
    local port="$3"
    local workers="$4"
    local run_user="$5"
    local unit_file="/etc/systemd/system/${SYSTEMD_UNIT}.service"

    [[ -z "$run_user" ]] && run_user="$(id -un)"

    cat > "$unit_file" <<UNITEOF
[Unit]
Description=AISE Multi-Agent Development Platform
After=network.target

[Service]
Type=simple
User=$run_user
WorkingDirectory=$install_dir
ExecStart=$install_dir/venv/bin/python -m uvicorn aise.web.app:create_app --factory --host $host --port $port --workers $workers
Restart=on-failure
RestartSec=5
StandardOutput=append:$install_dir/logs/aise.log
StandardError=append:$install_dir/logs/aise-error.log
Environment=AISE_HOME=$install_dir

[Install]
WantedBy=multi-user.target
UNITEOF

    _ok "Systemd unit created: $unit_file"
}

_write_env_file() {
    local install_dir="$1"
    local host="$2"
    local port="$3"
    local workers="$4"
    local data_dir="$5"
    local log_dir="$6"
    local config_file="$7"

    cat > "$install_dir/.env" <<ENVEOF
# AISE Environment Configuration
# Generated by installer v${VERSION}
AISE_HOME=${install_dir}
AISE_HOST=${host}
AISE_PORT=${port}
AISE_WORKERS=${workers}
AISE_DATA_DIR=${data_dir}
AISE_LOG_DIR=${log_dir}
AISE_CONFIG=${config_file}
AISE_VERSION=${VERSION}
ENVEOF
}

# ============================================================
# INSTALL
# ============================================================
cmd_install() {
    local install_dir="$DEFAULT_INSTALL_DIR"
    local port=$DEFAULT_PORT
    local host="$DEFAULT_HOST"
    local data_dir="$DEFAULT_DATA_DIR"
    local log_dir="$DEFAULT_LOG_DIR"
    local config_file="$DEFAULT_CONFIG"
    local run_user="$DEFAULT_USER"
    local workers=$DEFAULT_WORKERS
    local no_start=false
    local with_systemd=false
    local force=false
    local with_web=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --prefix|--install-dir) install_dir="$2"; shift 2 ;;
            --port)        port="$2"; shift 2 ;;
            --host)        host="$2"; shift 2 ;;
            --data-dir)    data_dir="$2"; shift 2 ;;
            --log-dir)     log_dir="$2"; shift 2 ;;
            --config)      config_file="$2"; shift 2 ;;
            --user)        run_user="$2"; shift 2 ;;
            --workers)     workers="$2"; shift 2 ;;
            --no-start)    no_start=true; shift ;;
            --systemd)     with_systemd=true; shift ;;
            --with-web)    with_web=true; shift ;;
            --force)       force=true; shift ;;
            -h|--help)
                echo "Usage: aise-${VERSION}.sh install [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --prefix, --install-dir DIR  Installation directory (default: /opt/aise)"
                echo "  --port PORT                  Web server port (default: 8000)"
                echo "  --host HOST                  Web server bind address (default: 127.0.0.1)"
                echo "  --data-dir DIR               Data directory (default: INSTALL_DIR/data)"
                echo "  --log-dir DIR                Log directory (default: INSTALL_DIR/logs)"
                echo "  --config FILE                External config file path"
                echo "  --user USER                  Run service as specified user"
                echo "  --workers N                  Number of web workers (default: 1)"
                echo "  --with-web                   Install web console dependencies"
                echo "  --systemd                    Create systemd service unit"
                echo "  --no-start                   Install without starting the service"
                echo "  --force                      Overwrite existing installation"
                echo ""
                echo "Examples:"
                echo "  ./aise-${VERSION}.sh install"
                echo "  ./aise-${VERSION}.sh install --prefix /home/user/aise --port 9000"
                echo "  ./aise-${VERSION}.sh install --systemd --user aise --host 0.0.0.0"
                exit 0
                ;;
            *) _error "Unknown option: $1"; exit 1 ;;
        esac
    done

    # Resolve directories
    install_dir="$(_resolve_dir "$install_dir")"
    [[ -z "$data_dir" ]] && data_dir="$install_dir/data"
    [[ -z "$log_dir" ]] && log_dir="$install_dir/logs"
    data_dir="$(_resolve_dir "$data_dir")"
    log_dir="$(_resolve_dir "$log_dir")"

    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║     AISE Installer v${VERSION}          ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
    echo ""

    # Check existing installation
    if [[ -f "$install_dir/.aise_version" ]] && [[ "$force" != true ]]; then
        local existing
        existing=$(_read_installed_version "$install_dir")
        _error "AISE v${existing} already installed at $install_dir"
        _info "Use --force to overwrite, or 'upgrade' command instead."
        exit 1
    fi

    # Check Python
    _info "Checking Python..."
    local python_bin
    python_bin=$(_check_python)
    _ok "Found $python_bin ($($python_bin --version 2>&1))"

    # Copy payload
    _info "Installing to $install_dir..."
    cp -r "$EXTRACT_DIR/src" "$install_dir/"
    cp -r "$EXTRACT_DIR/config" "$install_dir/"
    cp "$EXTRACT_DIR/pyproject.toml" "$install_dir/"
    cp "$EXTRACT_DIR/.aise_version" "$install_dir/"
    cp "$EXTRACT_DIR/.build_meta.json" "$install_dir/"
    cp "$EXTRACT_DIR/README.md" "$install_dir/" 2>/dev/null || true
    cp "$EXTRACT_DIR/LICENSE" "$install_dir/" 2>/dev/null || true

    # Create directories
    mkdir -p "$data_dir" "$log_dir" "$install_dir/trace" "$install_dir/projects"

    # Setup config
    if [[ -n "$config_file" ]] && [[ -f "$config_file" ]]; then
        cp "$config_file" "$install_dir/config/global_project_config.json"
        _ok "Using custom config: $config_file"
    elif [[ ! -f "$install_dir/config/global_project_config.json" ]]; then
        cp "$install_dir/config/global_project_config.example.json" \
           "$install_dir/config/global_project_config.json"
        _warn "Default config created. Edit: $install_dir/config/global_project_config.json"
    fi

    # Create virtualenv
    _info "Creating Python virtual environment..."
    "$python_bin" -m venv "$install_dir/venv" 2>/dev/null || {
        _error "Failed to create venv. Install: apt install python3-venv (or equivalent)"
        exit 1
    }

    # Install dependencies
    _info "Installing dependencies (this may take a minute)..."
    local pip="$install_dir/venv/bin/pip"
    "$pip" install --upgrade pip setuptools wheel -q 2>&1 | tail -1

    local extras=""
    if [[ "$with_web" == true ]]; then
        extras="[web]"
    fi
    "$pip" install -e "${install_dir}${extras}" -q 2>&1 | tail -3
    _ok "Dependencies installed"

    # Create wrapper script
    mkdir -p "$install_dir/bin"
    cat > "$install_dir/bin/aise" <<WRAPPER
#!/usr/bin/env bash
# AISE CLI wrapper
export AISE_HOME="${install_dir}"
source "\${AISE_HOME}/.env" 2>/dev/null || true
exec "${install_dir}/venv/bin/aise" "\$@"
WRAPPER
    chmod +x "$install_dir/bin/aise"

    # Symlink to PATH
    if [[ -d /usr/local/bin ]] && [[ -w /usr/local/bin ]]; then
        ln -sf "$install_dir/bin/aise" /usr/local/bin/aise
        _ok "CLI available as: aise"
    elif [[ -d "$HOME/.local/bin" ]]; then
        mkdir -p "$HOME/.local/bin"
        ln -sf "$install_dir/bin/aise" "$HOME/.local/bin/aise"
        _ok "CLI available as: ~/.local/bin/aise"
    fi

    # Write env file
    _write_env_file "$install_dir" "$host" "$port" "$workers" "$data_dir" "$log_dir" "${config_file:-$install_dir/config/global_project_config.json}"

    # Systemd
    if [[ "$with_systemd" == true ]]; then
        if [[ "$(id -u)" != "0" ]]; then
            _warn "--systemd requires root. Skipping unit creation."
        else
            _generate_systemd_unit "$install_dir" "$host" "$port" "$workers" "$run_user"
        fi
    fi

    # Start
    if [[ "$no_start" != true ]] && [[ "$with_web" == true ]]; then
        _start_service "$install_dir" "$host" "$port" "$workers" "$run_user"
    elif [[ "$no_start" != true ]]; then
        _info "Web console not installed. Use --with-web to enable."
        _info "CLI ready: $install_dir/bin/aise --help"
    fi

    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║     ✅ AISE v${VERSION} Installed!       ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════╝${NC}"
    echo ""
    echo "  Install dir:  $install_dir"
    echo "  Data dir:     $data_dir"
    echo "  Log dir:      $log_dir"
    echo "  Config:       $install_dir/config/global_project_config.json"
    echo "  CLI:          $install_dir/bin/aise"
    echo ""
    echo "  Quick start:"
    echo "    aise demand -p 'MyProject'     # Interactive session"
    echo "    aise run -r 'Build a CLI app'  # Run full workflow"
    echo ""
}

# ============================================================
# UPGRADE
# ============================================================
cmd_upgrade() {
    local install_dir="$DEFAULT_INSTALL_DIR"
    local keep_config=true
    local restart=true
    local backup=true

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --prefix|--install-dir) install_dir="$2"; shift 2 ;;
            --no-backup)   backup=false; shift ;;
            --no-restart)  restart=false; shift ;;
            --reset-config) keep_config=false; shift ;;
            -h|--help)
                echo "Usage: aise-${VERSION}.sh upgrade [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --prefix, --install-dir DIR  Installation directory (default: /opt/aise)"
                echo "  --no-backup                  Skip backup before upgrade"
                echo "  --no-restart                 Don't restart service after upgrade"
                echo "  --reset-config               Replace config with defaults"
                echo ""
                exit 0
                ;;
            *) _error "Unknown option: $1"; exit 1 ;;
        esac
    done

    install_dir="$(_resolve_dir "$install_dir")"

    local existing
    existing=$(_read_installed_version "$install_dir")
    if [[ -z "$existing" ]]; then
        _error "No existing AISE installation at $install_dir"
        _info "Run 'install' instead."
        exit 1
    fi

    echo ""
    _info "Upgrading AISE: v${existing} → v${VERSION}"
    echo ""

    # Stop service
    _stop_service "$install_dir"

    # Backup
    if [[ "$backup" == true ]]; then
        local backup_dir="$install_dir/backups/v${existing}-$(date +%Y%m%d%H%M%S)"
        mkdir -p "$backup_dir"
        _info "Backing up to $backup_dir..."
        cp -r "$install_dir/src" "$backup_dir/" 2>/dev/null || true
        cp "$install_dir/pyproject.toml" "$backup_dir/" 2>/dev/null || true
        cp "$install_dir/.aise_version" "$backup_dir/" 2>/dev/null || true
        cp -r "$install_dir/config" "$backup_dir/" 2>/dev/null || true
        _ok "Backup complete"
    fi

    # Save config
    local saved_config=""
    if [[ "$keep_config" == true ]] && [[ -f "$install_dir/config/global_project_config.json" ]]; then
        saved_config=$(mktemp)
        cp "$install_dir/config/global_project_config.json" "$saved_config"
    fi

    # Update source
    _info "Updating source files..."
    rm -rf "$install_dir/src"
    cp -r "$EXTRACT_DIR/src" "$install_dir/"
    cp -r "$EXTRACT_DIR/config" "$install_dir/"
    cp "$EXTRACT_DIR/pyproject.toml" "$install_dir/"
    cp "$EXTRACT_DIR/.aise_version" "$install_dir/"
    cp "$EXTRACT_DIR/.build_meta.json" "$install_dir/"

    # Restore config
    if [[ -n "$saved_config" ]]; then
        cp "$saved_config" "$install_dir/config/global_project_config.json"
        rm -f "$saved_config"
        _ok "User config preserved"
    fi

    # Update dependencies
    _info "Updating dependencies..."
    local pip="$install_dir/venv/bin/pip"
    if [[ -f "$pip" ]]; then
        "$pip" install --upgrade pip setuptools wheel -q 2>&1 | tail -1
        # Detect if web extras were installed
        local extras=""
        if "$pip" show uvicorn &>/dev/null 2>&1; then
            extras="[web]"
        fi
        "$pip" install -e "${install_dir}${extras}" -q 2>&1 | tail -3
        _ok "Dependencies updated"
    else
        _warn "Virtualenv not found. Re-run install to recreate."
    fi

    # Restart
    if [[ "$restart" == true ]]; then
        # Read env file for params
        if [[ -f "$install_dir/.env" ]]; then
            source "$install_dir/.env"
            local host="${AISE_HOST:-$DEFAULT_HOST}"
            local port="${AISE_PORT:-$DEFAULT_PORT}"
            local workers="${AISE_WORKERS:-$DEFAULT_WORKERS}"
            _start_service "$install_dir" "$host" "$port" "$workers" ""
        fi
    fi

    echo ""
    _ok "AISE upgraded to v${VERSION}"
}

# ============================================================
# UNINSTALL
# ============================================================
cmd_uninstall() {
    local install_dir="$DEFAULT_INSTALL_DIR"
    local keep_data=false
    local yes=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --prefix|--install-dir) install_dir="$2"; shift 2 ;;
            --keep-data)   keep_data=true; shift ;;
            --yes|-y)      yes=true; shift ;;
            -h|--help)
                echo "Usage: aise-${VERSION}.sh uninstall [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --prefix, --install-dir DIR  Installation directory (default: /opt/aise)"
                echo "  --keep-data                  Keep data and config directories"
                echo "  --yes, -y                    Skip confirmation prompt"
                echo ""
                exit 0
                ;;
            *) _error "Unknown option: $1"; exit 1 ;;
        esac
    done

    install_dir="$(_resolve_dir "$install_dir")"

    local existing
    existing=$(_read_installed_version "$install_dir")
    if [[ -z "$existing" ]]; then
        _error "No AISE installation found at $install_dir"
        exit 1
    fi

    if [[ "$yes" != true ]]; then
        echo ""
        _warn "This will uninstall AISE v${existing} from $install_dir"
        if [[ "$keep_data" != true ]]; then
            _warn "ALL data, config, and logs will be DELETED."
        fi
        read -rp "Continue? [y/N] " confirm
        if [[ "$confirm" != [yY] ]]; then
            _info "Cancelled."
            exit 0
        fi
    fi

    # Stop service
    _stop_service "$install_dir"

    # Remove systemd unit
    if [[ -f "/etc/systemd/system/${SYSTEMD_UNIT}.service" ]]; then
        _info "Removing systemd service..."
        sudo systemctl stop "$SYSTEMD_UNIT" 2>/dev/null || true
        sudo systemctl disable "$SYSTEMD_UNIT" 2>/dev/null || true
        sudo rm -f "/etc/systemd/system/${SYSTEMD_UNIT}.service"
        sudo systemctl daemon-reload 2>/dev/null || true
    fi

    # Remove symlinks
    rm -f /usr/local/bin/aise 2>/dev/null || true
    rm -f "$HOME/.local/bin/aise" 2>/dev/null || true

    # Remove files
    _info "Removing installation..."
    if [[ "$keep_data" == true ]]; then
        # Remove everything except data, config, logs
        rm -rf "$install_dir/src" "$install_dir/venv" "$install_dir/bin" \
               "$install_dir/backups" "$install_dir/trace" \
               "$install_dir/pyproject.toml" "$install_dir/.aise_version" \
               "$install_dir/.build_meta.json" "$install_dir/.env" \
               "$install_dir/$PIDFILE_NAME" "$install_dir/README.md" \
               "$install_dir/LICENSE"
        _ok "AISE removed (data/config/logs preserved at $install_dir)"
    else
        rm -rf "$install_dir"
        _ok "AISE completely removed from $install_dir"
    fi

    echo ""
    _ok "AISE v${existing} uninstalled."
}

# ============================================================
# INFO
# ============================================================
cmd_info() {
    echo ""
    echo -e "${BOLD}AISE Installer Package${NC}"
    echo "  Package version:  $VERSION"
    if [[ -f "$EXTRACT_DIR/.build_meta.json" ]]; then
        local build_time git_commit
        build_time=$(python3 -c "import json; d=json.load(open('$EXTRACT_DIR/.build_meta.json')); print(d.get('build_time','?'))" 2>/dev/null || echo "?")
        git_commit=$(python3 -c "import json; d=json.load(open('$EXTRACT_DIR/.build_meta.json')); print(d.get('git_commit','?'))" 2>/dev/null || echo "?")
        echo "  Build time:       $build_time"
        echo "  Git commit:       $git_commit"
    fi
    echo "  Python required:  >= 3.11"
    echo ""

    local install_dir="$DEFAULT_INSTALL_DIR"
    if [[ -f "$install_dir/.aise_version" ]]; then
        local installed
        installed=$(_read_installed_version "$install_dir")
        echo "  Installed:        v${installed} at $install_dir"
        if pid=$(_pid_alive "$install_dir/$PIDFILE_NAME"); then
            echo "  Status:           Running (PID $pid)"
        elif systemctl is-active --quiet "$SYSTEMD_UNIT" 2>/dev/null; then
            echo "  Status:           Running (systemd)"
        else
            echo "  Status:           Stopped"
        fi
    else
        echo "  Installed:        Not found at $install_dir"
    fi
    echo ""
}

# ============================================================
# Dispatch
# ============================================================
case "${1:-}" in
    install)   shift; cmd_install "$@" ;;
    upgrade)   shift; cmd_upgrade "$@" ;;
    uninstall) shift; cmd_uninstall "$@" ;;
    info)      shift; cmd_info "$@" ;;
    *)
        _error "Unknown command: ${1:-}"
        echo "Commands: install, upgrade, uninstall, info"
        exit 1
        ;;
esac
