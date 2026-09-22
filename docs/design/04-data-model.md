# 04. 데이터 모델

> 마지막 수정: 2026-09-22
> 표시: 🚧 미정 · ⚠️ 확인 필요 · 🔐 멘토 승인 필요
>
> U-21·U-22·U-23을 팀원 2가 정리해(D-24, D-25, D-26) 본문을 작성했고, 4.10의 DDL 규칙을 D-27로, 관리자 업로드 방식(U-14)을 D-28로, 차량·파손 부위 입력 방식(U-13 일부)을 D-29로, 세션 저장 방식을 D-30으로, 사건 지점 고정 방식을 D-32로, 중복 저장 정리를 D-33~D-35로, 누끼를 우선 빼는 안을 D-36으로, 묶음 단위 [다음]을 D-37로, 고정 해제 없음을 D-40으로, 원본 허용 형식과 코덱 불량 시 바로 `failed`를 D-43으로, 링크로만 업로드(`upload_token_id` NOT NULL)를 D-45로, SQS에 넣고 나서 커밋하는 순서(4.4)를 D-46으로 더했다. 마스킹본·분석 결과 파기(U-24)는 D-57로 더했다. 이 중 **D-27·D-28·D-29·D-30·D-32·D-35·D-37·D-40·D-41·D-45·D-46·D-48·D-51·D-52·D-53·D-57은 확정**이고, 나머지는 상태가 **"확정 필요"** 다. 특히 **U-23(트랙 파일 형식)은 담당이 팀장**이므로 팀장이 확인해야 확정된다. D-29는 입력 방식만 확정이고, U-13의 나머지(룰 상황 목록·근접 판정·인접 영역)는 팀장 담당으로 남는다. 확정되지 않은 결정을 전제로 백엔드 구현을 시작해도 되지만, 뒤집힐 수 있다는 것을 알고 진행한다.

## 4.1 전체 구조

DB는 백엔드 EC2의 PostgreSQL이다. 백엔드와 GPU 워커가 같은 DB에 접속한다. (D-17)

```
users ──┬──< sessions        (로그인 세션)
        │
        ├──< upload_tokens   (업로드 전용 일회용 링크)
        │
        ├──< access_logs     (열람·발급·파기 기록, D-53)
        │
        └──< videos ──1:1── analysis_jobs ──< chunks
                                  │
                                  ├──  still_frames        (정지 장면 1장, 마스킹본)
                                  ├──1:1── vehicle_selections  (본인 차량 선택)
                                  ├──1:1── damage_inputs       (파손 부위 입력)
                                  ├──< candidates ──< candidate_clips
                                  └──1:1── pinned_incidents    (사건 지점 고정)
```

- `──<` 는 1:N, `──1:1──` 은 1:1을 뜻한다.
- **영상 1건 = `analysis_jobs` 1행**이다. 분석의 진행 상태는 이 행의 `status` 칼럼 하나로 관리한다. (D-24)
- U-21에서 `analysis`라고 부른 테이블이 `analysis_jobs`다. 04장 초안의 엔티티 이름 `AnalysisJob`과 같은 것이며, 앞으로는 `analysis_jobs`로 통일한다.
- 테이블 이름은 소문자 복수형 snake_case로 쓴다. `user`는 PostgreSQL 예약어라 쓸 수 없어 `users`로 한다.

**초안 목록에서 늘어난 테이블 5개**

| 테이블 | 추가한 이유 |
|---|---|
| `sessions` | 로그인 세션을 서버 메모리가 아니라 DB에 둔다. 무상태 규칙(D-19)이자, 유출된 세션을 즉시 끊기 위해서다 (D-30) |
| `still_frames` | 정지 장면(마스킹본 이미지)이 어느 원본 시간의 것이고 비식별화가 끝났는지 알아야 화면에 보여줄 수 있다. 불변 조건 2 |
| `chunks` | 청크별 진행 상황과 트랙 파일 위치를 기록한다. 청크는 독립 단위다 (D-03) |
| `upload_tokens` | 관리자는 로그인하지 않고 **업로드 전용 일회용 링크**로만 올린다. 그 링크의 주인·만료·사용 여부를 기록한다 (D-28) |
| `access_logs` | 개인영상정보에 닿는 요청을 한 행씩 남긴다. 표준 개인정보 보호지침 제44조⑤(열람 기록)·제42조(이용·파기 기록)와 고시 제8조①(접속기록 1년)이 요구하는 법정 기록이다 (D-53) |

## 4.2 테이블과 필드

