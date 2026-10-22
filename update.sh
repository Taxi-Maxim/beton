#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/deploy/scripts-common.sh"
main() {
require_root
for command in git rsync docker flock; do
    command -v "$command" >/dev/null || fail "Нет $command. Сначала запустите sudo bash istall.sh."
done
[[ -f .env ]] || fail 'Нет .env. Сначала запустите sudo bash istall.sh.'
lock_deploy
save_repository
repository=$(cat .deploy/repository)
branch=$(cat .deploy/branch)
if [[ ! -d .deploy/git ]]; then git init --bare .deploy/git; fi
git --git-dir=.deploy/git fetch --depth=1 -- "$repository" "refs/heads/$branch"
revision=$(git --git-dir=.deploy/git rev-parse FETCH_HEAD)
stage=$(mktemp -d "$ROOT/.deploy/release.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
git --git-dir=.deploy/git archive "$revision" | tar -x -C "$stage"
[[ -f $stage/docker-compose.yml && -f $stage/Dockerfile && -f $stage/games_5_7.html ]] || fail 'В репозитории отсутствуют файлы приложения.'
compose config --quiet
container=$(compose ps -q web)
if [[ -n $container ]]; then
    mkdir -p .deploy/backups
    backup=".deploy/backups/beton-$(date +%Y%m%d-%H%M%S)-$$.sqlite3"
    compose exec -T web python -c 'import sqlite3; source=sqlite3.connect("/data/beton.sqlite3"); target=sqlite3.connect("/tmp/deploy-backup.sqlite3"); source.backup(target); target.close(); source.close()'
    docker cp "$container:/tmp/deploy-backup.sqlite3" "$backup"
    chmod 600 "$backup"
    printf 'Резервная копия базы: %s\n' "$backup"
fi
# Keep local configuration, runtime data and deployment state across releases.
# Source files in this directory are managed by the selected GitHub branch.
rsync -a --delete --exclude='.git' --exclude='.env' --exclude='.env.*' \
    --exclude='.deploy' --exclude='.venv' --exclude='data' --exclude='instance' \
    --exclude='*.sqlite3' --exclude='*.sqlite3-*' "$stage/" "$ROOT/"
start_site
printf '%s\n' "$revision" > .deploy/version
printf 'Сайт обновлён до %s (ветка %s).\n' "$revision" "$branch"
}
main "$@"
