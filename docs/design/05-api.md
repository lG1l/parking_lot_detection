# 05. API 명세

> 마지막 수정: 2026-09-22
> 표시: 🚧 미정 · ⚠️ 확인 필요 · 🔐 멘토 승인 필요
>
> 5.2의 엔드포인트 15개를 모두 썼다. 근거가 되는 결정 중 **D-28·D-29·D-30·D-31·D-32·D-35·D-37·D-38·D-39·D-40·D-41·D-42·D-44·D-45·D-46·D-47·D-48·D-49·D-51·D-52·D-53·D-57은 확정**이고, 나머지(D-25·D-34·D-36·D-43·D-50·D-56)는 상태가 아직 **"확정 필요"** 다. 이 장을 전제로 백엔드·프론트 구현을 시작해도 되지만, 확정되지 않은 것은 뒤집힐 수 있다는 것을 알고 진행한다. 남은 항목은 [5.10](#510-이-장에서-미정으로-남는-것)에 모아 두었다.

## 5.1 공통 규칙

**주소**

- 모든 API는 `/api/`로 시작한다. 프론트와 같은 출처라 프론트는 상대경로로 부른다. (D-11)
- 업로드 이후의 API는 `/api/videos/{video_id}/...` 모양이다. 프론트는 `video_id` 하나만 안다. `job_id`(`analysis_jobs.id`)는 SQS·워커 안에서만 쓴다. (D-39)

**인증**

| 대상 | 방법 | 실패 |
|---|---|---|
| 업로드 링크로 부르는 API (5.2의 5·6·7번: 링크 확인, 업로드 URL 발급, 업로드 완료 알림) | 링크의 `token`. 쿠키를 보지 않는다 (D-28) | 엔드포인트별 코드 (5.4) |
| 그 밖의 모든 API | 세션 쿠키 (D-30) | 401 `UNAUTHENTICATED` |

- `/api/videos/{video_id}/...`는 요청마다 `videos.owner_user_id`가 로그인한 사용자인지 확인한다. 남의 영상이면 없는 영상과 똑같이 404 `VIDEO_NOT_FOUND`를 돌려준다. `video_id`는 순서대로 매기는 번호라 추측할 수 있기 때문이다. (D-39)

**요청·응답 값**

- 요청과 성공 응답 본문은 JSON 객체 그대로다. `{"data": ...}` 같은 감싸기는 하지 않는다.
- 원본 시간은 영상 시작부터의 초(`double`)다. 이름은 `_sec`로 끝난다. (04장 4.7)
- 좌표는 원본 해상도 기준 픽셀 정수 배열 `[x1, y1, x2, y2]`다. (04장)
- 시각은 시간대가 붙은 ISO 8601 문자열이다. 예: `"2026-09-18T14:03:00+09:00"`

**에러 응답** (D-38)

실패하면 HTTP 상태 번호와 함께 항상 아래 모양을 돌려준다.

```json
{"error": {"code": "VIDEO_NOT_FOUND", "message": "video 17 not found"}}
```

| 키 | 뜻 |
|---|---|
| `code` | 대문자 스네이크 표기의 영문 코드. **프론트는 이 값으로만 경우를 나눈다.** 한 번 정한 코드는 바꾸지 않는다 |
| `message` | 개발자용 영문 설명. 언제든 바뀔 수 있으며 프론트는 비교하지 않는다 |

- 사용자에게 보여줄 한국어 문구는 07장(U-15)에서 `code`별로 정한다.
- FastAPI의 `HTTPException`과 입력 검증 실패(`RequestValidationError`)도 예외 처리기에서 이 모양으로 바꾼다.

공통 코드:

| HTTP | `code` | 언제 | 프론트 처리 |
|---|---|---|---|
| 401 | `UNAUTHENTICATED` | 세션 쿠키가 없거나 만료됨 | 로그인 화면으로 |
| 404 | `VIDEO_NOT_FOUND` | 영상이 없거나 남의 영상 | 목록으로 |
| 409 | `INVALID_STATE` | 지금 분석 상태(04장 4.3)에서는 할 수 없는 요청. `message`에 현재 상태를 적는다 | 상태를 다시 조회해 화면을 새로 그린다 |
| 422 | `VALIDATION_FAILED` | 요청 값이 규칙에 어긋남. `message`에 어느 값인지 적는다 | 입력을 다시 받는다 |
| 500 | `INTERNAL_ERROR` | 서버 오류 | 잠시 후 다시 시도 안내 |

- 화면이 따로 안내해야 하는 경우는 엔드포인트별 코드를 더한다. 예: 업로드 링크의 `UPLOAD_TOKEN_EXPIRED`, `UPLOAD_TOKEN_USED`, 파일 형식의 `UNSUPPORTED_FILE_TYPE`·`FILE_TOO_LARGE`, 로그인의 `LOGIN_FAILED`. 업로드 링크 코드는 5.4에 모아 두었다. 원본 파기 뒤 [다음]을 막는 `RAW_EXPIRED`(13번, D-52)와 마스킹본 파기 뒤 열람을 막는 `MASKED_EXPIRED`(10·12·15번, D-57)도 여기에 속한다.
- 409는 되도록 `INVALID_STATE` 하나로 둔다. 대부분 상태가 이미 바뀐 경우라, 프론트는 다시 조회하기만 하면 맞는 화면이 나온다.

**presigned URL** (D-41)

| 용도 | 유효 시간 | 발급 시점 | 만료되면 |
|---|---|---|---|
| 업로드용 (원본 버킷 PUT) | 01장 1.6 (15분) | 업로드 URL 발급 API. 관리자가 [업로드]를 누를 때 | 업로드 링크를 다시 발급받는다 (04장 `upload_tokens`) |
| 재생용 (마스킹본 버킷 GET) | 01장 1.6 (15분) | URL이 들어가는 조회 API(5.2의 10·12·15번: 정지 장면, 후보 묶음, 고정된 사건 지점)를 **부를 때마다 새로 서명** | 재생하려 할 때 S3가 403을 준다. 프론트가 같은 조회 API를 다시 불러 새 URL로 이어 재생한다 |

- URL은 DB에 저장하지 않는다. 서명은 백엔드 안에서 하는 계산이라 AWS 호출도 비용도 없다.
- 재생 URL 재발급 전용 API는 두지 않는다. 만료(S3 403)되면 원래 조회 API를 다시 부른다.
- 응답에는 URL과 함께 만료 시각을 넣지 않는다. 프론트는 시각을 계산하지 않고 403이 나면 다시 조회하기만 한다. 서명 자격 증명 교체로 일찍 만료되는 경우(D-41 한계)도 같은 처리로 해결된다.

**기록을 남기는 API** (D-53)

개인영상정보에 닿는 요청은 성공했을 때 `access_logs`에 한 행씩 남긴다(04장 `access_logs`). 표준 개인정보 보호지침 제44조⑤·제42조가 요구하는 **법정 기록**이므로 끄는 설정을 두지 않는다.

| 엔드포인트 | `action` | 함께 남기는 것 |
|---|---|---|
| 1. 로그인 | `login` | `user_id`, `requested_ip` |
| 4. 업로드 링크 발급 | `issue_upload_link` | `user_id`, `requested_ip` |
| 10. 정지 장면 조회 | `view_still` | `user_id`, `video_id`, `requested_ip` |
| 12·15. 재생 URL이 들어가는 조회 | `view_clip` | `user_id`, `video_id`, `requested_ip` |
| 14. 사건 지점 고정 | `pin_incident` | `user_id`, `video_id`, `requested_ip` |
| (API 아님) 원본 파기 주기 작업 | `delete_raw` | `video_id`. `user_id`·`requested_ip`는 비어 있다 (D-52) |
| (API 아님) 마스킹본·분석 결과 파기 주기 작업 | `delete_masked` | `video_id`. `user_id`·`requested_ip`는 비어 있다 (D-57) |

- **재생 URL을 발급할 때마다 남는다.** 같은 클립을 다시 보면 행이 또 생긴다. 재생 URL은 부를 때마다 새로 서명하므로(D-41) 발급 = 열람으로 본다.
- 기록 쓰기가 실패해도 API는 성공으로 답한다. 남기지 못한 것을 서버 로그에 남긴다. 기록 때문에 열람이 막히면 사용자가 더 손해다.
- 실패한 요청(401·404 등)은 남기지 않는다. 남길 열람이 일어나지 않았기 때문이다.

**`last_activity_at`을 갱신하는 API** (D-52)

원본 파기 시점을 계산하는 값이다(04장 `videos`). 아래 API가 성공하면 `videos.last_activity_at = now()`로 갱신한다.

| 갱신한다 | 갱신하지 않는다 |
|---|---|
| 7. 업로드 완료 알림 · 11. 입력 저장 · 12. 묶음 조회 · 13. [다음] · 14. 고정 | **9. 상태 조회(폴링)**, 8. 영상 목록, 10. 정지 장면 조회 |

- **상태 조회로는 갱신하지 않는 것이 핵심이다.** 화면을 켜 두기만 해도 5~10초마다 폴링이 도는데(U-18), 그것으로 갱신하면 3일이 영원히 오지 않는다.

**SQS에 작업을 넣는 API** (7·11·13번, D-46)

작업을 SQS에 넣는 API는 모두 아래 순서를 따른다.

```
트랜잭션 시작
  DB 쓰기 (상태 변경, 행 생성 등)
  SQS SendMessage  → 실패하면 롤백하고 500 INTERNAL_ERROR
커밋
GPU EC2 켜기 요청
```

- **"DB에는 작업이 있는데 SQS에는 메시지가 없는" 상태를 만들지 않기 위해서다.** 그 상태가 되면 화면은 "대기 중"을 계속 보여주는데 워커는 영원히 메시지를 받지 못한다 (D-46).
- **GPU 켜기가 거부되거나 실패해도 API는 성공으로 답한다.** 작업은 이미 SQS에 들어갔고, 백엔드의 5초 주기 점검이 "작업은 있는데 GPU가 꺼져 있음"을 찾아 다시 켠다 (D-42). 사용자에게는 대기 시간이 조금 늘어나는 것 말고 달라지는 것이 없다.

## 5.2 엔드포인트 목록

인증 방법은 5.1의 표를 따른다. "전이"는 04장 4.3 전이 표의 번호다.

**계정** (세션 쿠키. 1은 로그인 전에 부른다. 회원가입은 없고 계정은 스크립트로 만든다, D-44)

| # | 메서드·주소 | 하는 일 | 관련 |
|---|---|---|---|
| 1 | `POST /api/auth/login` | 로그인. 세션 쿠키를 내려준다 | D-30 |
| 2 | `POST /api/auth/logout` | 로그아웃. `sessions` 행을 지운다 | D-30 |
| 3 | `GET /api/auth/me` | 지금 로그인한 사용자. 프론트가 처음 열릴 때 로그인 여부를 확인한다 | |

**업로드 링크** (피해자, 세션 쿠키)

| # | 메서드·주소 | 하는 일 | 관련 |
|---|---|---|---|
| 4 | `POST /api/upload-links` | 일회용 업로드 링크를 발급한다 | D-28 |

**업로드** (관리자, 링크의 `token`. 쿠키를 보지 않는다)

| # | 메서드·주소 | 하는 일 | 관련 |
|---|---|---|---|
| 5 | `GET /api/uploads/{token}` | 링크를 아직 쓸 수 있는지 확인한다. 관리자가 링크를 열자마자 만료·사용 완료를 안내하기 위해 둔다 | D-28 |
| 6 | `POST /api/uploads/{token}/presign` | 파일 이름·크기를 검사하고(5GB, 확장자) 업로드용 presigned URL을 발급한다. `videos` 행 생성, `used_at` 기록, **GPU 켜기** | D-15, D-18, D-22, D-41, D-43 |
| 7 | `POST /api/uploads/{token}/complete` | 업로드 완료 알림. `analysis_jobs` 행을 만들고(`queued`) 1단계 작업을 SQS에 넣는다 | 전이 1 |

**영상과 분석** (피해자, 세션 쿠키. 요청마다 주인을 확인하고 남의 영상은 404)

| # | 메서드·주소 | 하는 일 | 관련 |
|---|---|---|---|
| 8 | `GET /api/videos` | 내 영상 목록과 각 상태 | |
| 9 | `GET /api/videos/{video_id}` | 상태 한 건. **화면이 주기적으로 조회하는 대상**이다. "앞에 N건", 입력을 마쳤는지(`input_done`) 포함 | 4.5, U-18, D-47, D-49 |
| 10 | `GET /api/videos/{video_id}/still` | 정지 장면(원본 영상 시작 장면 1장, 1단계에서 만들어 둔 것)과 재생용 URL (5.6) | D-41, D-48 |
| 11 | `PUT /api/videos/{video_id}/input` | 차량·파손 부위 입력 저장. **1단계가 끝나기 전까지** 다시 보내 고칠 수 있어 PUT이다 (5.7) | 전이 4·7, D-25, D-36, D-49 |
| 12 | `GET /api/videos/{video_id}/batch` | 지금 묶음의 후보 클립과 재생용 URL, 남은 후보 수 | D-37, D-41 |
| 13 | `POST /api/videos/{video_id}/batch/next` | [다음] = 묶음 전체 "못 찾음" | 전이 10·12, D-37 |
| 14 | `POST /api/videos/{video_id}/pin` | 사건 지점 고정 | 전이 9, D-35 |
| 15 | `GET /api/videos/{video_id}/pin` | 고정된 사건 지점과 재생용 URL, 원본 기준 시작·끝 시간 | D-32 |

- 피해자가 원본을 직접 올리는 API는 없다. 업로드는 5~7번뿐이다 (D-45).
- 고정 해제 API는 없다 (D-40).

## 5.3 계정 API

회원가입은 없다. 데모는 스크립트로 만든 **공용 계정 하나**로 로그인한다 (D-44).

### 1. `POST /api/auth/login` 로그인

요청

```json
{"login_id": "demo", "password": "demo-password"}
```

성공: `200`

```http
Set-Cookie: sid=Jx3k...(랜덤 문자열); HttpOnly; Path=/; Max-Age=604800
```

```json
{"id": 1, "login_id": "demo", "name": "시연용"}
```

- `sessions` 행을 새로 만들고, 그 `token`을 쿠키 `sid`로 내려준다. 유효 시간은 01장 1.6(7일, 연장 없음)이고 `Max-Age`도 같은 값이다.
- 쿠키 속성: `HttpOnly`는 켜고 `Secure`는 켜지 않는다(HTTPS 없음, D-31). `SameSite`는 08장에서 정한다 🚧.
- 이미 로그인한 상태에서 다시 불러도 에러가 아니다. 새 세션을 만든다.
- 같은 계정으로 여러 브라우저에서 동시에 로그인할 수 있다. 세션은 브라우저마다 한 행이다.
- 응답 본문은 3번 `GET /api/auth/me`와 같다.

실패

| HTTP | `code` | 언제 |
|---|---|---|
| 401 | `LOGIN_FAILED` | 아이디가 없거나 비밀번호가 틀림. **둘을 구분하지 않는다.** 어느 쪽이 틀렸는지 알려주면 아이디가 있는지 확인하는 데 쓰일 수 있다 |
| 422 | `VALIDATION_FAILED` | `login_id`나 `password`가 없거나 빈 문자열 |

- `LOGIN_FAILED`는 공통 코드 `UNAUTHENTICATED`와 다르다. `UNAUTHENTICATED`를 받으면 프론트는 로그인 화면으로 보내지만, 로그인 화면에서 받은 `LOGIN_FAILED`는 "아이디 또는 비밀번호가 틀렸다"는 안내를 보여준다.

### 2. `POST /api/auth/logout` 로그아웃

요청 본문 없음.

성공: `204` (본문 없음)

```http
Set-Cookie: sid=; HttpOnly; Path=/; Max-Age=0
```

- 쿠키의 세션 행을 지우고 쿠키도 지운다. 이 브라우저의 세션만 끝난다. 같은 계정의 다른 브라우저 세션은 그대로다.
- **쿠키가 없거나 이미 만료된 세션이어도 `204`로 답한다.** 로그아웃의 목적(이 브라우저가 로그아웃 상태가 됨)은 이미 이뤄졌기 때문이다. 5.1의 "그 밖의 모든 API는 쿠키가 없으면 401" 규칙의 예외다.

### 3. `GET /api/auth/me` 내 정보

요청 본문 없음. 세션 쿠키로 인증한다.

성공: `200`

```json
{"id": 1, "login_id": "demo", "name": "시연용"}
```

실패

| HTTP | `code` | 언제 |
|---|---|---|
| 401 | `UNAUTHENTICATED` | 쿠키가 없거나, 세션 행이 없거나, 만료됨 |

- 프론트는 처음 열릴 때 이 API를 불러 로그인 여부를 확인한다. `200`이면 영상 목록으로, `401`이면 로그인 화면으로 간다.
- `password_hash`는 어떤 응답에도 넣지 않는다.

## 5.4 업로드 링크·업로드 API

관리자 화면에서 부르는 순서는 아래와 같다. 5~7번은 쿠키를 보지 않고 주소의 `token`으로만 인증한다 (D-28).

```
피해자 브라우저                 관리자 브라우저(로그인 없음)                S3 원본 버킷
4. POST /api/upload-links
   → token을 받아 링크를 보여준다
                               링크를 연다
                               5. GET /api/uploads/{token}   쓸 수 있는 링크인가
                               파일 고르기 (확장자·5GB는 프론트가 먼저 막는다)
                               [업로드]
                               6. POST .../presign  → upload_url
                               PUT upload_url (파일 본문) ───────────→  original.mp4
                               7. POST .../complete  → 분석 대기열에 들어감
```

**링크를 쓸 수 없는 경우의 코드** (5~7번 공통)

| HTTP | `code` | 언제 | 화면 |
|---|---|---|---|
| 404 | `UPLOAD_TOKEN_NOT_FOUND` | `token`에 맞는 행이 없음. 주소를 잘못 옮겨 적은 경우 | 링크 주소를 다시 확인하라는 안내 |
| 410 | `UPLOAD_TOKEN_USED` | `used_at`이 차 있음. 이미 이 링크로 업로드를 시작했다 | 이미 사용한 링크. 피해자에게 새 링크를 받으라는 안내 |
| 410 | `UPLOAD_TOKEN_EXPIRED` | `expires_at`이 지남 (01장 1.6, 24시간) | 만료된 링크. 피해자에게 새 링크를 받으라는 안내 |

- 둘 다 해당하면 `UPLOAD_TOKEN_USED`를 준다. "이미 올렸다"가 관리자에게 더 쓸모 있는 안내다.
- 410(Gone)은 "있었지만 이제 쓸 수 없다"는 뜻의 HTTP 번호다. 프론트는 번호가 아니라 `code`로 나눈다 (5.1).
- 7번(완료 알림)은 이 표와 조금 다르게 검사한다. 7번에서 설명한다.

### 4. `POST /api/upload-links` 업로드 링크 발급

세션 쿠키로 인증한다. 요청 본문 없음.

성공: `201`

```json
{"token": "q8Zp3vN1c0xR7mWkT2hYb9sLfA4eJ6uD5gQiXo_Kz-E", "expires_at": "2026-09-19T14:03:00+09:00"}
```

- `upload_tokens` 행을 만든다. 주인은 로그인한 사용자, `expires_at`은 지금 + 01장 1.6(24시간)이다.
- `token`은 추측할 수 없는 랜덤 문자열이다. 만드는 방법은 08장에서 정한다.
- **응답에 링크 주소 전체를 넣지 않고 `token`만 준다.** 링크 주소 모양(예: `http://<백엔드 IP>/#/upload/{token}`)은 프론트의 화면 경로라서 프론트가 지금 열린 주소를 앞에 붙여 만든다. 백엔드는 자기 퍼블릭 IP를 모르고, 켤 때마다 바뀐다 (D-12).
- **새로 발급하면 이 사용자의 이전 링크는 무효가 된다.** 행을 만들기 전에 아래를 실행한다. 살아 있는 링크는 항상 가장 최근 것 하나뿐이다 (D-28).

```sql
UPDATE upload_tokens
   SET expires_at = now()
 WHERE owner_user_id = :me
   AND used_at IS NULL
   AND expires_at > now();
```

  - 이미 쓴 링크(`used_at`이 차 있음)는 건드리지 않는다. 그 링크로 올라온 영상과 분석은 그대로다.
  - 무효가 된 링크를 열면 `UPLOAD_TOKEN_EXPIRED`가 나온다. 만료와 취소를 코드로 구분하지 않는다. 관리자에게는 "새 링크를 받으세요"로 똑같기 때문이다.
  - 그래서 이 API는 **[링크 다시 발급] 버튼을 눌렀을 때만** 불러야 한다. 발급 화면을 여는 것만으로 부르면 이미 관리자에게 보낸 링크가 죽는다 (07장).
- 링크 목록 조회 API는 두지 않는다. 살아 있는 링크가 하나뿐이라 목록이 필요 없다.

실패: 공통 코드(401 `UNAUTHENTICATED`)만 있다.

### 5. `GET /api/uploads/{token}` 링크 확인

요청 본문 없음.

성공: `200`

```json
{"expires_at": "2026-09-19T14:03:00+09:00"}
```

- 관리자가 링크를 열자마자 부른다. 쓸 수 없는 링크면 파일을 고르기 전에 안내하기 위해서다.
- **영상 주인의 이름·아이디는 돌려주지 않는다.** 링크로 할 수 있는 일은 업로드뿐이다 (D-28).
- 아무것도 바꾸지 않는다. 여러 번 불러도 된다.

실패: 위 "링크를 쓸 수 없는 경우의 코드" 표.

### 6. `POST /api/uploads/{token}/presign` 업로드 URL 발급

요청

```json
{"filename": "CH03_20260917_000000.mp4", "size_bytes": 1837260800}
```

성공: `200`

```json
{"upload_url": "https://<prefix>-raw.s3.ap-northeast-2.amazonaws.com/videos/17/original.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=...&X-Amz-Expires=900&X-Amz-Signature=..."}
```

백엔드가 하는 일 (순서대로)

1. 요청 값을 검사한다. 아래 "실패" 표.
2. 링크를 쓴 것으로 표시한다. **조건부 UPDATE 한 번**으로 검사와 표시를 같이 한다(4.4와 같은 방법).

```sql
UPDATE upload_tokens
   SET used_at = now()
 WHERE token = :token
   AND used_at IS NULL
   AND expires_at > now()
RETURNING id, owner_user_id;
```

   - 1행이 나오면 이 요청이 링크를 가져갔다. 0행이면 다시 조회해 "링크를 쓸 수 없는 경우의 코드" 중 맞는 것을 돌려준다.
   - 관리자가 [업로드]를 두 번 눌러 요청이 동시에 두 번 와도 한쪽만 1행을 받는다. 다른 쪽은 `UPLOAD_TOKEN_USED`를 받는다. 프론트는 첫 요청을 보낸 뒤 버튼을 막는다.
3. 같은 트랜잭션에서 `videos` 행을 만든다. 주인은 링크의 주인이고, `upload_token_id`·`original_filename`·`size_bytes`를 채운다. S3 키 `videos/{video_id}/original.{ext}`는 행 번호가 있어야 정해지므로, 번호를 먼저 받고(`nextval`) 키를 채워 넣는다 (04장 4.9).
4. 커밋한다.
5. 업로드용 presigned URL을 서명한다. 원본 버킷 `PutObject`, 유효 시간은 01장 1.6(15분)이다 (D-41).
6. GPU EC2 켜기를 요청한다 (D-15). **실패해도 응답은 성공이다.** 이 시점에는 아직 작업이 없어 5초 점검(D-42)도 켜지 않는다. 대신 7번에서 다시 요청한다.

- `ext`는 `filename`의 마지막 `.` 뒤를 소문자로 바꾼 것이다. `CH03.MP4` → `mp4`.
- 링크는 **이 API에서 쓴 것이 된다.** 업로드가 중간에 끊기면 링크를 새로 받아야 한다 (04장 `upload_tokens`).
- 응답에 `video_id`를 넣지 않는다. 관리자는 영상을 볼 수 없고, 7번은 `token`으로 영상을 찾는다.

프론트가 `upload_url`로 올리는 방법

- **HTTP `PUT`으로, 요청 본문에 파일 바이트를 그대로** 보낸다. `multipart/form-data`(폼 전송)로 감싸면 S3에 폼 내용이 통째로 저장돼 영상 파일이 깨진다.
- 서명에 `Content-Type`을 넣지 않는다. 그래서 브라우저가 어떤 `Content-Type`을 붙여도 서명이 맞는다. 다만 브라우저가 이 헤더를 붙이므로 버킷 CORS가 `Content-Type` 헤더를 허용해야 한다 (D-22 ⚠️).
- S3가 `200`을 주면 업로드가 끝난 것이다. 그 뒤 7번을 부른다.
- 업로드 도중 15분이 지나도 괜찮다. S3는 요청이 **시작될 때만** 만료를 본다 (D-41).
- **멀티파트로 바꿀 때**: 데모는 단일 PUT이라 파일 한 개당 최대 5GB다. 실제 운영에서 그보다 큰 영상을 받으려면 이 6번이 "조각마다 URL 발급 + 완료 알림" 세 API로 늘어난다. 더하거나 바꿀 것의 목록은 [11장 D-22](11-decisions.md#d-22-업로드는-단일-put으로-구현하고-실제-운영에서는-멀티파트로-바꾼다)에 있다. 4·5·7번과 이 장의 다른 API는 그대로다.

실패

| HTTP | `code` | 언제 |
|---|---|---|
| 404 / 410 | 위 표 | 링크를 쓸 수 없음 |
| 422 | `UNSUPPORTED_FILE_TYPE` | `filename`의 확장자가 `.mp4` `.avi` `.mkv` `.mov`가 아님. 확장자가 없는 경우도 포함 (D-43) |
| 422 | `FILE_TOO_LARGE` | `size_bytes`가 5GB(01장 1.6)보다 큼 (D-22) |
| 422 | `VALIDATION_FAILED` | `filename`이 비었거나 `size_bytes`가 0 이하 |

- 확장자와 크기는 프론트가 먼저 막는다(07장). 여기서 다시 막는 것은 프론트를 거치지 않은 요청 때문이다.
- 크기는 브라우저가 알려준 값이다. 실제로 더 큰 파일을 보내도 S3가 단일 PUT 5GB 한도에서 거절한다.
- 422를 돌려줄 때는 링크를 쓴 것으로 표시하지 않는다. 검사(1)가 표시(2)보다 먼저다. 관리자는 다른 파일을 골라 다시 시도할 수 있다.

### 7. `POST /api/uploads/{token}/complete` 업로드 완료 알림

요청 본문 없음. 브라우저가 S3 `PUT`에서 `200`을 받은 뒤 부른다.

성공: `204` (본문 없음)

백엔드가 하는 일 (D-46)

```
트랜잭션 시작
  1) UPDATE videos SET upload_completed_at = now()
      WHERE upload_token_id = :token_id AND upload_completed_at IS NULL
     → 0행이면 이미 완료 알림을 처리했다. 커밋하고 204 (아래 "두 번 불러도 된다")
  2) INSERT analysis_jobs (video_id, status='queued')  → job_id    (전이 1)
  3) SQS에 {"job_id": 42, "kind": "stage1"} 넣기
     → 실패하면 롤백하고 500 INTERNAL_ERROR
커밋
4) GPU EC2 켜기 요청. 실패해도 204 (D-42)
```

- **링크의 만료(`expires_at`)는 보지 않는다.** 6번에서 이미 링크를 가져갔고, 큰 파일은 업로드에 오래 걸려 그 사이 24시간을 넘길 수 있기 때문이다. 대신 "이 `token`으로 6번을 불러 만든 영상이 있는지"를 본다.
- **두 번 불러도 된다.** 응답을 받기 전에 네트워크가 끊겨 프론트가 다시 불러도, 1)에서 0행이 나와 작업을 또 만들지 않는다. `analysis_jobs.video_id`의 UNIQUE(04장)도 한 번 더 막는다.
- 4)에서 GPU를 다시 켜는 이유: 6번에서 켠 GPU는 업로드가 15분 넘게 걸리면 할 일이 없어 스스로 꺼진다(D-15). 켜기가 실패해도 이제는 작업이 있으므로 5초 점검(D-42)이 켠다.
- **S3에 파일이 정말 올라왔는지 백엔드가 확인하지 않는다.** 백엔드 역할에는 원본 버킷을 읽는 권한이 없다(불변 조건 1). 파일 없이 완료 알림만 오면 워커가 1단계에서 원본을 열지 못해 실패로 끝난다 (06장).

