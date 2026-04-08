# List all available targets
default:
    @just --list

# Install git hooks (run once after cloning)
hooks:
    git config core.hooksPath .githooks

# Build sdist and wheel
build:
    uv build

# Remove build artifacts
clean:
    rm -rf dist/

# Sync dependencies (including optional map extras)
sync:
    uv sync --all-extras

# Lint and type-check (ruff --fix, ty check)
check:
    uv run ruff check --fix
    uv run ty check

# Run unit tests (default)
test *args:
    uv run pytest {{ args }}

# Run live end-to-end tests (require external services, use real credentials from settings.toml)
test-live *args:
    uv run pytest tests_live/ -v {{ args }}

# Update node database from input files and APIs
update region="LUX":
    uv run meshcore-tools nodes update --region {{ region }}

# List all nodes
list:
    uv run meshcore-tools nodes list

# Look up a node by public key prefix
lookup prefix:
    uv run meshcore-tools nodes lookup {{ prefix }}

# Clear the OSM tile cache
clear-tile-cache:
    rm -rf ~/.cache/meshcore-tools/tiles

# Start live packet monitor TUI
monitor region="LUX" poll="5":
    uv run meshcore-tools monitor --region {{ region }} --poll {{ poll }} --log-file /tmp/mc.log

# Append channels from a meshcore-cli companion to channels.txt (strips numeric prefixes)
# Usage: just get-channels               (uses first available device)
#        just get-channels /dev/ttyUSB0  (specify device)
get-channels connection="":
    meshcli {{connection}} "get_channels" | sed 's/^[0-9]*: //' >> channels.txt
