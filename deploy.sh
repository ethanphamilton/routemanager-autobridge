#!/usr/bin/env bash
# Deploy Catalyst functions, injecting each function's .env into its
# catalyst-config.json. Configs are restored after deploy regardless of outcome.

set -e

FUNCTIONS=(rm_autobridge rm_callback)
BACKUPS=()

restore_configs() {
  for backup in "${BACKUPS[@]}"; do
    [ -f "$backup" ] && mv "$backup" "${backup%.bak}"
  done
}
trap restore_configs EXIT

for fn in "${FUNCTIONS[@]}"; do
  env_file="functions/$fn/.env"
  config_file="functions/$fn/catalyst-config.json"

  if [ ! -f "$env_file" ]; then
    echo "ERROR: $env_file not found"
    exit 1
  fi
  if [ ! -f "$config_file" ]; then
    echo "ERROR: $config_file not found"
    exit 1
  fi

  cp "$config_file" "${config_file}.bak"
  BACKUPS+=("${config_file}.bak")

  python3 - "$env_file" "$config_file" <<'PYEOF'
import json, sys

env_file, config_file = sys.argv[1], sys.argv[2]

env = {}
with open(env_file) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        env[key.strip()] = val.strip().strip('"').strip("'")

with open(config_file) as f:
    config = json.load(f)

config['deployment']['env_variables'] = env

with open(config_file, 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')

print(f"Injected {len(env)} env vars into {config_file}")
PYEOF
done

# CATALYST_TOKEN / CATALYST_PROJECT_ID / CATALYST_ORG_ID are set only in CI
# (see .github/workflows/deploy.yml) to allow non-interactive deploys; unset
# for local/manual use, where an existing `catalyst login` session plus the
# gitignored .catalystrc is used instead. Note: GitHub Actions (and most CI
# systems) sets CI=true, which makes the Catalyst CLI ignore .catalystrc
# entirely and require -p + --org explicitly - confirmed by testing, not
# documented anywhere. -p alone is not enough; both must be supplied together.
CATALYST_DEPLOY_ARGS=(--only functions)
if [ -n "${CATALYST_TOKEN:-}" ]; then
  CATALYST_DEPLOY_ARGS+=(--token "$CATALYST_TOKEN")
fi
if [ -n "${CATALYST_PROJECT_ID:-}" ]; then
  CATALYST_DEPLOY_ARGS+=(-p "$CATALYST_PROJECT_ID")
fi
if [ -n "${CATALYST_ORG_ID:-}" ]; then
  CATALYST_DEPLOY_ARGS+=(--org "$CATALYST_ORG_ID")
fi

# The catalyst CLI has been observed to exit 0 even when it deploys nothing
# (e.g. "No components deployed!" on an auth/config error), so `set -e` alone
# can't be trusted here - check the actual output for known failure markers.
# "✖" is the CLI's own error-line indicator, used as a catch-all alongside the
# specific phrases already seen, in case of future error message variants.
set +e
DEPLOY_OUTPUT="$(catalyst deploy "${CATALYST_DEPLOY_ARGS[@]}" 2>&1)"
DEPLOY_EXIT=$?
set -e
echo "$DEPLOY_OUTPUT"

if [ "$DEPLOY_EXIT" -ne 0 ] || echo "$DEPLOY_OUTPUT" | grep -qiE "✖|no components deployed|deploy skipped|http error|cannot be empty|not valid"; then
  echo "ERROR: catalyst deploy did not fully succeed" >&2
  exit 1
fi