실패

| HTTP | `code` | 언제 |
|---|---|---|
| 404 | `UPLOAD_TOKEN_NOT_FOUND` | `token`에 맞는 행이 없음 |
| 409 | `INVALID_STATE` | 링크는 있지만 6번을 부른 적이 없어 영상이 없음 |
| 500 | `INTERNAL_ERROR` | SQS에 넣지 못함. 아무것도 바뀌지 않았으므로 프론트가 다시 부르면 된다 |

## 5.5 영상 목록·상태 조회 API

세션 쿠키로 인증하고, 요청마다 주인을 확인한다. 남의 영상은 404 `VIDEO_NOT_FOUND`다 (D-39).

**상태 값** (D-47)

화면이 보는 `status`는 `analysis_jobs.status`(04장 4.3)에 **백엔드가 만들어 주는 두 값**을 더한 것이다. 두 값은 DB에 저장하지 않고 조회할 때 계산한다.

| `status` | 언제 나오나 |
|---|---|
| `uploading` | 작업 행이 없고, URL 발급(6번)으로부터 01장 1.6(30분)이 지나지 않음. **관리자가 올리는 중** |
| `upload_failed` | 작업 행이 없고, URL 발급으로부터 30분이 지남. **완료 알림이 오지 않은 영상** |
| 그 밖 | `analysis_jobs.status` 값 그대로 (`queued` … `failed`) |

