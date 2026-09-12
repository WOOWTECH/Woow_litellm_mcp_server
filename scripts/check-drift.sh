#!/usr/bin/env bash
# Compare charts/litellm-mcp with what is running. Exit 0 = in sync, 1 = drift.
#   1. repo vs release : helm template (this repo) <-> helm get manifest
#   2. repo vs cluster : kubectl diff of the rendered chart against live objects
# Extra arguments are passed to `helm template`, e.g. --set admin.storage.size=1Gi.
#   CONTEXT=woow-k3s RELEASE=litellm-mcp NAMESPACE=litellm scripts/check-drift.sh
#
# Before the phase-2 takeover the MCP objects still belong to release `litellm`
# in namespace `litellm`; compare against that one instead:
#   RELEASE=litellm scripts/check-drift.sh   # step 1 will list the gateway
#                                            # objects as missing here - expected
set -euo pipefail

CONTEXT="${CONTEXT:-woow-k3s}"
RELEASE="${RELEASE:-litellm-mcp}"
NAMESPACE="${NAMESPACE:-litellm}"
VALUES="${VALUES:-deploy/woow-k3s/litellm-mcp.yaml}"
cd "$(dirname "$0")/.."

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

helm template "$RELEASE" charts/litellm-mcp -n "$NAMESPACE" --skip-tests \
  -f "$VALUES" "$@" > "$tmp/repo.yaml"
helm --kube-context "$CONTEXT" get manifest "$RELEASE" -n "$NAMESPACE" > "$tmp/release.yaml"

rc=0
# -B: helm get manifest ends with an extra blank line that helm template does not.
if diff -u -B "$tmp/release.yaml" "$tmp/repo.yaml" > "$tmp/repo.diff"; then
  echo "1. repo == release ${RELEASE}"
else
  echo "1. DRIFT: this repo renders differently from release ${RELEASE}:"
  cat "$tmp/repo.diff"
  rc=1
fi

set +e
kubectl --context "$CONTEXT" diff -f "$tmp/repo.yaml" > "$tmp/live.diff" 2>&1
krc=$?
set -e
case "$krc" in
  0) echo "2. cluster == chart (context ${CONTEXT})" ;;
  1) echo "2. DRIFT: live objects differ from the chart:"; cat "$tmp/live.diff"; rc=1 ;;
  *) cat "$tmp/live.diff" >&2; exit "$krc" ;;
esac
exit "$rc"
