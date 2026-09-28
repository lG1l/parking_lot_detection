# 10. 로컬 개발·테스트 가이드

> 🚧 미작성. 팀장과 문답으로 결정하는 중이다. 결정은 [11장](11-decisions.md)에 먼저 기록하고, 문답이 끝나면 이 장을 명세로 작성한다.

## 작성할 항목

- 로컬 실행 방법: 프론트, 백엔드, GPU 워커
- 로컬에서 AWS를 대신하는 방법: S3, SQS, Bedrock, GPU EC2
- 로컬 PostgreSQL 실행 방법
- 가짜 워커 실행 방법 (D-20)
- 로컬 테스트 방법
- 환경변수와 비밀값 관리 (DB 비밀번호, 연결 문자열 포함. 저장소에 커밋하지 않는다)
- 로컬 개발용 CORS 설정 (`flutter run -d chrome`과 FastAPI의 포트가 다름)
- CI 내용, 배포 스크립트 내용, Flutter 빌드 위치, GPU 워커 코드 배포 방식
- 서버 부팅 시 서비스 자동 실행 방식 (API 서버, PostgreSQL, GPU 워커)
- 백엔드 EC2 PostgreSQL 설치 스크립트 ([11장 D-17](11-decisions.md#d-17-db는-백엔드-ec2에-postgresql을-직접-설치한다)의 절차를 스크립트로)
- GPU 자동 꺼짐 설정과 시연 날 끄는 방법 (D-15, [02장 2.8](02-architecture.md#시연-날-설정))
- GPU EC2 접속(SSH) 방식
- GPU EC2 설치 스크립트: DLAMI 위에 Python 패키지 설치. Terraform에서 AMI ID를 변수로 고정하는 방법, 루트 볼륨 크기 확인 (D-21)
- Locust 실행 방법 (D-20)
- Python·Flutter·PostgreSQL 버전, 백엔드 EC2 OS 버전, 패키지 관리 도구, 포맷터·린터
- 브랜치·커밋 규칙

## 관련 결정·조건

- 배포 절차: D-13, [02장 2.8](02-architecture.md#28-배포와-운영)
- Flutter Web의 로컬 CORS: D-08
- SQS 규칙: D-16 / PostgreSQL 설치: D-17 / 가짜 워커·Locust: D-20 / GPU AMI: D-21
- 미결정: U-03