```sql
CASE WHEN j.status IS NOT NULL                                  THEN j.status
     WHEN v.created_at > now() - interval '30 minutes'          THEN 'uploading'
     ELSE 'upload_failed'
END
```

- 작업 행은 7번(완료 알림)이 `upload_completed_at`과 **한 트랜잭션**으로 만든다 (D-46). 그래서 "업로드는 끝났는데 작업 행이 없는" 중간 상태는 조회에 잡히지 않는다.
- `upload_failed`는 **되돌아갈 수 있다.** 느린 회선이라 30분을 넘겼을 뿐이라면, 뒤늦게 7번이 도착하는 순간 같은 영상이 `queued`로 보인다. 저장하는 값이 아니라 계산하는 값이기 때문이다.
- **화면은 이 값을 "실패"로 단정하지 않는다.** 백엔드는 원본 버킷을 읽을 수 없어 파일이 올라왔는지 모른다. 문구는 07장에 있다 (D-47).
- `uploading`·`upload_failed` 영상은 10~15번을 부를 수 없다. 부르면 409 `INVALID_STATE`다.

### 8. `GET /api/videos` 내 영상 목록

요청 본문 없음.

성공: `200`

```json
[
  {"video_id": 18, "original_filename": "CH03_0919.mp4", "status": "uploading",
   "created_at": "2026-09-20T14:05:00+09:00"},
  {"video_id": 17, "original_filename": "CH01_0918.mp4", "status": "queued",
   "created_at": "2026-09-19T09:12:00+09:00"},
  {"video_id": 12, "original_filename": "CH01_0915.mp4", "status": "pinned",
   "created_at": "2026-09-15T20:41:00+09:00"}
]
```

