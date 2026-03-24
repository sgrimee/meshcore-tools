# List all available targets
default:
    @just --list

# Install git hooks (run once after cloning)
hooks:
    git config core.hooksPath .githooks

# Sync dependencies (including optional map extras)
sync:
    uv sync --all-extras

# Lint and type-check (ruff --fix, ty check)
check:
    uv run ruff check --fix
    uv run ty check

# Run tests
test *args:
    uv run pytest {{ args }}

# Update node database from input files and APIs
update region="LUX":
    uv run lma nodes update --region {{ region }}

# List all nodes
list:
    uv run lma nodes list

# Look up a node by public key prefix
lookup prefix:
    uv run lma nodes lookup {{ prefix }}

# Start live packet monitor TUI
monitor region="LUX" poll="5":
    uv run lma monitor --region {{ region }} --poll {{ poll }}

# Append channels from a meshcore-cli companion to channels.txt (strips numeric prefixes)
# Usage: just get-channels               (uses first available device)
#        just get-channels /dev/ttyUSB0  (specify device)
get-channels connection="":
    meshcli {{connection}} "get_channels" | sed 's/^[0-9]*: //' >> channels.txt
