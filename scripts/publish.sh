#!/usr/bin/env bash
# Publish the job's output (state/ and docs/) to the repository. Fails LOUDLY: the job must not look green if nothing was published.
set -euo pipefail
git config user.name "mis-bot"
git config user.email "mis-bot@users.noreply.github.com"
git add state docs
if git diff --cached --quiet; then echo "Nothing new to publish."; exit 0; fi
git commit -q -m "Dashboard update $(date -u +%F)"
branch="$(git rev-parse --abbrev-ref HEAD)"
for attempt in 1 2 3 4 5; do
  # -X theirs: if the same generated file changed on both sides, the job's fresh output wins
  if git pull --rebase -X theirs origin "$branch" && git push origin "HEAD:$branch"; then
    echo "Published on attempt $attempt."; exit 0
  fi
  git rebase --abort 2>/dev/null || true
  echo "Publish attempt $attempt failed; retrying..." >&2; sleep $((attempt * 5))
done
echo "ERROR: could not publish after 5 attempts. The dashboard was NOT updated." >&2
exit 1
