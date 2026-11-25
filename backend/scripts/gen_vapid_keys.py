"""웹 푸시 VAPID 키를 만들어 .env에 붙일 줄로 출력한다 (D-348).

    uv run python -m scripts.gen_vapid_keys

로컬은 PC마다 따로 만든다. 배포 키는 GitHub Secrets에만 넣고 로컬에 복사하지 않는다.
키를 바꾸면 push_subscriptions를 모두 지운다 (08장).
"""

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from py_vapid.utils import b64urlencode

vapid = Vapid()
vapid.generate_keys()
private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
public = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
print(f"VAPID_PRIVATE_KEY={b64urlencode(private)}")
print(f"VAPID_PUBLIC_KEY={b64urlencode(public)}")
