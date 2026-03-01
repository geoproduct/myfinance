import os, json, base64

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _get_vapid_keys():
    """
    VAPID 키 로드 우선순위:
    1. 환경변수 VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY  ← Railway 배포 시
    2. .vapid_keys.json 파일                          ← 로컬 개발 시
    3. 새로 생성 후 파일 저장                          ← 최초 실행 시
    """
    # 1) 환경변수 우선 (Railway는 \n을 리터럴로 저장하므로 실제 줄바꿈으로 변환)
    env_priv = os.environ.get('VAPID_PRIVATE_KEY', '').replace('\\n', '\n')
    env_pub  = os.environ.get('VAPID_PUBLIC_KEY',  '')
    if env_priv and env_pub:
        return {'private_key': env_priv, 'public_key': env_pub}

    # 2) 파일
    keys_file = os.path.join(BASE_DIR, '.vapid_keys.json')
    if os.path.exists(keys_file):
        with open(keys_file) as f:
            return json.load(f)

    # 3) 새로 생성
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization

        priv = ec.generate_private_key(ec.SECP256R1(), default_backend())
        pub  = priv.public_key()

        priv_pem = priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()
        ).decode()

        pub_b64 = base64.urlsafe_b64encode(
            pub.public_bytes(serialization.Encoding.X962,
                             serialization.PublicFormat.UncompressedPoint)
        ).rstrip(b'=').decode()

        keys = {'private_key': priv_pem, 'public_key': pub_b64}
        try:
            with open(keys_file, 'w') as f:
                json.dump(keys, f)
        except OSError:
            pass  # read-only 파일시스템 (Railway 등) 무시
        return keys
    except Exception:
        return {'private_key': '', 'public_key': ''}


def _db_uri():
    """
    DB URI 결정:
    - DATABASE_URL 환경변수 있으면 PostgreSQL (Railway 자동 주입)
    - 없으면 SQLite (로컬 개발)
    Railway는 'postgres://' 형식을 주는데 SQLAlchemy는 'postgresql://' 필요
    """
    url = os.environ.get('DATABASE_URL', '')
    if url:
        # postgres:// → postgresql:// 변환
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        return url
    return 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'myfinance.db')


_vapid = _get_vapid_keys()


class Config:
    SECRET_KEY              = os.environ.get('SECRET_KEY', 'myfinance-secret-change-me!')
    SQLALCHEMY_DATABASE_URI = _db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'img')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    # ── Google OAuth ─────────────────────────────
    # Google Cloud Console → OAuth 2.0 클라이언트 ID 등록 필요
    # 승인된 리디렉션 URI: http://localhost:5001/auth/google/callback
    GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

    # ── Kakao OAuth ──────────────────────────────
    # developers.kakao.com → 앱 등록 후 REST API 키 입력
    # 플랫폼 → Web → 사이트 도메인: http://localhost:5001
    # Redirect URI: http://localhost:5001/auth/kakao/callback
    KAKAO_CLIENT_ID     = os.environ.get('KAKAO_CLIENT_ID', '')
    KAKAO_CLIENT_SECRET = os.environ.get('KAKAO_CLIENT_SECRET', '')

    # ── VAPID (Web Push) ─────────────────────────
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', _vapid.get('private_key', ''))
    VAPID_PUBLIC_KEY  = os.environ.get('VAPID_PUBLIC_KEY',  _vapid.get('public_key', ''))
    VAPID_CLAIMS      = {'sub': 'mailto:admin@myfinance.kr'}

    # ── 오픈뱅킹 (금융결제원 API 신청 후 발급) ────
    OPENBANKING_CLIENT_ID     = os.environ.get('OPENBANKING_CLIENT_ID', '')
    OPENBANKING_CLIENT_SECRET = os.environ.get('OPENBANKING_CLIENT_SECRET', '')
    OPENBANKING_BASE_URL      = 'https://testapi.openbanking.or.kr'
