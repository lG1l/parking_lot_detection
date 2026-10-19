import hashlib
import secrets
from functools import lru_cache

import bcrypt

BCRYPT_ROUNDS = 12  # 01장 1.6
MAX_PASSWORD_BYTES = 72  # bcrypt가 처리하는 상한 (08장 8.3)


def hash_password(plain: str) -> str:
    data = plain.encode("utf-8")
    if len(data) > MAX_PASSWORD_BYTES:
        raise ValueError("password is longer than 72 bytes")
    return bcrypt.hashpw(data, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    data = plain.encode("utf-8")
    if len(data) > MAX_PASSWORD_BYTES:
        return False  # 만들 수 없는 길이라 맞을 수 없다
    return bcrypt.checkpw(data, hashed.encode())


@lru_cache
def dummy_hash() -> str:
    # 없는 아이디도 bcrypt 비교를 한 번 하게 해 응답 시간으로 아이디 존재를 알 수 없게 한다
    return hash_password("dummy-password")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
