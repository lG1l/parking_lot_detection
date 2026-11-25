"""비밀번호 바꾸기 (08장 8.2). 실행: uv run python -m scripts.reset_password --login-id victim1"""

import argparse
import getpass
import sys

from sqlalchemy import text

from app.db import get_engine
from app.security import MAX_PASSWORD_BYTES, hash_password


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login-id", required=True)
    args = parser.parse_args()

    with get_engine().connect() as conn:
        user_id = conn.execute(
            text("SELECT id FROM users WHERE login_id = :l"), {"l": args.login_id}
        ).scalar_one_or_none()
    if user_id is None:
        sys.exit(f"no such login id: {args.login_id}")

    # 비밀번호는 명령행 인자로 받지 않는다 (셸 기록과 ps에 남는다)
    password = getpass.getpass("Password: ")
    if not password:
        sys.exit("password is empty")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        sys.exit(f"password is longer than {MAX_PASSWORD_BYTES} bytes")

    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE users SET password_hash = :p WHERE id = :i"),
            {"p": hash_password(password), "i": user_id},
        )
        # 비밀번호가 새서 바꾸는 경우를 위해 이미 로그인한 브라우저를 모두 끊는다
        conn.execute(text("DELETE FROM sessions WHERE user_id = :i"), {"i": user_id})
    print(f"password changed: {args.login_id}")


if __name__ == "__main__":
    main()
