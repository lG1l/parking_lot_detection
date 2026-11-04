#!/usr/bin/env bash
# 백엔드 갱신 (D-125, D-152, D-154). 부팅 때 backend-update.service가, 켜진 채로는 Actions 배포 버튼이 실행한다.
# 실패하면 그 단계에서 멈추고 API 서버·주기 작업을 시작하지 않는다 (D-126). 기록: journalctl -u backend-update
set -Eeuo pipefail

APP_USER=ubuntu
APP_DIR=/home/ubuntu/app
UV=/home/ubuntu/.local/bin/uv
WEB_URL=https://github.com/lG1l/parking_lot_detection/releases/download/web-latest/web.tar.gz

step() { current="$*"; echo "== $*"; }
current="시작 전 확인"
as_app() { runuser -u "$APP_USER" -- env HOME="/home/$APP_USER" "$@"; }
trap 'echo "!! 갱신 실패 단계: $current. 서비스를 시작하지 않는다" >&2' ERR

[[ $EUID -eq 0 ]] || { echo "sudo로 실행한다" >&2; exit 1; }
[[ -f $APP_DIR/backend/.env ]] || { echo "backend/.env가 없다. Actions 배포 버튼을 실행한다" >&2; exit 1; }

# 새 코드와 예전 코드·DB가 섞여 돌지 않게 먼저 멈춘다
systemctl stop backend-api backend-periodic

step "최신 main 받기"
as_app git -C "$APP_DIR" fetch --quiet origin main
as_app git -C "$APP_DIR" reset --quiet --hard origin/main  # 서버에서 고친 코드는 사라진다 (D-125 주의점 11)
as_app git -C "$APP_DIR" log -1 --format='%h %s'

step "uv sync"
cd "$APP_DIR/backend"
as_app "$UV" sync --locked --no-dev

step "화면 파일 받기 (web.tar.gz)"
tmp=$(as_app mktemp -d)
as_app curl -fsSL --retry 3 -o "$tmp/web.tar.gz" "$WEB_URL"
as_app mkdir "$tmp/web"
as_app tar -xzf "$tmp/web.tar.gz" -C "$tmp/web"
[[ -f $tmp/web/index.html ]] || { echo "web.tar.gz에 index.html이 없다" >&2; exit 1; }
rm -rf "$APP_DIR/backend/web"
mv "$tmp/web" "$APP_DIR/backend/web"
rm -rf "$tmp"

step "DB 마이그레이션"
as_app "$UV" run --no-sync alembic upgrade head

step "서비스 시작"
systemctl start backend-api backend-periodic
step "완료"
