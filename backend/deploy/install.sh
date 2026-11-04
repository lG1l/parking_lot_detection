#!/usr/bin/env bash
# 백엔드 EC2(Ubuntu 24.04) 첫 설치 (D-223). 여러 번 돌려도 결과가 같다.
#   git clone https://github.com/lG1l/parking_lot_detection.git /home/ubuntu/app
#   sudo /home/ubuntu/app/backend/deploy/install.sh [GPU 프라이빗 IP]
# GPU를 아직 만들지 않았으면 IP 없이 실행하고, 만든 뒤 IP를 넣어 다시 실행한다.
# 끝나면 Actions 배포 버튼으로 .env를 쓰고 갱신 스크립트를 돌린다 (D-125 주의점 1ⓐ).
set -euo pipefail

APP_USER=ubuntu
APP_DIR=/home/ubuntu/app
UV_VERSION=0.12.5
PG_VERSION=16
PG_CONF_DIR=/etc/postgresql/$PG_VERSION/main
DB_NAME=parking
DB_USER=app
GPU_IP=${1:-}

step() { echo "== $*"; }

[[ $EUID -eq 0 ]] || { echo "sudo로 실행한다" >&2; exit 1; }
[[ -d $APP_DIR/.git ]] || { echo "$APP_DIR에 저장소를 먼저 clone한다" >&2; exit 1; }
if [[ -n $GPU_IP && ! $GPU_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "GPU 프라이빗 IP 형식이 아니다: $GPU_IP" >&2; exit 1
fi

step "PostgreSQL $PG_VERSION 설치 (D-17, D-144)"
apt-get update
apt-get install -y "postgresql-$PG_VERSION" curl git
systemctl enable --now postgresql

step "DB 사용자·DB 만들기"
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER'" | grep -q 1; then
  echo "사용자 $DB_USER가 이미 있다. 비밀번호는 바꾸지 않는다"
else
  # 비밀번호는 명령 인자·셸 기록에 남지 않게 입력받아 psql 표준 입력으로만 넘긴다
  read -rsp "DB 비밀번호 (GitHub Secrets에 넣을 값과 같게): " pw; echo
  read -rsp "한 번 더: " pw2; echo
  [[ -n $pw && $pw == "$pw2" ]] || { echo "비어 있거나 서로 다르다" >&2; exit 1; }
  printf "CREATE ROLE %s LOGIN PASSWORD '%s';\n" "$DB_USER" "${pw//\'/\'\'}" \
    | sudo -u postgres psql -v ON_ERROR_STOP=1 -q
  unset pw pw2
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1; then
  sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
fi

step "GPU에서 오는 접속 허용 (D-17)"
private_ip=$(hostname -I | awk '{print $1}')
echo "listen_addresses = 'localhost,$private_ip'" > "$PG_CONF_DIR/conf.d/app.conf"
if [[ -n $GPU_IP ]]; then
  sed -i '/# app-gpu$/d' "$PG_CONF_DIR/pg_hba.conf"
  echo "host  $DB_NAME  $DB_USER  $GPU_IP/32  scram-sha-256  # app-gpu" >> "$PG_CONF_DIR/pg_hba.conf"
else
  echo "GPU IP가 없어 접속 허용을 바꾸지 않는다. GPU를 만든 뒤 IP를 넣어 다시 실행한다"
fi
systemctl restart postgresql

step "uv $UV_VERSION 설치 (D-119, Python 3.12는 uv sync가 받는다)"
if [[ "$(sudo -iu "$APP_USER" uv --version 2>/dev/null)" != "uv $UV_VERSION"* ]]; then
  sudo -iu "$APP_USER" bash -c "curl -LsSf https://astral.sh/uv/$UV_VERSION/install.sh | sh"
fi

step "자동 실행 서비스 등록 (D-125)"
cp "$APP_DIR"/backend/deploy/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable backend-update.service

step "완료. 이제 Actions 배포 버튼을 한 번 실행한다"
