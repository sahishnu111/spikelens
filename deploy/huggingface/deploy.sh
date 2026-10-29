#!/usr/bin/env bash
# Publish the app to a Hugging Face Docker Space.
# Prereqs: `pip install -U huggingface_hub` and `hf auth login` (write token), then:
#   DRY_RUN=1 ./deploy/huggingface/deploy.sh <hf-username>   # stage only
# or
#   ./deploy/huggingface/deploy.sh <hf-username>
set -euo pipefail
USER_NAME="${1:?usage: deploy.sh <hf-username>}"
SPACE="$USER_NAME/spikelens"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
cp -r "$ROOT/spikelens" "$ROOT/requirements.txt" "$ROOT/Dockerfile" "$TMP/"
cp "$ROOT/deploy/huggingface/README.md" "$TMP/README.md"
# public demo: disable outbound webhooks (avoids the instance being used to send requests)
sed -i 's/SPIKELENS_DB=\/data\/spikelens.db/SPIKELENS_DB=\/data\/spikelens.db SPIKELENS_ALLOW_WEBHOOKS=0/' "$TMP/Dockerfile"
if [ "${DRY_RUN:-0}" = "1" ]; then echo "dry run, staged files in $TMP"; ls "$TMP"; grep ALLOW "$TMP/Dockerfile"; exit 0; fi
hf repos create "$SPACE" --repo-type space --space-sdk docker --public --exist-ok
hf upload "$SPACE" "$TMP" . --repo-type space --commit-message "Deploy SpikeLens"
echo "Deployed: https://huggingface.co/spaces/$SPACE  (app: https://${USER_NAME}-spikelens.hf.space)"
