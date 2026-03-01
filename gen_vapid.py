"""
Railway 배포 시 사용할 VAPID 키 생성 스크립트
실행: python gen_vapid.py
출력된 값을 Railway Variables에 복사하세요
"""
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

priv = ec.generate_private_key(ec.SECP256R1(), default_backend())
pub  = priv.public_key()

priv_pem = priv.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption()
).decode().strip()

pub_b64 = base64.urlsafe_b64encode(
    pub.public_bytes(serialization.Encoding.X962,
                     serialization.PublicFormat.UncompressedPoint)
).rstrip(b'=').decode()

print("=" * 60)
print("Railway Variables에 아래 값을 복사하세요:")
print("=" * 60)
print(f"\nVAPID_PUBLIC_KEY={pub_b64}\n")
print(f"VAPID_PRIVATE_KEY={priv_pem}")
print("=" * 60)
