"""계정 만들기 (08장 8.2). 실행: uv run python -m scripts.create_user --login-id victim1 --name 홍길동"""

import argparse
import getpass
import sys

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db import get_engine
from app.security import MAX_PASSWORD_BYTES, hash_password


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--login-id", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    # 비밀번호는 명령행 인자로 받지 않는다 (셸 기록과 ps에 남는다)
    password = getpass.getpass("Password: ")
    if not password:
        sys.exit("password is empty")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        sys.exit(f"password is longer than {MAX_PASSWORD_BYTES} bytes")

    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("INSERT INTO users (login_id, password_hash, name) VALUES (:l, :p, :n)"),
                {"l": args.login_id, "p": hash_password(password), "n": args.name},
            )
    except IntegrityError:
        sys.exit(f"login id already exists: {args.login_id}")
    print(f"created user {args.login_id}")


if __name__ == "__main__":
    main()