- 내 영상만 나온다(`owner_user_id`). 최신순(`created_at` 내림차순)이다.
- **"앞에 N건"(`queue_ahead`)은 목록에 넣지 않는다.** 영상마다 세는 조회라 목록에서 한꺼번에 하면 무거워진다 (D-19). 대기 순서는 영상을 연 뒤 9번에서 본다.
- 페이지 나누기는 두지 않는다. 한 사람의 영상이 몇 건뿐인 데모 규모다. 실제 운영에서 늘어나면 `limit`·`cursor`를 더한다.

실패: 공통 코드(401 `UNAUTHENTICATED`)만 있다.

### 9. `GET /api/videos/{video_id}` 영상 하나의 상태

요청 본문 없음. **분석이 끝날 때까지 화면이 주기적으로 부르는 API**다. 주기는 5~10초 🚧 (U-18, D-19).

성공: `200`

```json
{"video_id": 17, "original_filename": "CH01_0918.mp4", "status": "queued",
 "queue_ahead": 2,
 "input_done": false,
 "candidate_total": 0,
 "raw_deleted": false,
 "masked_deleted": false,
 "created_at": "2026-09-19T09:12:00+09:00",
 "duration_sec": 86400.0}
```

| 키 | 언제 들어가나 |
|---|---|
| `queue_ahead` | `status`가 `queued`일 때만. 나보다 먼저 들어왔고 아직 1단계가 끝나지 않은 작업 수다 (04장 4.5) |
| `input_done` | 항상. 차량·파손 부위 입력이 저장됐는지(`analysis_jobs.input_completed_at`이 차 있는지)다. 저장하지 않고 조회할 때 본다 |
| `candidate_total` | `status`가 `exhausted`일 때만. 지금까지 만들어진 후보 총 수다. `0`이면 후보가 한 번도 만들어지지 않았다는 뜻이다 (04장 `candidates`를 세서 계산한다) |
| `raw_deleted` | 항상. 원본 영상이 파기됐는지(`videos.raw_deleted_at`이 차 있는지)다. 저장하지 않고 조회할 때 본다 (D-52) |
| `masked_deleted` | 항상. 마스킹본·분석 결과가 파기됐는지(`videos.masked_deleted_at`이 차 있는지)다. 같은 방식으로 조회할 때 본다 (D-57) |
| `duration_sec` | 워커가 1단계에서 채운 뒤부터. 그 전에는 `null` |
| 그 밖 | 항상 |

