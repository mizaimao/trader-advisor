#!/usr/bin/env bash
#
# deploy_to_hf.sh — sync this repo to the HuggingFace Space mirror and push.
#
# Usage:
#   tools/deploy_to_hf.sh                    # interactive (prompts for msg)
#   tools/deploy_to_hf.sh -m "fix wording"   # one-shot
#   tools/deploy_to_hf.sh --dry-run          # preview changes, don't commit

set -euo pipefail

HF_USER="DonkeyTheMoose"
HF_SPACE="trader-advisor"
HF_REMOTE_URL="https://huggingface.co/spaces/${HF_USER}/${HF_SPACE}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MIRROR_DIR="${SOURCE_DIR%/*}/hf-${HF_SPACE}"

EXCLUDES=(
  --exclude='.git'
  --exclude='.venv'
  --exclude='__pycache__'
  --exclude='.env'
  --exclude='temp.sh'
  --exclude='*.pyc'
  --exclude='tools/deploy_to_hf.sh'
  --exclude='tools/hf_readme.md'
  --exclude='README.md'
)

COMMIT_MSG=""
DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message) COMMIT_MSG="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=true; shift ;;
    -h|--help)    grep '^#' "$0" | sed 's/^# \?//'; exit 0 ;;
    *)            echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

say()  { printf '\n\033[1;36m▶\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

command -v rsync   >/dev/null || die "rsync missing. sudo dnf install rsync"
command -v git     >/dev/null || die "git missing."
command -v git-lfs >/dev/null || die "git-lfs missing. sudo dnf install git-lfs && git lfs install"
[[ -f "${SOURCE_DIR}/dashboard.py" ]] || die "Source doesn't look like trader-advisor: ${SOURCE_DIR}"
[[ -f "${SOURCE_DIR}/tools/hf_readme.md" ]] || die "Missing tools/hf_readme.md"

say "Source: ${SOURCE_DIR}"
say "Mirror: ${MIRROR_DIR}"

if [[ ! -d "${MIRROR_DIR}/.git" ]]; then
  say "Mirror not found. Cloning ${HF_REMOTE_URL}..."
  git clone "${HF_REMOTE_URL}" "${MIRROR_DIR}" \
    || die "Clone failed. Check HF credentials."
fi

say "Syncing files..."
RSYNC_FLAGS=(-av "${EXCLUDES[@]}")
$DRY_RUN && RSYNC_FLAGS+=(--dry-run)
rsync "${RSYNC_FLAGS[@]}" "${SOURCE_DIR}/" "${MIRROR_DIR}/"

say "Installing HF README..."
$DRY_RUN || cp "${SOURCE_DIR}/tools/hf_readme.md" "${MIRROR_DIR}/README.md"

cd "${MIRROR_DIR}"
[[ -f .env ]] && die ".env present in mirror — refusing to push."

say "Changes in mirror:"
git status --short

if [[ -z "$(git status --porcelain)" ]]; then
  say "Nothing to commit. Mirror up to date."
  exit 0
fi

if $DRY_RUN; then
  say "Dry run complete."
  exit 0
fi

if [[ -z "${COMMIT_MSG}" ]]; then
  printf '\nCommit message: '
  read -r COMMIT_MSG
  [[ -n "${COMMIT_MSG}" ]] || die "Empty commit message."
fi

git add .
git commit -m "${COMMIT_MSG}"

say "Pushing to HuggingFace..."
git push

say "Done. Watch build: ${HF_REMOTE_URL}"
