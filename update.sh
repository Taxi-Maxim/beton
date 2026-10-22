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
    # Stream the backup through exec: docker cp can miss files on mounted /tmp.
    if ! (
        umask 077
        compose exec -T web python - > "$backup.partial" <<'PYBACKUP'
import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

source_uri = Path(os.environ.get("BETON_DATABASE", "/data/beton.sqlite3")).resolve().as_uri() + "?mode=ro"
with tempfile.TemporaryDirectory(prefix="beton-backup-") as directory:
    snapshot = Path(directory) / "backup.sqlite3"
    with closing(sqlite3.connect(source_uri, uri=True)) as source:
        with closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
            if target.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("SQLite backup integrity check failed")
    with snapshot.open("rb") as stream:
        shutil.copyfileobj(stream, sys.stdout.buffer)
    sys.stdout.buffer.flush()
PYBACKUP
    ); then
        rm -f -- "$backup.partial"
        fail 'Не удалось сохранить резервную копию базы. Обновление остановлено.'
    fi
    [[ -s $backup.partial ]] || fail 'Получена пустая резервная копия. Обновление остановлено.'
    mv -- "$backup.partial" "$backup"
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
