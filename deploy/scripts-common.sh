#!/usr/bin/env bash

set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
fail() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }
require_root() { [[ $EUID -eq 0 ]] || fail "Запустите: sudo bash $0"; }
lock_deploy() {
    mkdir -p .deploy
    chmod 700 .deploy
    exec 9>.deploy/lock
    flock -n 9 || fail 'Установка или обновление уже выполняется.'
}
compose() { docker compose "$@"; }
start_site() {
    compose config --quiet
    compose build --pull
    compose up -d --wait --wait-timeout 180
    compose ps
}
save_repository() {
    local repository=${REPO_URL:-} branch=${BRANCH:-}
    if [[ -z $repository && -f .deploy/repository ]]; then
        repository=$(cat .deploy/repository)
    fi
    if [[ -z $repository && -d .git ]]; then
        repository=$(git config --get remote.origin.url || true)
    fi
    if [[ -z $repository ]]; then
        read -r -p 'URL GitHub репозитория (https://github.com/owner/repo.git): ' repository
    fi
    [[ $repository == https://github.com/* || $repository == git@github.com:* || $repository == ssh://git@github.com/* ]] || fail 'Укажите URL репозитория GitHub.'
    if [[ -z $branch && -f .deploy/branch ]]; then branch=$(cat .deploy/branch); fi
    if [[ -z $branch ]]; then
        branch=$(git ls-remote --symref "$repository" HEAD | sed -n 's|^ref: refs/heads/\(.*\)[[:space:]]HEAD$|\1|p')
    fi
    [[ -n $branch ]] || fail 'Не удалось определить ветку. Укажите BRANCH=main.'
    git check-ref-format "refs/heads/$branch" >/dev/null
    printf '%s\n' "$repository" > .deploy/repository
    printf '%s\n' "$branch" > .deploy/branch
}