공통 규칙은 [4.7 시간 필드 규칙](#47-시간-필드-규칙)을 따른다. `id`는 모두 자동 증가 정수(bigserial) 기본키다.

### users

계정은 **피해자 것 한 종류뿐**이다. 주차장 관리자는 계정을 만들지 않고 업로드 전용 링크로만 올리므로 역할(role) 칼럼이 없다. (D-28) 비밀번호 해시 방식과 쿠키 속성의 세부는 08장에서 정한다. 🚧

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `login_id` | text UNIQUE | 로그인 아이디 |
| `password_hash` | text | 평문 비밀번호를 저장하지 않는다 |
| `name` | text | 화면 표시용 이름 |
| `created_at` | timestamptz | |

### sessions

로그인 세션 하나. 서버 메모리가 아니라 DB에 둔다. (D-19, D-30)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `token` | text UNIQUE | 쿠키에 담기는 랜덤 문자열 |
| `user_id` | bigint FK → users | 누구의 세션인가 |
| `expires_at` | timestamptz | 이 시각이 지나면 만료. 연장하지 않는다 |
| `created_at` | timestamptz | 로그인한 시각 |

- 로그인에 성공하면 행을 만들고 `token`을 **HttpOnly 쿠키**로 내려준다. 요청마다 쿠키의 값으로 이 표를 찾아 `expires_at > now()`이면 통과시킨다.
- **로그아웃은 행을 지우는 것**이다. 유출된 세션도 같은 방법으로 즉시 끊을 수 있다. HTTPS가 없는 상태(02장 2.11)에서 이것이 JWT 대신 DB 세션을 고른 이유다. (D-30)
- `upload_tokens`와 모양이 같지만 **용도가 다르다.** 이 표는 열람 권한을 가진 로그인이고, `upload_tokens`는 업로드만 되는 1회용 링크다. 업로드 API는 쿠키를 보지 않는다.
- 만료된 행을 지우는 정리 작업은 두지 않는다. 데모 규모에서는 쌓여도 문제가 없다.

### upload_tokens

피해자가 발급한 **업로드 전용 일회용 링크** 하나. 관리자는 이 링크로만 올린다. 링크에는 영상을 올리는 것 말고 아무 권한도 없다. (D-28)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `token` | text UNIQUE | 링크 주소에 들어가는 랜덤 문자열. 추측할 수 없게 만든다 |
| `owner_user_id` | bigint FK → users | 이 링크로 올린 영상의 주인 |
| `expires_at` | timestamptz | 이 시각이 지나면 쓸 수 없다. 유효 시간은 01장 1.6 |
| `used_at` | timestamptz | 업로드를 시작한 시각. 비어 있지 않으면 다시 쓸 수 없다 |
| `created_at` | timestamptz | 발급 시각 |

- 링크를 쓸 수 있는 조건은 **`used_at`이 비어 있고 `expires_at`이 지나지 않았을 때**다. 둘 중 하나라도 어긋나면 업로드 화면이 "만료된 링크"를 보여준다.
- 만료되거나 이미 쓴 링크는 피해자가 로그인해서 다시 발급한다. 발급 이력은 행으로 쌓인다.
- **다시 발급하면 아직 쓰지 않은 이전 링크의 `expires_at`을 `now()`로 바꿔 무효로 만든다.** 한 사용자에게 살아 있는 링크는 하나뿐이다 (D-28, 05장 5.4).
- `used_at`은 **업로드용 presigned URL을 발급할 때** 찍는다. 그래서 업로드가 중간에 실패하면 링크는 이미 쓴 것이 되고, 다시 발급받아야 한다. 발급이 한 번 더 필요할 뿐이라 이대로 둔다.
- `token`은 해시하지 않고 그대로 저장한다. 비밀번호와 달리 짧게 살고 1회만 쓰며, 유출돼도 할 수 있는 일이 "그 피해자 소유로 영상 1건 올리기"뿐이다. ⚠️ 유효 시간·발급 방식의 확정은 08장(D-28)에서 한다.

### videos

업로드한 원본 영상 1건. 행은 **업로드용 presigned URL을 발급할 때** 만든다(그때 S3 키가 정해지기 때문이다). 업로드가 끝나지 않았으면 `upload_completed_at`이 비어 있다. (D-18)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | S3 키에도 쓴다 (4.9) |
| `owner_user_id` | bigint FK → users | 영상의 주인. 결과를 보는 사용자 |
| `upload_token_id` | bigint FK → upload_tokens, NOT NULL | 어느 링크로 올라왔는지. 영상은 업로드 링크로만 올라온다 (D-28, D-45) |
| `s3_key` | text | 원본 버킷 안의 키 (4.9) |
| `original_filename` | text | 관리자가 올린 파일 이름 |
| `size_bytes` | bigint | 업로드 URL 발급 때 브라우저가 알려준 크기. 5GB 검사에 쓴 값 (05장 5.4) |
| `duration_sec` | double precision | 영상 길이(초). GPU 워커가 1단계에서 채운다 |
| `fps` | double precision | 원본 fps. 워커가 채운다. 샘플링 fps와 다르다 |
| `width`, `height` | integer | 원본 해상도. 워커가 채운다 |
| `created_at` | timestamptz | URL 발급 시각 |
| `upload_completed_at` | timestamptz | 업로드 완료 알림을 받은 시각. 비어 있으면 미완료 |
| `last_activity_at` | timestamptz | 마지막 사용자 조작 시각. 원본 파기 시점 계산에 쓴다 (D-52) |
| `raw_deleted_at` | timestamptz | 원본을 S3에서 지운 시각. 비어 있으면 원본이 아직 있다 (D-52) |
| `masked_deleted_at` | timestamptz | 마스킹본·분석 결과를 S3에서 지운 시각. 비어 있으면 아직 있다 (D-57) |

- `duration_sec`·`fps`·`width`·`height`는 업로드 시점에 알 수 없다. 워커가 1단계 시작 때 원본을 열어 채운다.
- **`last_activity_at`은 사용자가 무언가를 한 순간마다 갱신한다.** 갱신하는 지점은 업로드 완료 알림, 차량·파손 부위 입력 저장, 후보 묶음 조회, [다음], [찾음]이다. 상태 조회(폴링)로는 갱신하지 않는다 — 화면을 켜 두기만 해도 파기가 밀리면 안 된다.
- **`raw_deleted_at`이 차 있으면 원본은 없다.** 재분석은 Non-Scope이므로 이 값이 다시 비워지는 일은 없다.
- **`masked_deleted_at`이 차 있으면 정지 장면·후보 클립·트랙 파일도 없다.** 기준은 `last_activity_at`이 아니라 `upload_completed_at`이다. 열람할 때마다 기한이 밀리면 수집일에서 30일을 넘겨 표준지침 제41조②에 어긋나기 때문이다. (D-57)

### analysis_jobs

영상 1건의 분석 작업. **영상 1건당 1행**이며 `video_id`에 UNIQUE를 건다. 행은 업로드 완료 알림을 받아 1단계 작업을 SQS에 넣을 때 만든다. (D-24)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | SQS 메시지의 `job_id`가 이 값이다 (4.6) |
| `video_id` | bigint FK → videos, UNIQUE | |
| `status` | text | 진행 상태. 값 목록은 [4.3](#43-분석-상태와-전이-규칙) |
| `stage1_started_at` | timestamptz | 1단계 시작 |
| `stage1_ended_at` | timestamptz | 1단계 종료 |
| `stage2_started_at` | timestamptz | 2단계 시작 |
| `stage2_ended_at` | timestamptz | 2단계 종료 |
| `input_completed_at` | timestamptz | 차량·파손 부위 입력이 끝난 시각. 2단계 시작 조건에 쓴다 |
| `error_message` | text | 실패했을 때 마지막 오류. 평소에는 비어 있다 |
| `created_at` | timestamptz | 대기 순서 계산의 기준 (4.5) |
| `updated_at` | timestamptz | 상태를 바꿀 때마다 갱신 |

- 시각 칼럼 4개는 09장 처리량 측정을 위한 것이다. `영상 길이 ÷ (stage1_ended_at − stage1_started_at)`로 "GPU 1대가 1시간에 처리하는 영상 시간"을 바로 계산한다. (D-20)
- **재시도가 일어나면 시각이 덮어써진다.** 마지막 시도 기준 값만 남는다. 재시도·실패 이력을 행으로 남기지 않기로 했다. 이유와 바꿀 시점은 D-24에 적었다.
- 인덱스: `(status, created_at)` — 4.5의 대기 순서 계산에 쓴다.

### chunks

청크 하나의 처리 상황. 청크는 독립 단위다. (D-03)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `analysis_job_id` | bigint FK → analysis_jobs | |
| `idx` | integer | 0부터 시작하는 청크 번호. `(analysis_job_id, idx)`에 UNIQUE |
| `start_sec`, `end_sec` | double precision | 원본 시간 기준 구간 |
| `status` | text | `pending` · `running` · `done` · `failed` |
| `track_s3_key` | text | 트랙 결과 파일 키 (4.8, 4.9). 완료 후 채운다 |
| `started_at`, `ended_at` | timestamptz | 청크별 소요 시간 측정용 |

- 청크 길이는 🚧 (U-06). 청크 개수 = `ceil(duration_sec ÷ 청크 길이)`.
- 1단계 종료 판정은 "이 작업의 모든 청크가 `done`"이다.

**이 표가 꼭 필요한가** (2026-09-17 검토)

- **없어도 된다.** 트랙 파일 이름이 `chunk_0003.jsonl`로 정해져 있고(4.9) S3에 올라간 파일은 완성본이므로, "파일이 있으면 그 청크는 끝난 것"으로 1단계 종료 판정과 재시작 건너뛰기를 할 수 있다. 청크 개수도 `duration_sec`에서 계산된다.
- **그럼에도 두는 이유는 가시성이다.** 분석이 멈췄을 때 S3 목록을 뒤지지 않고 `psql` 한 줄로 어디서 멈췄는지, 조각 하나에 몇 초 걸렸는지 본다. 팀에 경험이 적어 "무슨 일이 일어나는지 눈으로 보는 것"의 값이 크다. 비용은 테이블 하나와 청크마다 UPDATE 두 번뿐이다.

  ```sql
  SELECT idx, status, ended_at - started_at AS 걸린시간
    FROM chunks
   WHERE analysis_job_id = 42
   ORDER BY idx;
  ```

- 화면에 "12/40 조각 완료" 같은 진행률을 붙이고 싶어지면 이 표가 그대로 근거가 된다. 지금은 넣지 않는다(상태 표시는 4.3의 `status`뿐).
- **없앨 신호**: 청크 행을 쓰는 UPDATE가 1단계를 느리게 만들거나, 진행률을 끝내 안 쓰기로 정해질 때. 그때는 위의 "S3 파일 존재로 판정"으로 바꾸면 되고, 고칠 곳은 워커의 1단계 시작·종료 부분뿐이다.

### still_frames

차량 선택용 정지 장면. **원본 영상 시작 장면(첫 프레임) 1장이고, 작업 1건당 1행이다.** 1단계에서 가장 먼저 만든다 (D-48). 다른 시점 장면은 만들지 않는다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `analysis_job_id` | bigint FK → analysis_jobs, UNIQUE | 작업 1건당 1행 (D-48) |
| `t_sec` | double precision | 원본 시간. 시작 장면이라 `0.0`이다 |
| `masked_s3_key` | text | 비식별화가 끝난 이미지 키 (4.9) |
| `created_at` | timestamptz | |

- 원본 이미지는 저장하지 않는다. 비식별화된 것만 남긴다. (불변 조건 2)
- **원본 해상도 그대로 저장한다.** 사용자가 드래그한 좌표를 원본 해상도 픽셀로 받기 때문이다 (05장 5.1, 5.6).
- **정지 장면에서 차량을 탐지하지 않는다.** 누끼 없이 드래그한 사각형을 그대로 쓰기 때문이다. (D-36)
- **여러 시점의 장면을 다시 받으려면** UNIQUE를 `(analysis_job_id, t_sec)`으로 되돌리면 된다. 칼럼과 S3 키 구조는 그대로다. 절차는 [11장 D-48 "되살릴 방법"](11-decisions.md#d-48-차량-선택용-정지-장면은-원본-영상-시작-장면-1장만-만든다).
- **확장**: 누끼를 다시 넣으면 탐지된 차량 목록 `detections` 칼럼(jsonb)을 더한다. 예시와 절차는 [11장 D-36 "확장 방법"](11-decisions.md#d-36-우선-누끼-없이-드래그한-차량-사각형을-그대로-본인-차량-영역으로-쓴다).
  ```json
  [{"det_id": 1, "bbox": [810, 440, 960, 620], "conf": 0.91,
    "polygon": [[812, 441], [958, 445], [956, 618], [814, 615]]}]
  ```

### vehicle_selections

사용자가 고른 본인 차량. 작업 1건당 1행이다. (D-25)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `analysis_job_id` | bigint FK → analysis_jobs, UNIQUE | |
| `still_frame_id` | bigint FK → still_frames | 어느 정지 장면에서 골랐는지. 장면이 1장뿐이라 지금은 `analysis_job_id`에서 바로 나오지만, 05장 11번의 검사와 장면을 늘릴 여지를 위해 둔다 (D-48) |
| `schema_version` | integer | `payload` 형식 번호. 형식이 바뀌면 올린다 |
| `payload` | jsonb | 선택 내용 |
| `created_at`, `updated_at` | timestamptz | 다시 입력하면 같은 행을 덮어쓴다 |

사용자는 정지 장면에서 **본인 차량을 드래그로 지목한다.** 드래그한 사각형을 **탐지와 맞추지 않고 그대로** 본인 차량 영역으로 쓴다. (D-29, D-36)

`schema_version` 1:

```json
{
  "bbox": [800, 430, 970, 630]
}
```

| 키 | 뜻 |
|---|---|
| `bbox` | **본인 차량 영역.** 사용자가 그린 사각형. 원본 해상도 기준 픽셀. 2단계 룰이 쓰는 값 |

- **본인 차량은 추적하지 않는다.** 주차된 차라 영상 내내 자리가 같으므로 고정된 영역으로 다룬다. 2단계 룰은 "다른 트랙이 이 영역 근처에 왔는가"를 본다. 그래서 `track_id`를 이어 붙일 필요가 없다. (D-29)
- **확장**: 누끼를 다시 넣으면 `schema_version`을 2로 올려 아래처럼 키를 더한다. **`bbox`의 뜻("본인 차량 영역")은 바꾸지 않으므로** 룰과 `sides` 계산(D-34)은 고치지 않는다. 절차는 [11장 D-36 "확장 방법"](11-decisions.md#d-36-우선-누끼-없이-드래그한-차량-사각형을-그대로-본인-차량-영역으로-쓴다).
  ```json
  {"drag_bbox": [800, 430, 970, 630], "det_id": 1, "bbox": [810, 440, 960, 620], "matched": true}
  ```

### damage_inputs

파손 부위 입력. 작업 1건당 1행이다. (D-25)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `analysis_job_id` | bigint FK → analysis_jobs, UNIQUE | |
| `schema_version` | integer | |
| `payload` | jsonb | 입력 내용 |
| `created_at`, `updated_at` | timestamptz | |

드래그한 본인 차량 위에서 **파손 부위를 한 번 더 드래그해** 지정한다. 차량 선택과 파손 부위는 **한 요청으로 함께 저장한다** (D-29, D-36). 두 행을 한 트랜잭션에서 쓴다.

```json
{
  "damage_bbox": [940, 470, 1000, 610]
}
```

| 키 | 뜻 |
|---|---|
| `damage_bbox` | 사용자가 그린 파손 부위. 원본 해상도 기준 픽셀 |

- 파손 부위가 차량의 어느 쪽인지(`sides`: `left`·`right`·`top`·`bottom`의 배열)는 **저장하지 않는다.** 2단계를 시작할 때 GPU 워커가 `damage_bbox`와 `vehicle_selections.payload.bbox`를 비교해 계산한다. 룰이 "파손 부위 쪽 인접 공간"(PRD 3.3)을 정할 때 쓴다. (D-34)
  - 저장하면 사용자가 차량 선택만 다시 했을 때 옛 차량 기준의 값이 남는다. 두 사각형이 서로 다른 테이블에 있어 한쪽만 고쳐질 수 있기 때문이다.
- 자유 드로잉(폴리곤)이 아니라 **사각형 하나**로 받는다. 정지 장면에는 파손이 보이지 않아 사용자가 기억으로 대략 찍는 입력이고, 룰의 근접 판정 폭에 외곽 몇 px 차이는 묻히기 때문이다. 근거와 바꿀 신호는 [11장 D-29](11-decisions.md#d-29-본인-차량과-파손-부위는-정지-장면-위에서-두-번-드래그해-입력한다).
- ⚠️ **룰이 실제로 무엇을 입력으로 받을지는 여전히 U-13(팀장, 06장)이다.** 근접 판정 폭, 인접 영역을 어디까지로 볼지가 정해지면 `schema_version`을 올려 필요한 값을 더한다. (D-25)
- ⚠️ **값 검증은 DB가 해 주지 않는다.** 백엔드(Pydantic)가 `schema_version`별로 검증한다. 검증 규칙은 [05장 5.7](05-api.md#57-차량파손-부위-입력-저장-api)에 있다. (D-25)

### candidates

룰이 판정한 근접 순간 하나. 2단계에서 GPU 워커가 만든다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `analysis_job_id` | bigint FK → analysis_jobs | |
| `judged_at_sec` | double precision | 판정 시점(원본 시간). 불변 조건 7 |
| `rule_name` | text | 어느 룰이 잡았는지. 목록은 🚧 (U-13) |
| `track_ref` | text | 근거가 된 트랙. `{청크 번호}:{track_id}` 형식 (4.8) |
| `vlm_score` | integer | 0~100. VLM 호출 전에는 비어 있다 |
| `rank` | integer | 점수순 정렬 결과. 1부터 |
| `batch_no` | integer | 몇 번째 묶음인지. 1부터 |
| `verdict` | text | `unseen`(아직 안 봄) · `not_found`(못 찾음). "찾음"은 여기에 적지 않는다 (D-35) |
| `verdict_at` | timestamptz | 사용자가 [다음]을 눌러 그 묶음을 "못 찾음"으로 넘긴 시각. 같은 묶음은 모두 같은 값이다 (D-37) |
| `created_at` | timestamptz | |

- **VLM은 후보를 지우지 않는다.** 점수를 매기기 전후로 행 수가 같다. (불변 조건 4)
- 후보는 **판정 시점 하나만** 저장한다. 사건 지점(= `judged_at_sec + 5초`)은 01장 1.6의 상수로 계산한다. 클립 구간은 클립을 만들 때 계산해 `candidate_clips`에만 저장한다. (D-33)
  - ⚠️ 연속된 판정을 하나로 합치는 규칙(U-13, 팀장)에 따라 후보가 "구간"을 가져야 하면, 그때 후보 구간 칼럼을 더한다.
- "못 찾음"은 후보마다 따로 받지 않는다. 사용자가 묶음 아래 [다음]을 누르면 그 묶음 후보 전부를 한 번에 `not_found`로 바꾼다. (D-37)
- 판단(`verdict`)은 클립이 아니라 후보에 붙인다. 클립은 다시 만들 수 있지만 사용자의 판단은 후보 하나에 대한 것이기 때문이다.
- **"찾음"은 `pinned_incidents` 한 곳에만 기록한다.** "찾음"은 작업당 한 번뿐이고 그 뒤로 작업은 끝 상태(`pinned`)라, 후보마다 "찾음" 칸을 둘 필요가 없다. 두 곳에 적으면 서로 어긋날 수 있다. 찾음을 고른 후보의 `verdict`는 `unseen`으로 남는다. (D-35)

### candidate_clips

후보의 마스킹본 클립. 후보 1건에 클립 1개가 원칙이지만, 다시 만들면 행이 늘어날 수 있어 1:N으로 둔다. 다시 만든 클립은 **새 행, 새 키**로 저장하고 이전 파일을 덮어쓰지 않는다. 고정된 클립이 나중에 바뀌지 않게 하기 위해서다. (D-32)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `candidate_id` | bigint FK → candidates | 몇 번째 묶음인지는 이 후보의 `batch_no`로 본다 (D-33) |
| `start_sec`, `end_sec` | double precision | 원본 시간 기준 구간. 판정 시점 −10초 ~ +20초를 영상 경계에서 잘라낸 값 (4.7). 불변 조건 7 |
| `masked_s3_key` | text | 마스킹본 버킷 키 (4.9) |
| `status` | text | `pending` · `running` · `done` · `failed` |
| `created_at` | timestamptz | 묶음별 소요 시간은 이 값으로 본다 |

- **클립 생성에 실패하면(`failed`) 그 후보는 이번 묶음에서 빠진다.** 05장 12번이 `done`인 클립만 목록에 넣기 때문이다. 워커는 다시 만들지 않고, `verdict`도 건드리지 않는다. 드문 경우라 받아들인다 (D-51).
- 사용자에게 주는 재생 URL은 이 행의 `masked_s3_key`로만 발급한다. 고정한 사건 지점도 이 행을 가리키므로 같은 키로 재생한다. (불변 조건 1, D-32)

### pinned_incidents

사용자가 "찾음"을 고른 사건 지점. 작업 1건당 1행이다. (PRD 3.6)

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `analysis_job_id` | bigint FK → analysis_jobs, UNIQUE | |
| `candidate_clip_id` | bigint FK → candidate_clips | 고정한 클립 |
| `pinned_at` | timestamptz | |

- **고정은 파일을 복사하지 않는다. 고정한 클립 행을 가리키기만 한다.** (D-32) 재생 URL은 그 클립의 `masked_s3_key`로, 경찰에게 넘길 원본 기준 시작·끝은 그 클립의 `start_sec`·`end_sec`로 얻는다.

  ```sql
  SELECT c.start_sec, c.end_sec, c.masked_s3_key
    FROM pinned_incidents p
    JOIN candidate_clips c ON c.id = p.candidate_clip_id
   WHERE p.analysis_job_id = 42;
  ```

- 어느 후보인지는 `candidate_clips.candidate_id`로 따라간다. `candidate_id`를 따로 두지 않는다. 두 FK를 함께 두면 서로 다른 후보를 가리키는 어긋남이 생길 수 있기 때문이다.
- 고정할 때 백엔드는 **그 클립이 요청한 작업의 클립인지, `status`가 `done`인지** 확인한다. FK는 클립이 있는지만 볼 뿐 어느 작업의 것인지는 보지 않는다. 확인하지 않으면 다른 사용자의 클립 번호로 고정해 그 재생 URL을 받을 수 있다. (D-35)

  ```sql
  SELECT 1
    FROM candidate_clips c
    JOIN candidates d ON d.id = c.candidate_id
   WHERE c.id = :clip_id AND d.analysis_job_id = :job_id AND c.status = 'done';
  ```

- **전이 9(`ready` → `pinned`, "찾음")는 한 트랜잭션으로 쓴다.** 상태를 조건부로 바꾸고, 바뀐 행이 없으면(이미 고정됨) 되돌린다. 중간에 실패하면 둘 다 취소되므로 "상태는 `pinned`인데 고정 행이 없는" 경우가 생기지 않는다. (D-35)

  ```sql
  BEGIN;
  UPDATE analysis_jobs SET status = 'pinned', updated_at = now()
   WHERE id = :job_id AND status = 'ready';        -- 0행이면 ROLLBACK
  -- 위의 클립 확인. 없으면 ROLLBACK
  INSERT INTO pinned_incidents (analysis_job_id, candidate_clip_id) VALUES (:job_id, :clip_id);
  COMMIT;
  ```
- `candidate_clip_id` FK에는 CASCADE를 걸지 않는다. 그래서 고정된 클립 행만 따로 지우려 하면 DB가 거부한다. 분석 작업째 지울 때는 두 행이 함께 지워진다.
- **고정 해제는 두지 않는다.** `pinned`는 끝 상태이고, 실수는 고정 전 확인창이 막는다. (D-40)
  - **확장**: 해제가 필요해지면 이 행을 지우고 상태를 `pinned` → `ready`로 되돌리는 전이를 한 트랜잭션으로 더한다. S3에서 지울 파일은 없다. 절차는 [11장 D-40](11-decisions.md#d-40-사건-지점-고정은-해제하지-않는다-고정-전-확인으로-실수를-막는다).

### access_logs

개인영상정보에 닿는 요청을 한 행씩 남긴다. **법정 기록이다** (D-53). 화면에 보여주는 표가 아니라 감사·발표용 근거다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `id` | bigserial PK | |
| `user_id` | bigint FK → users, NULL 허용 | 누가. 시스템이 남기는 `delete_raw`·`delete_masked`는 비어 있다 |
| `video_id` | bigint FK → videos, NULL 허용 | 어느 영상. `login`·`issue_upload_link`는 비어 있다 |
| `action` | text | 무엇을 했나. 값 목록은 아래 |
| `requested_ip` | inet | 어디서. 고시 제8조의 접속지 정보 |
| `created_at` | timestamptz | 언제 |

**`action` 값**

| 값 | 남기는 지점 (05장) | 법적 성격 |
|---|---|---|
| `login` | 로그인 성공 (5.3) | 열람 요구자 특정 (표준지침 제44조⑤) |
| `issue_upload_link` | 업로드 링크 발급 (5.4) | 수집 경로 기록 |
| `view_still` | 정지 장면 조회 (5.6) | **열람** |
| `view_clip` | 후보 클립 재생 URL 발급 (5.8) | **열람** |
| `pin_incident` | 사건 지점 고정 (5.9) | 이용 기록 (표준지침 제42조) |
| `delete_raw` | 원본 파기 주기 작업 (D-52) | 파기 기록 (표준지침 제42조) |
| `delete_masked` | 마스킹본·분석 결과 파기 주기 작업 (D-57) | 파기 기록 (표준지침 제42조) |

- **재생 URL을 발급할 때마다 한 행씩 남는다.** 같은 클립을 다시 보면 행이 또 생긴다. 재생 URL은 조회할 때마다 새로 발급하므로(D-41) 발급 = 열람으로 본다.
- `action` 값도 `status`처럼 **코드 enum으로 관리하고 DB CHECK를 걸지 않는다** (D-27과 같은 이유).
- **지우지 않는다.** 고시 제8조①이 접속기록을 1년 이상 보관하라고 하는데, 정리 작업을 두지 않으면 그대로 충족된다. 데모 규모에서 행이 쌓여도 문제가 없다.
- `videos → users` FK와 같은 이유로 **CASCADE를 걸지 않는다.** 사용자나 영상을 지웠다고 법정 기록이 사라지면 안 된다. 그래서 두 FK 모두 NULL을 허용하고, `ON DELETE SET NULL`로 둔다.
- 인덱스는 `(video_id, created_at DESC)`를 둔다. "이 영상에 누가 언제 닿았나"가 유일한 조회 방식이다.

## 4.3 분석 상태와 전이 규칙

`analysis_jobs.status`가 가지는 값이다. **코드에는 아래 영문 코드를 쓰고, 화면 문구는 07장에서 정한다** (문구 🚧 U-15). 값 목록은 코드의 상수(enum)로 두고 DB 테이블로 빼지 않는다.

| 코드 | 뜻 | 사용자 입력 | 끝 상태 |
|---|---|---|---|
| `queued` | SQS에 1단계 작업이 들어갔고 워커가 아직 잡지 않았다. 화면에 "앞에 N건"을 함께 보여준다 (4.5) | 불가 | |
| `stills_running` | 워커가 1단계를 시작해 정지 장면을 비식별화하는 중 | 불가 | |
| `stage1_running` | 정지 장면이 준비됐고 청크별 객체탐지·추적이 진행 중 | **가능** | |
| `stage1_input_done` | 입력이 끝났고 1단계가 아직 진행 중. 1단계가 끝나면 2단계가 자동으로 시작된다 | 수정 가능 | |
| `stage1_done` | 1단계가 끝났고 입력을 기다린다 | **가능** | |
| `stage2_running` | 룰·VLM·후보 클립 비식별화 진행 중 | 불가 | |
| `ready` | 후보 묶음이 준비됐다. 사용자가 확인할 수 있다 | | |
| `batch_running` | "못 찾음" 뒤 다음 묶음을 만드는 중 | | |
| `pinned` | 사건 지점을 고정했다 | | ✅ |
| `exhausted` | 모든 후보를 "못 찾음"으로 확인했다. 사건이 없다는 뜻이 아니다 (PRD 3.6) | | ✅ |
| `failed` | 워커가 되풀이해도 소용없는 오류를 만났다. `error_message`에 오류가 있다 (D-43) | | ✅ |

- 화면이 보는 상태는 이 목록에 **`uploading`·`upload_failed` 두 개가 더 있다.** 업로드가 끝나지 않아 아직 작업 행이 없는 영상을 위해 조회 API가 만들어 주는 값이고, DB에는 없다 (D-47, 05장 5.5).
- **`stage1_done`은 `status`만으로 입력 가능 여부가 갈리지 않는다.** 입력을 기다리는 중일 수도 있고, 입력을 받아 2단계 작업을 넣어 둔 중일 수도 있다(전이 7에서 상태를 바꾸는 쪽은 워커다). 그래서 상태 조회 API가 `input_completed_at`이 차 있는지를 `input_done`으로 함께 돌려준다. 저장하는 칼럼이 아니라 조회할 때 계산하는 값이다 (D-49, 05장 5.5·5.7).
- 초안 목록보다 `stills_running`·`stage1_done`·`batch_running` 3개가 늘었다. 화면이 `status` 하나만 보고 "지금 입력할 수 있는지"를 판단할 수 있게 하기 위해서다. 정지 장면이 준비되기 전에는 입력 화면을 열 수 없다. (D-15)

**전이 표**

| # | 이전 → 다음 | 언제 | 누가 | 함께 바꾸는 것 |
|---|---|---|---|---|
| 1 | (행 생성) → `queued` | 업로드 완료 알림을 받고 1단계 작업을 SQS에 넣을 때 | 백엔드 | `created_at` |
| 2 | `queued` → `stills_running` | 워커가 1단계 메시지를 꺼냈을 때 | 워커 | `stage1_started_at` |
| 3 | `stills_running` → `stage1_running` | 정지 장면 비식별화가 끝났을 때 | 워커 | `still_frames` 행 생성 (1행) |
| 4 | `stage1_running` → `stage1_input_done` | 사용자가 차량·파손 부위 입력을 저장했을 때 | 백엔드 | `input_completed_at` |
| 5 | `stage1_running` → `stage1_done` | 모든 청크가 `done`인데 입력이 없을 때 | 워커 | `stage1_ended_at` |
| 6 | `stage1_input_done` → `stage2_running` | 모든 청크가 `done`이고 입력이 있을 때. 워커가 이어서 2단계를 실행한다 | 워커 | `stage1_ended_at`, `stage2_started_at` |
| 7 | `stage1_done` → `stage2_running` | 입력이 들어와 백엔드가 2단계 작업을 SQS에 넣고, 워커가 그 메시지를 꺼냈을 때 | 워커 | `input_completed_at`(백엔드), `stage2_started_at` |
| 8 | `stage2_running` → `ready` | 첫 묶음 후보 클립이 모두 만들어졌을 때 | 워커 | `stage2_ended_at` |
| 9 | `ready` → `pinned` | 사용자가 "찾음"을 골랐을 때 | 백엔드 | `pinned_incidents` 행 생성. 상태 변경과 **한 트랜잭션** (D-35) |
| 10 | `ready` → `batch_running` | 사용자가 [다음]을 눌렀고(묶음 전체 "못 찾음", D-37) 남은 후보가 있을 때 | 백엔드→워커 | 백엔드가 `next_batch` 작업을 SQS에 넣는다 |
| 11 | `batch_running` → `ready` | 다음 묶음 클립이 만들어졌을 때 | 워커 | |
| 12 | `ready` → `exhausted` | 사용자가 [다음]을 눌렀고(묶음 전체 "못 찾음", D-37) 남은 후보가 없을 때 | 백엔드 | |
| 14 | `stage2_running` → `exhausted` | 2단계가 끝났는데 룰이 후보를 하나도 만들지 못했을 때 (후보 0건) | 워커 | `stage2_ended_at`. 클립을 만들 것이 없으므로 `ready`를 거치지 않는다 (D-50) |
| 13 | 어떤 상태 → `failed` | 1단계 시작 직후 워커가 읽을 수 없는 코덱을 발견했을 때(다시 해도 같으므로 바로, D-43 ⚠️ 팀장 확인). 그 밖에 워커가 되풀이해도 소용없는 오류를 만났을 때 | 워커 | `error_message`. 어떤 오류를 이렇게 볼지는 🚧 (06장) |

- 7번에서 백엔드는 상태를 바꾸지 않는다. 입력을 저장하고 SQS에만 넣는다. 상태를 바꾸는 쪽을 워커 하나로 모아야 4.4의 중복 방지가 한 곳에서 걸린다.
- **`exhausted`에 이르는 길은 둘이다.** 사용자가 [다음]으로 후보를 전부 넘긴 경우(전이 12)와, 후보가 애초에 0건인 경우(전이 14)다. 화면 문구가 달라야 하므로 상태 조회 API가 `candidate_total`을 함께 돌려준다 (D-50, 05장 5.5). 09장 KPI 집계도 이 둘을 구분해서 센다.
- 끝 상태(`pinned`, `exhausted`, `failed`)에서는 더 전이하지 않는다. 다시 분석하려면 새 작업을 만든다. (재분석 기능은 Non-Scope)
- **끝 상태에 이르면 원본 영상이 파기 대상이 된다.** 상태 전이가 아니라 백엔드 주기 작업이 하루 1회 찾아서 지우고 `videos.raw_deleted_at`을 찍는다. 끝 상태에 이르지 못해도 `last_activity_at`에서 3일이 지나면 같이 지운다. (D-52)

## 4.4 두 번 실행되지 않게 하는 방법

SQS 표준 대기열은 드물게 같은 메시지를 두 번 전달한다. 워커가 처리 중에 죽으면 같은 작업이 다시 전달되기도 한다. (D-16) 또 2단계는 "1단계 완료"와 "입력 완료" 두 경로에서 시작될 수 있어(전이 6·7) 두 번 시작될 위험이 있다.

**해결: 상태를 조건부로 바꾼다.** 상태를 바꾸는 UPDATE에 "지금 상태가 X일 때만"을 붙이고, **바뀐 행 수가 0이면 이미 다른 쪽이 처리한 것이므로 그냥 끝낸다.**

```sql
-- 2단계 시작 (전이 6·7). 워커가 2단계를 시작하기 직전에 실행한다
UPDATE analysis_jobs
   SET status = 'stage2_running',
       stage2_started_at = now(),
       updated_at = now()
 WHERE id = :job_id
   AND status IN ('stage1_input_done', 'stage1_done');
```

- 바뀐 행 수가 **1이면** 이 워커가 2단계를 맡는다.
- 바뀐 행 수가 **0이면** 이미 다른 워커(또는 같은 메시지의 이전 전달)가 시작한 것이다. 아무것도 하지 않고 `DeleteMessage`로 메시지를 지운다.
- **0행이면 이유를 가리지 않고 지운다.** 행 자체가 없는 경우(백엔드가 SQS에 넣고 커밋하기 전이거나, 커밋이 실패한 경우)도 마찬가지다. 그 때문에 작업이 대기 상태에 멈추면 백엔드가 임계 시간 뒤 SQS에 다시 넣는다 (D-56 ⚠️ 팀장 확인).
- PostgreSQL에서 UPDATE는 해당 행에 잠금을 건다. 두 워커가 동시에 실행해도 한쪽만 1을 받는다.

같은 방법을 1단계 시작(전이 2, `WHERE status = 'queued'`)과 다음 묶음(전이 11)에도 쓴다. **상태를 바꾸는 모든 UPDATE에는 `WHERE status = ...`를 반드시 붙인다.** 이것이 D-16 "반드시 지킬 것" 2번(멱등성)을 구현하는 방법이다.

- 청크 단위에도 같은 규칙을 쓴다: `UPDATE chunks SET status='running' ... WHERE status='pending'`.
- 1단계가 중간부터 다시 시작되면 이미 `done`인 청크는 건너뛴다. 트랙 파일이 S3에 있으므로 다시 탐지하지 않는다.

## 4.5 "대기 중 (앞에 N건)"의 N 계산

**SQS를 조회하지 않는다.** SQS는 대기 중인 메시지 수를 대략값으로만 알려주고, "내 앞에 몇 개"는 알려주지 않는다. DB에서 센다. (D-19 최소 조치 6번)

```sql
SELECT count(*)
  FROM analysis_jobs
 WHERE status IN ('queued', 'stills_running', 'stage1_running', 'stage1_input_done')
   AND created_at < (SELECT created_at FROM analysis_jobs WHERE id = :job_id);
```

- 뜻: **나보다 먼저 들어왔고 아직 1단계가 끝나지 않은 작업 수**다.
- 인덱스 `(status, created_at)`가 있으면 행이 많아져도 빠르다.
- 이 값은 정확한 예측이 아니라 "멈춘 게 아니라 순서를 기다리는 중"을 보여주기 위한 것이다. 화면 조회 주기는 5~10초다. 🚧 (U-18)

## 4.6 SQS 메시지 형식

메시지에는 **작업 ID와 작업 종류만** 넣는다. 나머지는 워커가 DB와 S3에서 읽는다. 메시지 크기 한도가 있고, 같은 정보를 두 곳에 두면 어긋나기 때문이다. (D-16 "반드시 지킬 것" 6번)

```json
{"job_id": 42, "kind": "stage1"}
{"job_id": 42, "kind": "stage2"}
{"job_id": 42, "kind": "next_batch"}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `job_id` | 정수 | `analysis_jobs.id` |
| `kind` | 문자열 | `stage1` · `stage2` · `next_batch` 셋 중 하나 |

- **묶음 번호는 넣지 않는다.** `next_batch`를 받은 워커가 DB에서 `max(batch_no) + 1`을 계산한다. 메시지에 넣으면 중복 전달 때 어긋난다.
- 메시지를 꺼낸 워커는 먼저 4.4의 조건부 UPDATE를 시도한다. 0행이면 아무 일도 하지 않고, 이유를 가리지 않고 메시지를 지운다 (4.4, D-56 ⚠️ 팀장 확인).
- 1단계는 수십 분이 걸리므로 처리하는 동안 `ChangeMessageVisibility`로 가시성 제한 시간을 연장한다. 연장 주기는 🚧 (U-18)

## 4.7 시간 필드 규칙

**영상 안의 시간과 벽시계 시각을 절대 섞지 않는다.** 이름으로 구분한다.

| 종류 | 이름 규칙 | 타입 | 기준 |
|---|---|---|---|
| 영상 안의 시간 | `*_sec` | double precision | **원본 영상 시작부터의 경과 초** |
| 벽시계 시각 | `*_at` | timestamptz | UTC로 저장한다 |

- 후보는 원본 시간 기준 판정 시점을, 후보 클립은 원본 시간 기준 시작·끝을 가진다. 고정된 사건 지점은 가리키는 클립의 값을 그대로 쓴다. **청크로 자르거나 클립으로 가공한 뒤에도 이 값이 유지된다.** (불변 조건 7, D-33)
  - 청크 3번이 원본 720초에서 시작하면, 그 청크의 트랙에 적히는 `t`는 0이 아니라 720.0부터다.
  - 30초짜리 클립 안의 시간(0~30초)은 DB에 저장하지 않는다. 저장하는 것은 원본 기준 `start_sec`·`end_sec`뿐이다.
- 후보 클립 구간은 `판정 시점 −10초 ~ +20초`로 계산한다. 영상 경계를 넘으면 잘라내고, 그 결과를 `candidate_clips.start_sec`·`end_sec`에 저장한다. 따라서 클립 길이가 30초보다 짧을 수 있다. (01장 1.6)

## 4.8 청크별 트랙 결과 파일 형식

**청크 하나당 JSONL 파일 하나**를 만든다. 한 줄에 JSON 객체 하나를 쓰고, 줄 하나가 "어떤 시각에 어떤 객체가 어디에 있었는지"를 나타낸다. (D-26)

```
{"t":720.0,"track_id":31,"cls":"car","bbox":[810,440,960,620],"conf":0.91}
{"t":720.0,"track_id":44,"cls":"person","bbox":[120,300,180,520],"conf":0.77}
{"t":720.2,"track_id":31,"cls":"car","bbox":[812,441,962,621],"conf":0.90}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `t` | 실수 | **원본 시간(초).** 청크로 잘라도 원본 기준이다 (4.7) |
| `track_id` | 정수 | 추적 ID. **청크 안에서만 유일하다** |
| `cls` | 문자열 | 객체 종류. `car` · `person` 등. 목록은 🚧 (U-09) |
| `bbox` | 정수 4개 | `[x1, y1, x2, y2]`, 원본 해상도 기준 픽셀 |
| `conf` | 실수 | 탐지 신뢰도 0~1 |

**규칙**

- 줄은 `t` 오름차순으로 쓴다. 같은 `t`의 객체들은 이어서 쓴다.
- `track_id`는 청크 안에서만 유일하다. 청크가 독립 단위라 청크마다 다시 1부터 시작하기 때문이다. **여러 청크에 걸쳐 트랙을 가리킬 때는 `{청크 번호}:{track_id}`로 쓴다** (예: `3:31`). `candidates.track_ref`가 이 형식이다.
- 청크 경계를 넘어가는 트랙을 하나로 이어 붙일지는 🚧 (06장). 청크 길이가 후보 구간보다 훨씬 길면 실제 문제가 되는 경우가 드물다.
- 2단계 룰은 파일을 한 줄씩 읽어 `track_id`별로 모은 뒤 좌표를 비교한다. 파일을 통째로 메모리에 올리지 않는다.
- 크기 추정: 줄당 80~120바이트로 잡으면 24시간·5fps·동시 객체 20개 기준 약 **0.7~1GB**다(추정, 실측 대상). 시연은 짧은 영상으로만 하므로 수 MB 수준이다.
- 압축(`.jsonl.gz`)은 지금 하지 않는다. 필요해지면 읽기·쓰기 함수 두 곳만 고치면 된다.

## 4.9 S3 키 구조

버킷은 비공개 3개다. 버킷 이름은 Terraform 변수 `bucket_prefix`로 받는다. (D-23)

**모든 키는 `videos/{video_id}/`로 시작한다.** 영상 1건과 관련된 파일을 지울 때 이 접두사 하나만 지우면 되기 때문이다.

### 원본 버킷 `<prefix>-raw`

```
videos/{video_id}/original.{ext}     예: original.mp4, original.avi
```

- 여기에는 **업로드용 presigned URL만** 발급한다. 재생 URL은 어떤 경우에도 발급하지 않는다. (불변 조건 1, D-23)
- **이 버킷의 객체는 오래 살지 않는다.** 백엔드 주기 작업이 끝 상태 또는 3일 무입력이면 지운다. 그 위에 S3 수명 주기 규칙으로 30일 삭제를 안전망으로 건다. (D-52, 02장 2.9)
- `ext`는 업로드한 파일의 확장자를 소문자로 바꾼 것이다. 허용 확장자는 `.mp4` `.avi` `.mkv` `.mov`이고 코덱은 H.264·H.265다 (D-43, 01장 1.6).

### 마스킹본 버킷 `<prefix>-masked`

```
videos/{video_id}/stills/{t_sec}.jpg          예: stills/0.jpg
videos/{video_id}/clips/{candidate_clip_id}.mp4   예: clips/1187.mp4
```

- `{t_sec}`는 소수점을 버린 정수 초로 쓴다. 정지 장면은 작업당 1장이라 파일도 1개다 (D-48). 키에 시점을 남겨 두면 장면을 늘리더라도 구조가 그대로다.
- 클립 키는 후보 번호가 아니라 **클립 행 번호**(`candidate_clips.id`)로 짓는다. 후보 번호로 지으면 클립을 다시 만들 때 같은 파일을 덮어써서, 이미 고정한 사건 지점의 영상이 바뀐다. (D-32)
- 사건 지점을 고정해도 파일을 따로 만들지 않는다. 고정은 `clips/`의 파일을 그대로 가리킨다. (D-32)
- 사용자에게 주는 재생 URL은 **이 버킷에서만** 발급한다.
- **이 버킷의 객체도 오래 살지 않는다.** 백엔드 주기 작업이 `upload_completed_at`에서 30일이 지난 영상의 `videos/{video_id}/` 전체를 지우고, 그 위에 S3 수명 주기 규칙 30일 삭제를 안전망으로 건다. (D-57, 02장 2.9)
- 클립은 H.264 코덱 MP4로 만든다. 브라우저 `<video>` 태그가 재생해야 하기 때문이다. (D-08)

### 분석 결과 버킷 `<prefix>-analysis`

```
videos/{video_id}/tracks/chunk_0003.jsonl
```

- **들어가는 것은 1단계 트랙 파일뿐이다** (4.8). 후보는 `candidates` 행으로 DB에, 후보 클립은 마스킹본 버킷에 있다. 차량·파손 부위 입력도 DB(`vehicle_selections`·`damage_inputs`)다.
- 청크 번호는 0을 채운 4자리로 쓴다(`chunk_0003`). 이름순 정렬이 곧 시간순이 된다.
- 이 버킷은 사용자에게 어떤 URL도 발급하지 않는다. GPU 워커만 읽고 쓴다.
- 마스킹본과 **같은 시점에 함께 지운다** (D-57).

- 키에 쓰는 `video_id`·`candidate_id`는 순차 정수라 값을 추측할 수 있다. 하지만 버킷이 모두 비공개이고 접근은 presigned URL의 서명·만료로 막으므로 문제가 되지 않는다. (D-23)

## 4.10 스키마 DDL과 인덱스

4.2의 표를 그대로 SQL로 옮긴 것이다. **표와 이 DDL이 어긋나면 표가 기준이다.** (D-27)

### 적용 방법

- 파일은 `backend/migrations/0001_init.sql`에 둔다(저장소 구조는 03장 3.3, 🚧 U-12). 마이그레이션 도구(Alembic 등)를 쓸지는 🚧 (U-03, U-12)다. 정해질 때까지는 이 파일을 `psql -f`로 한 번 실행한다.
- 시연 전까지는 스키마가 바뀌면 **DB를 지우고 다시 만든다.** 아직 지킬 데이터가 없다. 데이터를 지키며 바꾸는 방식(마이그레이션)은 U-03에서 정한다.

```sql
CREATE TABLE users (
  id            bigserial PRIMARY KEY,
  login_id      text        NOT NULL UNIQUE,
  password_hash text        NOT NULL,
  name          text        NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  id         bigserial PRIMARY KEY,
  token      text        NOT NULL UNIQUE,   -- HttpOnly 쿠키에 담기는 랜덤 문자열
  user_id    bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE upload_tokens (
  id            bigserial PRIMARY KEY,
  token         text        NOT NULL UNIQUE,   -- 링크 주소에 들어가는 랜덤 문자열
  owner_user_id bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at    timestamptz NOT NULL,
  used_at       timestamptz,                   -- 비어 있지 않으면 이미 쓴 링크
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE videos (
  id                  bigserial PRIMARY KEY,
  owner_user_id       bigint      NOT NULL REFERENCES users(id),
  upload_token_id     bigint      NOT NULL REFERENCES upload_tokens(id),  -- 영상은 링크로만 올라온다 (D-45)
  s3_key              text        NOT NULL,
  original_filename   text        NOT NULL,
  size_bytes          bigint,                  -- 업로드 URL 발급 때 채운다
  duration_sec        double precision,        -- 아래 4개는 워커가 1단계에서 채운다
  fps                 double precision,
  width               integer,
  height              integer,
  created_at          timestamptz NOT NULL DEFAULT now(),
  upload_completed_at timestamptz,             -- 비어 있으면 업로드 미완료
  last_activity_at    timestamptz NOT NULL DEFAULT now(),  -- 마지막 사용자 조작. 원본 파기 계산 (D-52)
  raw_deleted_at      timestamptz,             -- 원본을 지운 시각. 비어 있으면 원본이 있다 (D-52)
  masked_deleted_at   timestamptz              -- 마스킹본·분석 결과를 지운 시각 (D-57)
);

CREATE TABLE analysis_jobs (
  id                 bigserial PRIMARY KEY,
  video_id           bigint      NOT NULL UNIQUE REFERENCES videos(id) ON DELETE CASCADE,
  status             text        NOT NULL,     -- 값 목록은 4.3
  stage1_started_at  timestamptz,
  stage1_ended_at    timestamptz,
  stage2_started_at  timestamptz,
  stage2_ended_at    timestamptz,
  input_completed_at timestamptz,
  error_message      text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chunks (
  id              bigserial PRIMARY KEY,
  analysis_job_id bigint           NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  idx             integer          NOT NULL,
  start_sec       double precision NOT NULL,
  end_sec         double precision NOT NULL,
  status          text             NOT NULL DEFAULT 'pending',
  track_s3_key    text,                        -- 완료 후 채운다
  started_at      timestamptz,
  ended_at        timestamptz,
  UNIQUE (analysis_job_id, idx)
);

CREATE TABLE still_frames (
  id              bigserial PRIMARY KEY,
  analysis_job_id bigint           NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,   -- 작업당 1장 (D-48)
  t_sec           double precision NOT NULL,   -- 시작 장면이라 0.0
  masked_s3_key   text             NOT NULL,   -- 마스킹본만 저장한다 (불변 조건 2)
  created_at      timestamptz      NOT NULL DEFAULT now()
);

CREATE TABLE vehicle_selections (
  id              bigserial PRIMARY KEY,
  analysis_job_id bigint      NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  still_frame_id  bigint      NOT NULL REFERENCES still_frames(id),
  schema_version  integer     NOT NULL,
  payload         jsonb       NOT NULL,        -- 검증은 백엔드가 한다 (D-25)
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE damage_inputs (
  id              bigserial PRIMARY KEY,
  analysis_job_id bigint      NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  schema_version  integer     NOT NULL,
  payload         jsonb       NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE candidates (
  id              bigserial PRIMARY KEY,
  analysis_job_id bigint           NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  judged_at_sec   double precision NOT NULL,   -- 구간은 저장하지 않는다 (D-33)
  rule_name       text             NOT NULL,   -- 목록은 🚧 (U-13)
  track_ref       text             NOT NULL,   -- '{청크 번호}:{track_id}' (4.8)
  vlm_score       integer,                     -- 0~100. VLM 호출 전에는 비어 있다
  rank            integer,
  batch_no        integer,
  verdict         text             NOT NULL DEFAULT 'unseen',   -- 'unseen' | 'not_found'. 찾음은 pinned_incidents (D-35)
  verdict_at      timestamptz,
  created_at      timestamptz      NOT NULL DEFAULT now()
);

CREATE TABLE candidate_clips (
  id            bigserial PRIMARY KEY,
  candidate_id  bigint           NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,   -- 묶음 번호는 후보에서 (D-33)
  start_sec     double precision NOT NULL,
  end_sec       double precision NOT NULL,
  masked_s3_key text,                          -- 완료 후 채운다
  status        text             NOT NULL DEFAULT 'pending',
  created_at    timestamptz      NOT NULL DEFAULT now()
);

CREATE TABLE pinned_incidents (
  id                bigserial PRIMARY KEY,
  analysis_job_id   bigint      NOT NULL UNIQUE REFERENCES analysis_jobs(id) ON DELETE CASCADE,
  candidate_clip_id bigint      NOT NULL REFERENCES candidate_clips(id),   -- CASCADE 없음 (D-32)
  pinned_at         timestamptz NOT NULL DEFAULT now()
);

-- 법정 기록. 지우지 않는다 (D-53)
CREATE TABLE access_logs (
  id           bigserial PRIMARY KEY,
  user_id      bigint      REFERENCES users(id)  ON DELETE SET NULL,   -- 시스템 기록은 NULL
  video_id     bigint      REFERENCES videos(id) ON DELETE SET NULL,   -- login 등은 NULL
  action       text        NOT NULL,             -- 값 목록은 4.2, 코드 enum으로 관리 (D-27)
  requested_ip inet,
  created_at   timestamptz NOT NULL DEFAULT now()
);
```

### 인덱스

UNIQUE 제약은 인덱스를 자동으로 만든다. 아래는 그것만으로 부족한 조회에 더하는 것이다.

```sql
CREATE INDEX idx_videos_owner        ON videos (owner_user_id, created_at DESC);
CREATE INDEX idx_jobs_status_created ON analysis_jobs (status, created_at);
CREATE INDEX idx_chunks_job_status   ON chunks (analysis_job_id, status);
CREATE INDEX idx_cand_job_batch_rank ON candidates (analysis_job_id, batch_no, rank);
CREATE INDEX idx_cand_job_verdict    ON candidates (analysis_job_id, verdict);
CREATE INDEX idx_clips_candidate     ON candidate_clips (candidate_id);
CREATE INDEX idx_access_video        ON access_logs (video_id, created_at DESC);
CREATE INDEX idx_videos_raw_alive    ON videos (last_activity_at) WHERE raw_deleted_at IS NULL;
CREATE INDEX idx_videos_masked_alive ON videos (upload_completed_at) WHERE masked_deleted_at IS NULL;
```

| 인덱스 | 어떤 조회에 쓰나 |
|---|---|
| `videos (owner_user_id, created_at DESC)` | 사용자의 영상 목록을 최근순으로 보여줄 때 |
| `analysis_jobs (status, created_at)` | 4.5의 "앞에 N건" 계산 |
| `chunks (analysis_job_id, status)` | 1단계 종료 판정("모든 청크가 `done`인가") |
| `candidates (analysis_job_id, batch_no, rank)` | 묶음 하나를 점수순으로 꺼낼 때 |
| `candidates (analysis_job_id, verdict)` | 전이 10·12의 "남은 후보가 있는가" |
| `candidate_clips (candidate_id)` | 후보의 클립을 찾을 때 |
| `access_logs (video_id, created_at DESC)` | "이 영상에 누가 언제 닿았나" (D-53) |
| `videos (last_activity_at) WHERE raw_deleted_at IS NULL` | 원본 파기 주기 작업이 "지울 것"을 찾을 때. 부분 인덱스라 이미 지운 영상은 아예 들어오지 않는다 (D-52) |
| `videos (upload_completed_at) WHERE masked_deleted_at IS NULL` | 같은 주기 작업이 마스킹본 파기 대상을 찾을 때 (D-57) |

- 데모 규모(영상 수십 건)에서는 인덱스가 없어도 느리지 않다. **부하 테스트(09장)에서 행을 많이 넣고 재는 것이 이 인덱스들의 목적이다.**
- `still_frames`·`vehicle_selections`·`damage_inputs`·`pinned_incidents`는 UNIQUE 제약이 만드는 인덱스로 충분하다. 모두 `analysis_job_id`로만 찾기 때문이다.
- `sessions`와 `upload_tokens`도 마찬가지다. 찾는 방법이 `token` 하나뿐이고 여기에 UNIQUE가 걸려 있다. 요청마다 도는 조회라 인덱스가 꼭 필요한데, UNIQUE가 이미 만들어 준다.

### DDL에서 정한 것 (D-27)

| 항목 | 정한 것 | 이유 |
|---|---|---|
| `status`에 CHECK 제약 | **걸지 않는다.** 값 목록은 백엔드·워커 코드의 enum으로만 관리한다 | 상태 목록(4.3)이 아직 바뀔 수 있다(D-24는 "확정 필요"). CHECK를 걸면 값 하나를 더할 때마다 DB를 고쳐야 한다. 상태를 쓰는 곳이 백엔드와 워커 둘뿐이라 코드에서 막아도 충분하다 |
| `analysis_jobs` 아래 테이블의 FK | 모두 `ON DELETE CASCADE` | 영상 1건을 지울 때 관련 행이 함께 지워진다. S3에서 `videos/{video_id}/` 접두사 하나만 지우면 되는 것(4.9)과 짝이 맞는다 |
| `videos → users` FK | CASCADE를 걸지 **않는다**(기본 동작) | 사용자를 지웠다고 영상과 분석 결과가 사라지면 안 된다. 참조가 남아 있으면 삭제가 거부된다 |
| `upload_tokens → users`, `sessions → users` FK | CASCADE를 건다 | 링크와 세션은 짧게 살고 만료되는 임시 값이라 계정과 함께 사라져도 된다 (D-30) |
| `pinned_incidents → candidate_clips` FK | CASCADE를 걸지 **않는다** | 고정한 클립 행만 따로 지워지면 사건 지점이 사라진다. 분석 작업째 지울 때는 위의 CASCADE로 함께 지워진다 (D-32) |
| `access_logs`의 FK 2개 | `ON DELETE SET NULL` | 법정 기록이라 사용자나 영상이 지워져도 행이 남아야 한다. CASCADE면 함께 지워지고, 기본 동작(RESTRICT)이면 영상을 못 지운다. 둘 다 곤란해서 SET NULL을 쓴다 (D-53) |
| `videos → upload_tokens` FK | CASCADE를 걸지 **않는다**(기본 동작) | 영상은 링크로만 올라오므로(D-45) 영상이 가리키는 링크 행은 지울 수 없어야 한다. 만료 링크 정리 작업을 만들면 쓰지 않은 링크(`used_at IS NULL`)만 지운다 |
| `updated_at` 갱신 | 트리거를 쓰지 않고 **UPDATE 문에 직접 쓴다** | 상태를 바꾸는 UPDATE는 4.4처럼 `WHERE status = ...`가 붙은 조건부 문장이다. 같은 문장에서 함께 쓰는 편이 읽기 쉽고, 트리거가 숨어서 도는 것보다 추적하기 낫다 |
| `NOT NULL` 기준 | 행을 만드는 시점에 값을 알 수 있으면 `NOT NULL`, 나중에 채우면 NULL 허용 | `videos.duration_sec`처럼 워커가 나중에 채우는 칼럼은 NULL이어야 한다. 주석으로 "완료 후 채운다"를 적어 둔다 |
| 금액·좌표 타입 | 좌표·시간은 `double precision`, 픽셀 bbox는 JSONB 안의 정수 배열 | 4.2·4.8의 표와 같다. 소수 오차가 문제 되는 계산(금액 등)은 이 프로젝트에 없다 |

## 4.11 이 장에서 미정으로 남는 것

| 항목 | 어디서 정하나 |
|---|---|
| 비밀번호 해시 방식, 쿠키 속성(`SameSite` 등) | 08장 — 세션 저장 방식은 D-30(확정)으로 정했다 |
| 업로드 링크 발급 화면·유효 시간 확정, 만료 안내 문구 | 08장, 07장 (D-28) |
| 드래그와 탐지를 맞추는 기준(겹침 비율 등), 누끼를 다각형으로 딸지 사각형만 쓸지 | 누끼를 우선 빼서(D-36) 지금은 정하지 않는다. 다시 넣을 때 06장 (U-13, U-09) |
| 룰이 실제로 받는 파손 부위 값(근접 판정 폭, 인접 영역) | 06장 (U-13) → 정해지면 `schema_version`만 올린다 |
| `payload` 검증 규칙 | **해결** → [05장 5.7](05-api.md#57-차량파손-부위-입력-저장-api) (`schema_version` 1의 규칙 6가지) |
| 청크 길이, 샘플링 fps | U-06, 실측 후 |
| 상태별 화면 문구 | 07장 (U-15) |
| 청크 경계를 넘는 트랙 이어 붙이기 | 06장 |
| 워커가 어떤 오류를 `failed`로 볼지 (전이 13) | 06장 (D-43) |
| 마이그레이션 도구(Alembic 등), `0001_init.sql`을 둘 위치 | 03장, 10장 (U-03, U-12) |
| 마스킹본·분석 결과의 보관 기간과 파기 방법 | **해결** → D-57 (업로드 완료 30일 뒤 파기, `masked_deleted_at`). 확정 |
| `status`에 CHECK 제약을 더할지 | D-24가 확정되고 상태 목록이 굳은 뒤 (D-27) |

## 관련 결정·조건

- 상태 구조는 `analysis_jobs` 한 행 + 시각 칼럼: D-24
- 입력값은 JSONB + `schema_version`: D-25
- 트랙 파일은 청크당 JSONL: D-26
- DDL 규칙(status에 CHECK를 걸지 않음, FK CASCADE 범위): D-27
- 관리자는 계정 없이 업로드 전용 일회용 링크로 올린다: D-28 (U-14 해결)
- 차량·파손 부위는 두 번 드래그로 입력하고 본인 차량은 추적하지 않는다: D-29 (U-13 일부 해결)
- 로그인 세션은 DB 테이블 + HttpOnly 쿠키: D-30
- 사건 지점 고정은 파일 복사 없이 클립 행 참조: D-32
- 후보는 판정 시점만, 구간·묶음 번호는 한 곳에만: D-33
- 파손 부위 방향(`sides`)은 저장하지 않고 워커가 계산: D-34
- "찾음"은 `pinned_incidents` 한 곳에만, 전이 9는 한 트랜잭션: D-35
- 우선 누끼 없이 드래그한 차량 사각형을 그대로 씀, 차량·파손 부위는 한 번에 저장: D-36
- 후보마다 [찾음]만, 묶음 단위 [다음]이 "못 찾음": D-37
- 고정 해제 없음, `pinned`는 끝 상태: D-40
- 원본 키 확장자, 코덱 불량 시 재시도 없이 `failed`: D-43 (코덱 검사는 팀장 확인)
- 영상은 업로드 링크로만 올라온다, `upload_token_id` NOT NULL: D-45
- SQS에 넣고 나서 커밋, 작업 행이 없는 메시지는 지우지 않음(4.4): D-46
- 입력 수정은 1단계가 끝나기 전까지, 상태 조회에 `input_done`: D-49
- 후보 0건이면 `exhausted`로 보내고 `candidate_total`로 구분: D-50
- 클립 생성에 실패한 후보는 이번 묶음에서 빠지고, 다시 만들지 않는다: D-51
- 원본은 끝 상태 또는 3일 무입력이면 파기, `raw_deleted_at`: D-52
- 열람·발급·파기 기록을 `access_logs`에 남긴다: D-53
- 마스킹본·분석 결과는 업로드 완료 30일 뒤 파기, `masked_deleted_at`: D-57 (U-24 해결)
- 두 단계 분석과 상태 표시: D-05, [02장 2.5](02-architecture.md#25-처리-흐름-두-단계-분석)
- DB는 백엔드 EC2의 PostgreSQL: D-17
- 작업 전달은 SQS, 상태는 DB: D-16
- 1단계 중 입력 허용, 2단계 자동 시작: D-15
- 대기 순서 표시, 무상태 API: D-19
- 불변 조건 1·7: [02장 2.4](02-architecture.md#24-이중-경로와-불변-조건)
- S3 사용: D-09. 영역은 비공개 버킷 3개로 분리: D-23
- 청크 독립 단위의 입력·출력: [02장 2.6](02-architecture.md#26-청크-분할과-병렬-처리)
