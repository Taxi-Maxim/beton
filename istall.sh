#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/deploy/scripts-common.sh"
require_root
source /etc/os-release
[[ $ID == ubuntu ]] || fail 'Автоустановка поддерживает Ubuntu 22.04/24.04.'
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git rsync util-linux
lock_deploy
if ! docker compose version >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
        "$(dpkg --print-architecture)" "${UBUNTU_CODENAME:-$VERSION_CODENAME}" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
save_repository
if [[ ! -f .env ]]; then
    origin=${BETON_PUBLIC_ORIGIN:-}
    bind=${APP_BIND_IP:-127.0.0.1}
    port=${APP_PORT:-8000}
    if [[ -z $origin ]]; then read -r -p 'Публичный адрес сайта (https://your-domain): ' origin; fi
    [[ $origin =~ ^https?://[a-zA-Z0-9.-]+(:[0-9]+)?$ ]] || fail 'Нужен адрес http(s)://домен без пути.'
    [[ $bind =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'APP_BIND_IP должен быть IPv4-адресом сервера.'
    [[ $port =~ ^[0-9]+$ && ${#port} -le 5 ]] || fail 'Некорректный APP_PORT.'
    (( 10#$port >= 1 && 10#$port <= 65535 )) || fail 'APP_PORT должен быть от 1 до 65535.'
    secure=true
    [[ $origin == https://* ]] || secure=false
    umask 077
    printf 'BETON_PUBLIC_ORIGIN=%s\nBETON_COOKIE_SECURE=%s\nAPP_PORT=%s\nAPP_BIND_IP=%s\n' \
        "$origin" "$secure" "$port" "$bind" > .env
fi
chmod 600 .env
start_site
printf 'Установка завершена. Обновление: cd %q && sudo bash update.sh\n' "$ROOT"