- **실패 이유(`error_message`)는 돌려주지 않는다.** 워커가 남기는 영문 개발자용 문구라 사용자에게 보여줄 것이 아니다. 화면은 `failed`만 보고 "분석에 실패했습니다"를 보여준다 (07장). 개발자는 DB에서 본다.
- **`input_done`이 따로 있는 이유**: `stage1_done`은 "입력을 기다리는 중"과 "입력을 받아 2단계 작업을 넣어 둔 중" 둘 다에서 나온다(5.7). 화면이 `status` 하나만 보면 이미 입력한 사용자에게 입력 화면을 다시 보여주게 된다. 두 값을 함께 보고 입력 화면을 열지 정한다 (D-49, 07장).
- **`raw_deleted`가 따로 있는 이유**: 원본은 끝 상태이거나 3일 동안 입력이 없으면 파기된다(D-52). 파기해도 `status`는 바뀌지 않으므로, `ready`인데 원본은 없는 상태가 생긴다. 이때 **[다음]을 눌러도 다음 묶음을 만들 수 없다** — 후보 클립은 원본에서 잘라내기 때문이다. 화면은 이 값을 보고 [다음] 버튼 대신 안내문을 보여준다 (07장). 13번도 같은 값을 보고 요청을 막는다.
  - `status`에 `expired` 같은 값을 더하지 않은 이유는 D-52에 적었다. 상태 목록·전이 표·KPI 집계를 건드리지 않기 위해서다.
  - 이미 고정한 영상(`pinned`)은 이 값이 `true`여도 결과를 계속 볼 수 있다. 고정은 마스킹본 클립을 가리키기 때문이다 (D-32).
- **`masked_deleted`가 따로 있는 이유**: 마스킹본과 분석 결과는 업로드 완료에서 30일이 지나면 파기된다(D-57). 이때는 정지 장면도 후보 클립도 고정된 사건 지점도 볼 수 없다. `raw_deleted`와 같은 이유로 `status`는 그대로이므로, 화면이 이 값을 보고 "보관 기간이 끝나 삭제되었습니다"를 보여준다 (07장). 10·12·15번도 같은 값을 보고 요청을 막는다.
  - `raw_deleted`가 `true`여도 `masked_deleted`가 `false`면 **결과는 계속 볼 수 있다.** 막히는 것은 다음 묶음을 새로 만드는 일뿐이다.
- **`candidate_total`이 따로 있는 이유**: `exhausted`는 "사용자가 후보를 전부 넘겼다"(전이 12)와 "후보가 0건이었다"(전이 14) 둘 다에서 나온다. 앞은 "모든 후보를 확인했습니다", 뒤는 "후보 구간이 탐지되지 않았습니다"여야 한다(PRD 3.5·3.6). `exhausted`일 때 12번은 409라 화면이 빈 배열로 알아낼 수도 없다. 그래서 여기서 구분값을 준다 (D-50, 07장).
- 이 API는 무거운 일을 하지 않는다. 읽는 것은 `videos` 1행, `analysis_jobs` 1행, `queued`일 때 count 1번, `exhausted`일 때 count 1번뿐이다 (D-19).

실패

| HTTP | `code` | 언제 |
|---|---|---|
| 404 | `VIDEO_NOT_FOUND` | 없는 영상이거나 남의 영상 |

## 5.6 정지 장면 조회 API

차량 선택 화면이 쓰는 이미지다. 장면은 1단계에서 미리 만들어 두므로(D-48) 이 API는 **DB를 읽고 URL에 서명만 한다.** GPU를 켜지 않는다.

### 10. `GET /api/videos/{video_id}/still` 정지 장면 조회

**차량 선택 화면을 열 때 한 번 부른다.** 정지 장면은 **원본 영상 시작 장면 1장**이고 다른 시점으로 넘기는 기능이 없으므로(D-48), 이 API도 값 하나만 준다.

응답 `200`

```json
{
  "still_frame_id": 305,
  "t_sec": 0.0,
  "image_url": "https://<prefix>-masked.s3.ap-northeast-2.amazonaws.com/videos/17/stills/0.jpg?X-Amz-Algorithm=..."
}
```

| 키 | 뜻 |
|---|---|
| `still_frame_id` | `still_frames` 행 번호. 사용자가 이 장면 위에 그린 사각형을 저장할 때 11번에 그대로 보낸다 (5.7) |
| `t_sec` | 원본 시간(초). 시작 장면이라 `0.0`이다 (04장 4.7) |
| `image_url` | 마스킹본 버킷의 JPG에 서명한 재생용 URL. 유효 시간 15분 (D-41) |

