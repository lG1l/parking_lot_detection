#!/usr/bin/env bash
# 백엔드 EC2를 켠 뒤 CloudShell에서 실행한다. CloudFront 원본을 새 퍼블릭 DNS로 바꾼다 (D-339)
# 사용법: bash update_origin.sh <배포ID> <백엔드 인스턴스ID>
set -euo pipefail

dist_id=${1:?배포 ID가 필요하다}
instance_id=${2:?백엔드 인스턴스 ID가 필요하다}

dns=$(aws ec2 describe-instances --instance-ids "$instance_id" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
[[ -n $dns && $dns != None ]] || { echo "퍼블릭 DNS가 없다. 인스턴스가 켜져 있는지 확인한다"; exit 1; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# 설정에 비밀 헤더 값이 들어 있으므로 파일은 본인만 읽게 하고 끝나면 지운다
umask 077

aws cloudfront get-distribution-config --id "$dist_id" > "$tmp/current.json"
etag=$(jq -r .ETag "$tmp/current.json")
jq --arg dns "$dns" '.DistributionConfig | .Origins.Items[0].DomainName = $dns' \
  "$tmp/current.json" > "$tmp/new.json"

aws cloudfront update-distribution --id "$dist_id" --if-match "$etag" \
  --distribution-config "file://$tmp/new.json" > /dev/null
echo "원본을 $dns 로 바꿨다. 반영을 기다린다 (보통 수 분)"
aws cloudfront wait distribution-deployed --id "$dist_id"
echo "반영 완료"