- **장면은 항상 1장이다.** 작업 1건에 `still_frames` 행이 1개다(04장, `analysis_job_id` UNIQUE). 영상 길이와 관계없다.
- 이미지는 **원본 해상도 그대로** 저장한다. 11번에서 보내는 드래그 좌표가 원본 해상도 기준 픽셀이기 때문이다 (5.1). 화면이 축소해 보여주더라도 프론트가 `<img>`의 `naturalWidth`·`naturalHeight`로 원본 크기를 알 수 있어, 응답에 해상도를 따로 넣지 않는다.
- URL은 저장하지 않고 부를 때마다 새로 서명한다. 오래 열어 둬 만료되면(S3가 403) **이 API를 다시 부른다** (D-41).
- **확장**: 여러 시점 장면이 필요해지면 응답을 `{"stills": [...]}` 배열로 바꾸고, 첫 원소를 처음 보여줄 장면으로 둔다. 절차는 [11장 D-48 "되살릴 방법"](11-decisions.md#d-48-차량-선택용-정지-장면은-원본-영상-시작-장면-1장만-만든다).

실패

| HTTP | `code` | 언제 | 프론트 처리 |
|---|---|---|---|
| 404 | `VIDEO_NOT_FOUND` | 없는 영상이거나 남의 영상 (D-39) | 목록으로 |
| 409 | `MASKED_EXPIRED` | 보관 기간이 끝나 마스킹본이 파기됐다(D-57). `message`에 파기 시각을 적는다 | 9번을 다시 불러 "보관 기간 종료" 안내문으로 바꾼다 |
| 409 | `INVALID_STATE` | 정지 장면이 아직 없다. `message`에 현재 상태를 적는다 | 상태를 다시 조회해(9번) 대기 화면을 보여준다 |

- **`MASKED_EXPIRED`를 `INVALID_STATE`보다 먼저 본다.** `videos` 행은 5.1의 소유자 확인에서 이미 읽으므로 조회가 늘지 않는다. 없는 키에 서명해 주면 브라우저가 S3의 404 XML을 받는다.
- 409가 되는 상태는 `uploading`·`upload_failed`(작업 행이 아직 없음, D-47)와 `queued`·`stills_running`이다. `stills_running`이 끝나면서 장면이 생기므로(04장 4.3 전이 3), **`still_frames` 행이 있으면 200, 없으면 409**로 판단하면 상태 목록을 따로 검사하지 않아도 된다.
- `failed`여도 장면이 이미 만들어져 있으면 200이다. 실패 안내는 9번의 `status`로 하고, 이 API는 이미지만 담당한다.

## 5.7 차량·파손 부위 입력 저장 API

차량 사각형과 파손 부위 사각형을 **한 요청으로 받아 그대로 저장한다.** 탐지와 맞추지 않고(누끼 없음), 방향(`sides`)도 계산하지 않는다 (D-29, D-34, D-36).

### 11. `PUT /api/videos/{video_id}/input` 차량·파손 부위 저장

요청

```json
{
  "still_frame_id": 305,
  "schema_version": 1,
  "vehicle": {"bbox": [800, 430, 970, 630]},
  "damage": {"damage_bbox": [940, 470, 1000, 610]}
}
```

| 키 | 뜻 |
|---|---|
| `still_frame_id` | 어느 정지 장면 위에서 그렸는지. 10번 응답의 값을 그대로 보낸다 |
| `schema_version` | 아래 두 객체의 형식 번호. 지금은 `1`뿐이다 (D-25) |
| `vehicle` | `vehicle_selections.payload`에 **그대로** 저장할 객체 (04장) |
| `damage` | `damage_inputs.payload`에 **그대로** 저장할 객체 (04장) |

성공: `200`

```json
{"status": "stage1_input_done", "input_done": true}
```

- `status`는 저장 뒤의 상태다. 화면은 이 값으로 다시 그리고 9번을 따로 부르지 않아도 된다.
- **PUT인 이유**: 같은 요청을 다시 보내면 같은 결과가 된다. 두 테이블 모두 작업 1건당 1행이라(04장) 덮어쓰기다.

**`schema_version` 1의 검증 규칙** (D-25)

DB는 `payload`의 내용을 검사하지 않는다. 아래를 백엔드(Pydantic)가 검사하고, 하나라도 어긋나면 **아무것도 저장하지 않고** 422 `VALIDATION_FAILED`를 돌려준다. `message`에 어느 값이 왜 틀렸는지 적는다.

| # | 검사 | 어긋나면 |
|---|---|---|
| 1 | `schema_version`이 `1`이다 | 422. 모르는 형식을 저장하면 2단계 룰이 읽지 못한다 |
| 2 | `vehicle`은 `bbox` 키 하나, `damage`는 `damage_bbox` 키 하나만 가진다 (`extra="forbid"`) | 422. 오타 난 키가 조용히 저장되는 것을 막는다 |
| 3 | 두 사각형 모두 **정수 4개** `[x1, y1, x2, y2]`이고 `x1 < x2`, `y1 < y2` | 422 |
| 4 | 두 사각형 모두 원본 해상도 안에 있다: `0 ≤ x1`, `x2 ≤ videos.width`, `0 ≤ y1`, `y2 ≤ videos.height` | 422 |
| 5 | `damage_bbox`가 `bbox` **안(경계 포함)** 에 있다 (D-29) | 422 |
| 6 | `still_frame_id`가 **이 작업의** `still_frames` 행이다 | 422 |

- 좌표는 원본 해상도 기준 픽셀이다 (5.1). 정지 장면 이미지도 원본 해상도로 저장하므로(5.6) 프론트는 화면 좌표를 이미지 원본 크기로 되돌려 보낸다.
- 4번의 `videos.width`·`height`는 워커가 1단계 시작 때 채운다(04장). 정지 장면이 생긴 뒤에만 입력할 수 있으므로 이 값은 항상 차 있다.
- 5번은 화면이 먼저 막는다(07장). 여기서 다시 막는 것은 프론트를 거치지 않은 요청 때문이다.
- 6번은 남의 작업의 장면 번호를 저장하지 않기 위한 검사다. `still_frame_id`는 `video_id`와 달리 주소에 없지만 순차 번호라 추측할 수 있다 (D-39와 같은 이유).
- U-13(룰이 실제로 받는 값)이 정해져 형식이 바뀌면 `schema_version`을 2로 올리고 이 표에 2의 규칙을 더한다. 저장된 옛 데이터는 버린다 (D-25).

**상태별로 하는 일** (전이 4·7, D-15, D-49)

| 지금 `status` | 입력이 이미 있나 | 하는 일 |
|---|---|---|
| `stage1_running` | 없음 | 두 행을 만들고 `input_completed_at`을 찍는다. `stage1_input_done`으로 바꾼다 (전이 4). SQS에 넣지 않는다 — 1단계가 끝날 때 워커가 이어서 2단계를 한다 (전이 6) |
| `stage1_input_done` | 있음 | 두 행을 **덮어쓴다.** 상태와 `input_completed_at`은 그대로 둔다. 다시 저장한 시각은 두 행의 `updated_at`에 남는다 |
| `stage1_done` | 없음 | 두 행을 만들고 `input_completed_at`을 찍는다. **2단계 작업을 SQS에 넣는다** (전이 7). 상태는 워커가 바꾼다 |
| `stage1_done` | 있음 | 409 `INVALID_STATE`. 2단계 작업을 이미 넣었다 (아래) |
| 그 밖 | | 409 `INVALID_STATE` |

- **고칠 수 있는 구간은 1단계가 끝나기 전까지다.** `stage1_done`에서 저장하면 그 요청이 곧바로 2단계 작업을 SQS에 넣으므로, 그 뒤에 고치면 워커가 이미 옛 값으로 계산을 시작했을 수 있다. 두 번째 저장을 받아 주면 조용히 어긋나므로 거절한다 (D-49).
- 화면은 9번 응답의 `status`와 `input_done`으로 [다시 입력] 버튼을 보일지 정한다 (5.5, 07장).

**백엔드가 하는 일** (D-46)

```
트랜잭션 시작
  1) SELECT status, input_completed_at FROM analysis_jobs
      WHERE video_id = :video_id FOR UPDATE          -- 행을 잠근다
     → 위 표에 없는 경우면 롤백하고 409 INVALID_STATE (message에 현재 상태)
  2) INSERT INTO vehicle_selections ... ON CONFLICT (analysis_job_id)
       DO UPDATE SET still_frame_id=..., schema_version=..., payload=..., updated_at=now()
  3) INSERT INTO damage_inputs ...  (같은 방법)
  4) 처음 저장이면
       UPDATE analysis_jobs SET input_completed_at = now(), updated_at = now(),
              status = CASE WHEN status = 'stage1_running' THEN 'stage1_input_done' ELSE status END
        WHERE id = :job_id
  5) 1)에서 상태가 stage1_done이었으면
       SQS에 {"job_id": 42, "kind": "stage2"} 넣기 → 실패하면 롤백하고 500 INTERNAL_ERROR
커밋
6) 5)를 했으면 GPU EC2 켜기를 요청한다. 실패해도 200이다 (D-15, D-42)
```

- 1)의 `FOR UPDATE`가 이 API의 핵심이다. 워커도 같은 행의 상태를 조건부로 바꾸므로(4.4), 잠그지 않으면 "1단계가 끝나는 순간에 저장"이 워커의 전이와 엇갈려 2단계가 두 번 시작되거나 한 번도 시작되지 않을 수 있다. 잠그면 둘 중 하나가 먼저 끝나고, 나중 쪽은 바뀐 상태를 보고 위 표대로 판단한다.
- 두 입력을 **한 트랜잭션에서** 쓰므로 "차량만 저장되고 파손 부위가 없는" 행이 남지 않는다 (D-36).
- 저장된 입력을 **돌려주는 API는 두지 않는다.** 다시 입력할 때는 처음부터 두 번 드래그한다. 화면이 이전 사각형을 다시 그려 주려면 `GET /api/videos/{video_id}/input`을 더하면 되고, 읽기만 하는 API라 다른 곳에 영향이 없다 (D-49).

실패

| HTTP | `code` | 언제 | 프론트 처리 |
|---|---|---|---|
| 404 | `VIDEO_NOT_FOUND` | 없는 영상이거나 남의 영상 | 목록으로 |
| 409 | `INVALID_STATE` | 위 표의 마지막 두 줄. `message`에 현재 상태를 적는다 | 상태를 다시 조회해(9번) 화면을 새로 그린다 |
| 422 | `VALIDATION_FAILED` | 위 검증 규칙에 어긋남 | 다시 그리게 한다 |
| 500 | `INTERNAL_ERROR` | SQS에 넣지 못함. 아무것도 저장되지 않았다 | 잠시 후 다시 보낸다 |

## 5.8 후보 묶음 조회·[다음] API

후보 묶음(최대 10건, 01장 1.6)을 보여주고, [다음] 한 번으로 묶음 전체를 "못 찾음"으로 넘긴다 (D-37).

### 12. `GET /api/videos/{video_id}/batch` 지금 묶음 조회

요청 본문 없음. **후보 확인 화면을 열 때와, 재생 URL이 만료됐을 때 부른다** (D-41).

성공: `200`

```json
{
  "batch_no": 1,
  "candidates": [
    {"candidate_clip_id": 1187, "rank": 1,
     "start_sec": 13235.0, "end_sec": 13265.0, "incident_at_sec": 13250.0,
     "clip_url": "https://<prefix>-masked.s3.ap-northeast-2.amazonaws.com/videos/17/clips/1187.mp4?X-Amz-Algorithm=..."},
    {"candidate_clip_id": 1188, "rank": 2,
     "start_sec": 51102.0, "end_sec": 51132.0, "incident_at_sec": 51117.0,
     "clip_url": "https://...clips/1188.mp4?X-Amz-Algorithm=..."}
  ],
  "remaining": 23
}
```

| 키 | 뜻 |
|---|---|
| `batch_no` | 지금 묶음 번호. 1부터. 13번을 부를 때 그대로 돌려보낸다 |
| `candidate_clip_id` | 고정할 때 14번에 보내는 번호 (D-35) |
| `rank` | 점수순 순위. 배열은 이 순서로 정렬돼 있다 |
| `start_sec`·`end_sec` | 클립이 원본 영상의 어느 구간인지 (04장 4.7) |
| `incident_at_sec` | 사건 지점의 원본 시간. 클립 안에서의 위치는 `incident_at_sec − start_sec`다 |
| `clip_url` | 마스킹본 클립의 재생용 URL. 유효 시간 15분 (D-41) |
| `remaining` | [다음]을 누르면 더 볼 수 있는 후보 수. `0`이면 이번이 마지막 묶음이다 |

- **VLM 점수는 돌려주지 않는다.** 배열 순서가 곧 점수순이다. 점수를 보여주면 사용자가 영상 대신 숫자를 보고 판단하게 되는데, 이 화면의 목적은 사용자가 직접 확인하는 것이다(PRD 3.5). KPI 집계(09장)는 DB에서 읽는다.
- **후보 번호(`candidates.id`)도 돌려주지 않는다.** 고정 API가 클립 번호만 받기 때문이다 (D-35).
- `incident_at_sec`는 `judged_at_sec + 5초`(01장 1.6)를 백엔드가 계산한 값이다. 프론트가 상수를 알 필요가 없다. 판정 시점은 돌려주지 않는다.
- 후보 하나에 클립이 여러 개면(다시 만든 경우, D-32) **가장 최근 것 하나**를 준다.

```sql
SELECT DISTINCT ON (d.id)
       d.rank, d.judged_at_sec, c.id AS clip_id, c.start_sec, c.end_sec, c.masked_s3_key
  FROM candidates d
  JOIN candidate_clips c ON c.candidate_id = d.id AND c.status = 'done'
 WHERE d.analysis_job_id = :job_id
   AND d.batch_no = (SELECT max(batch_no) FROM candidates WHERE analysis_job_id = :job_id)
 ORDER BY d.id, c.id DESC;      -- 후보마다 가장 최근 클립 1개. 바깥에서 rank로 다시 정렬한다
```

- **클립을 만들지 못한 후보는 목록에서 빠진다.** 위 SQL이 `c.status = 'done'`인 클립만 고르기 때문이다. 묶음이 10건이 아니라 9건으로 보일 수 있다. 워커는 다시 만들지 않고, 응답에도 따로 알리지 않는다. 드문 경우라 받아들인다 (D-51).
- `remaining`은 아직 묶음에 들어가지 않은 후보 수다. 이번 묶음의 후보는 세지 않는다.

```sql
SELECT count(*) FROM candidates
 WHERE analysis_job_id = :job_id AND verdict = 'unseen' AND batch_no IS NULL;
```

- **이 API는 빈 배열을 돌려주지 않는다.** 후보가 0건이면 워커가 `ready`를 거치지 않고 바로 `exhausted`로 보내므로(04장 전이 14), 이 API는 409를 돌려준다. 화면은 9번의 `status`와 `candidate_total`을 보고 "후보 구간이 탐지되지 않았다"를 띄운다. 사건이 없다는 뜻이 아니다 (PRD 3.5, D-50).
- 이전 묶음을 다시 보는 조회는 두지 않는다. 필요해지면 `?batch_no=1`을 받아 같은 응답을 돌려주면 된다 (🚧 07장, D-37).

실패

| HTTP | `code` | 언제 | 프론트 처리 |
|---|---|---|---|
| 404 | `VIDEO_NOT_FOUND` | 없는 영상이거나 남의 영상 | 목록으로 |
| 409 | `MASKED_EXPIRED` | 보관 기간이 끝나 마스킹본이 파기됐다(D-57). `message`에 파기 시각을 적는다 | 9번을 다시 불러 "보관 기간 종료" 안내문으로 바꾼다 |
| 409 | `INVALID_STATE` | `status`가 `ready`가 아님(분석 중, 다음 묶음 만드는 중, 이미 고정함, 전부 확인함). `message`에 현재 상태를 적는다 | 상태를 다시 조회해(9번) 맞는 화면으로 간다 |

### 13. `POST /api/videos/{video_id}/batch/next` [다음] (묶음 전체 "못 찾음")

요청

```json
{"batch_no": 1}
```

성공: `200`

```json
{"status": "batch_running", "remaining": 13}
```

- 남은 후보가 없었으면 `{"status": "exhausted", "remaining": 0}`이다. 화면은 "후보 전부 확인 완료"를 보여준다 (PRD 3.6).
- **요청에 지금 보고 있는 묶음 번호를 함께 보낸다.** 화면이 오래돼 이미 다음 묶음으로 넘어간 뒤에 [다음]을 누르면, 사용자가 보지도 않은 묶음이 "못 찾음"이 된다. 번호가 다르면 409로 막는다.

**백엔드가 하는 일** (전이 10·12, D-37, D-46)

```
트랜잭션 시작
  0) 원본이 파기됐으면(videos.raw_deleted_at이 차 있음) 롤백하고 409 RAW_EXPIRED   (D-52)
  1) SELECT status FROM analysis_jobs WHERE video_id = :video_id FOR UPDATE
     → ready가 아니면 롤백하고 409 INVALID_STATE
     → 요청의 batch_no가 max(batch_no)와 다르면 롤백하고 409 INVALID_STATE
  2) UPDATE candidates SET verdict = 'not_found', verdict_at = now()
      WHERE analysis_job_id = :job_id AND batch_no = :batch_no AND verdict = 'unseen'
  3) 남은 후보 수를 센다 (12번의 count 쿼리)
     > 0 → UPDATE analysis_jobs SET status = 'batch_running', updated_at = now()  (전이 10)
           SQS에 {"job_id": 42, "kind": "next_batch"} 넣기
             → 실패하면 롤백하고 500 INTERNAL_ERROR
     = 0 → UPDATE analysis_jobs SET status = 'exhausted', updated_at = now()      (전이 12)
커밋
4) batch_running이면 GPU EC2 켜기를 요청한다. 실패해도 200이다 (D-42)
```

- 2)의 `verdict_at`은 묶음 후보 전부가 같은 값이다 (04장 `candidates`). 클립을 만들지 못해 화면에 나오지 않은 후보도 같이 `not_found`가 된다. 그 후보만 골라 남길 방법이 없고, 남겨 두면 `remaining`이 줄지 않아 `exhausted`에 이르지 못한다 (D-51).
- 같은 묶음 번호로 요청이 동시에 두 번 와도 1)의 `FOR UPDATE`와 `WHERE status = 'ready'` 조건 때문에 한쪽만 처리된다. 다른 쪽은 409를 받고 다시 조회한다. 프론트는 첫 요청을 보낸 뒤 버튼을 막는다.
- **0)이 필요한 이유는 프론트를 믿을 수 없기 때문이다.** 화면은 9번의 `raw_deleted`를 보고 버튼을 감추지만, 그 값은 마지막 조회 시점의 것이다. 화면을 열어 둔 사이에 원본이 파기되면 낡은 화면에 버튼이 남아 있다. 서버가 막지 않으면 SQS에 작업이 들어가고, 워커가 원본을 찾지 못해 `failed`가 된다 — 보관 기간이 지난 것이 "분석 실패"로 보인다.
  - 이 검사에 추가 조회는 없다. `videos` 행은 소유자 확인(5.1)을 위해 이미 읽은 상태다.
- `next_batch` 메시지에 묶음 번호를 넣지 않는다. 워커가 `max(batch_no) + 1`을 계산한다 (04장 4.6).
- [다음]을 누른 뒤 다음 묶음이 바로 나오지 않는다. `batch_running` 동안 클립을 비식별화하고, GPU가 꺼져 있었으면 부팅이 더해진다. 화면은 9번으로 `ready`가 될 때까지 기다린다 (07장).

실패

| HTTP | `code` | 언제 | 프론트 처리 |
|---|---|---|---|
| 404 | `VIDEO_NOT_FOUND` | 없는 영상이거나 남의 영상 | 목록으로 |
| 409 | `INVALID_STATE` | `ready`가 아니거나, 보낸 `batch_no`가 지금 묶음이 아님. `message`에 현재 상태와 묶음 번호를 적는다 | 12번을 다시 불러 화면을 새로 그린다 |
| 409 | `RAW_EXPIRED` | 원본이 파기돼(D-52) 다음 묶음을 만들 수 없음. `message`에 파기 시각을 적는다 | 9번을 다시 불러 안내문으로 바꾼다. 지금 묶음은 계속 볼 수 있다 |
| 422 | `VALIDATION_FAILED` | `batch_no`가 없거나 1보다 작음 | |
| 500 | `INTERNAL_ERROR` | SQS에 넣지 못함. 아무것도 바뀌지 않았다 | 잠시 후 다시 보낸다 |

## 5.9 사건 지점 고정 API

"찾음"은 `pinned_incidents` 행 하나로만 기록한다. 파일을 복사하지 않는다 (D-32, D-35). 해제 API는 두지 않는다 (D-40).

### 14. `POST /api/videos/{video_id}/pin` 사건 지점 고정

요청

```json
{"candidate_clip_id": 1187}
```

- 12번 응답의 `candidate_clip_id`를 그대로 보낸다. 후보 번호는 받지 않는다. 두 번호를 따로 받으면 서로 다른 후보를 가리킬 수 있기 때문이다 (D-35).
- 화면은 보내기 전에 확인창을 띄운다. 고정은 되돌릴 수 없다 (D-40, 07장).

성공: `200` — 본문은 **15번과 같다.** 화면이 이어서 15번을 부르지 않아도 결과 화면을 그릴 수 있다.

**백엔드가 하는 일** (전이 9, D-35)

```
트랜잭션 시작
  1) UPDATE analysis_jobs SET status = 'pinned', updated_at = now()
      WHERE id = :job_id AND status = 'ready'
     → 0행이면 롤백하고 409 INVALID_STATE
  2) 클립 확인: 이 작업의 클립인가, status가 done인가 (04장 pinned_incidents의 쿼리)
     → 없으면 롤백하고 404 CLIP_NOT_FOUND
  3) INSERT INTO pinned_incidents (analysis_job_id, candidate_clip_id)
커밋
```

- **한 트랜잭션인 것이 이 API의 조건이다.** 중간에 실패하면 둘 다 취소되므로 "상태는 `pinned`인데 고정 행이 없는" 경우가 생기지 않는다 (D-35).
- 2)의 확인이 빠지면 남의 클립 번호로 고정해 그 재생 URL을 받을 수 있다. FK는 클립이 있는지만 볼 뿐 어느 작업의 것인지는 보지 않는다 (D-35).
- 이전 묶음의 클립 번호로도 고정된다(`verdict`가 `not_found`여도 막지 않는다). "이전 묶음으로 돌아가 다시 보기"(🚧 07장, D-37)가 정해지면 함께 정한다.
- SQS에 넣지 않고 GPU도 켜지 않는다. `pinned`는 끝 상태라 뒤에 할 일이 없다.

실패

| HTTP | `code` | 언제 | 프론트 처리 |
|---|---|---|---|
| 404 | `VIDEO_NOT_FOUND` | 없는 영상이거나 남의 영상 | 목록으로 |
| 404 | `CLIP_NOT_FOUND` | 이 작업의 클립이 아니거나, 없거나, `status`가 `done`이 아님 | 12번을 다시 불러 화면을 새로 그린다 |
| 409 | `INVALID_STATE` | `ready`가 아님(이미 고정했거나 다음 묶음을 만드는 중). `message`에 현재 상태를 적는다 | 상태를 다시 조회한다(9번) |

### 15. `GET /api/videos/{video_id}/pin` 고정된 사건 지점 조회

요청 본문 없음. 결과 화면을 열 때와, 재생 URL이 만료됐을 때 부른다 (D-41).

성공: `200`

```json
{"candidate_clip_id": 1187,
 "start_sec": 13235.0, "end_sec": 13265.0, "incident_at_sec": 13250.0,
 "clip_url": "https://<prefix>-masked.s3.ap-northeast-2.amazonaws.com/videos/17/clips/1187.mp4?X-Amz-Algorithm=...",
 "pinned_at": "2026-09-20T15:20:11+09:00"}
```

| 키 | 뜻 |
|---|---|
| `start_sec`·`end_sec` | **경찰에게 넘길 값.** 고정한 클립이 원본 영상의 어느 구간인지 (PRD 3.6, 불변 조건 7) |
| `incident_at_sec` | 사건 지점의 원본 시간. 클립 안에서의 위치는 `incident_at_sec − start_sec`다 |
| `clip_url` | 마스킹본 클립의 재생용 URL. 유효 시간 15분 (D-41) |

- 세 시간 값은 모두 원본 영상 시작부터의 초다. `03:40:35` 같은 표시 형식은 07장에서 정한다.
- 값은 고정한 클립 행에서 읽는다. `pinned_incidents`에는 복사해 두지 않는다 (D-32, 04장의 JOIN 쿼리). `incident_at_sec`는 그 클립의 후보에서 `judged_at_sec + 5초`로 계산한다.
- **다운로드 링크는 주지 않는다.** `clip_url`은 `<video>`가 재생하는 URL이고, 화면에 다운로드 버튼을 두지 않는다 (불변 조건 8, PRD 3.6).
- 다시 접속해도 같은 값이 나온다. `pinned`는 끝 상태라 바뀌지 않는다.
- **단, 업로드 완료에서 30일이 지나면 클립이 파기돼 이 API도 409가 된다** (D-57). 고정 결과를 볼 수 있는 기간은 30일이다.

실패

| HTTP | `code` | 언제 | 프론트 처리 |
|---|---|---|---|
| 404 | `VIDEO_NOT_FOUND` | 없는 영상이거나 남의 영상 | 목록으로 |
| 409 | `MASKED_EXPIRED` | 보관 기간이 끝나 클립이 파기됐다(D-57). `message`에 파기 시각을 적는다 | 9번을 다시 불러 "보관 기간 종료" 안내문으로 바꾼다 |
| 409 | `INVALID_STATE` | 아직 고정하지 않음(`pinned`가 아님). `message`에 현재 상태를 적는다 | 상태를 다시 조회해(9번) 맞는 화면으로 간다 |

## 5.10 이 장에서 미정으로 남는 것

| 항목 | 어디서 정하나 |
|---|---|
| `code`별 한국어 문구, 상태별 화면 문구 | 07장 (U-15) |
| 화면 상태 조회 주기(5~10초) | U-18 → 정해지면 01장 1.6 |
| 쿠키 `SameSite` 속성, `token` 만드는 방법, 비밀번호 해시 | 08장 |
| 워커가 후보 0건일 때 2단계를 끝내는 방법 (상태는 D-50) | 06장 |
| 이전 묶음을 다시 보는 조회(`?batch_no=`) | 07장에서 필요해지면 (D-37) |
| 저장된 입력을 돌려주는 `GET .../input` | 07장에서 필요해지면 (D-49) |
| `schema_version` 2의 검증 규칙 | U-13이 정해진 뒤 (D-25) |
| 멀티파트 업로드로 바꿀 때 더할 API | 실제 운영 전환 시 ([D-22](11-decisions.md#d-22-업로드는-단일-put으로-구현하고-실제-운영에서는-멀티파트로-바꾼다)의 할 일 목록) |

## 관련 결정·조건

- 불변 조건 1(원본 재생 URL 미노출), 8(다운로드 기능 없음): [02장 2.4](02-architecture.md#24-이중-경로와-불변-조건)
- 프론트와 API는 같은 출처이며 프론트는 상대경로 `/api/...`로 호출한다: D-11
- API는 분석을 하지 않는다: D-14
- 작업 전달은 SQS, 상태는 DB: D-16
- presigned URL 직접 업로드: D-18 / 단일 PUT과 멀티파트 전환: D-22
- 관리자는 계정 없이 업로드 전용 일회용 링크로 올린다: D-28
- 차량·파손 부위 입력은 두 번 드래그: D-29 / 방향은 워커가 계산: D-34 / 우선 누끼 없이 한 번에 저장: D-36
- 후보마다 [찾음]만, 묶음 단위 [다음]이 "못 찾음": D-37
- 고정은 클립 행 참조, 고정 API의 작업 소유 확인: D-32, D-35
- 고정 해제 없음: D-40
- 에러 응답 형식: D-38
- presigned URL 유효 시간과 재생 URL 재발급: D-41
- GPU 켜기 실패 대비 5초 주기 점검: D-42
- 업로드 허용 형식(확장자·코덱): D-43
- 주소는 `video_id` 하나, 남의 영상은 404: D-39
- 회원가입 없음(계정은 스크립트로): D-44 / 업로드는 링크로만: D-45
- SQS에 넣는 API는 트랜잭션 안에서 넣고 커밋: D-46
- 대기 상태에 멈춘 작업은 5초 점검이 SQS에 다시 넣는다(DLQ·재시도 상한 없음): D-56
- 업로드 중·업로드 실패 상태는 조회할 때 계산: D-47
- 정지 장면은 시작 장면 1장, 1단계에서 만든다: D-48
- 입력 수정은 1단계가 끝나기 전까지, 상태 조회에 `input_done`: D-49
- 후보 0건이면 `exhausted`로 보내고 `candidate_total`로 구분: D-50
- 클립 생성에 실패한 후보는 이번 묶음에서 빠지고, 다시 만들지 않는다: D-51
- 원본 파기와 `raw_deleted`·`RAW_EXPIRED`: D-52 / 열람·파기 기록: D-53
- 마스킹본·분석 결과 파기와 `masked_deleted`·`MASKED_EXPIRED`: D-57
- 부하 대응(무거운 일 금지, 조회 주기, 무상태): D-19, [02장 2.12](02-architecture.md#212-부하-대응과-부하-테스트)
