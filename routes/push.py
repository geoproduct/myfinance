"""
웹 푸시 알림 (Web Push Protocol + VAPID)
- 별도의 Firebase 없이 브라우저 내장 Push API 사용
- pywebpush 라이브러리로 서버→브라우저 푸시 전송
"""
import json
from flask import (Blueprint, request, jsonify, current_app)
from flask_login import login_required, current_user
from models import db, PushSubscription

push_bp = Blueprint('push', __name__)


# ── VAPID 공개키 조회 ─────────────────────────────
@push_bp.route('/vapid-public-key')
def vapid_public_key():
    key = current_app.config.get('VAPID_PUBLIC_KEY', '')
    return jsonify(publicKey=key)


# ── 구독 저장 ─────────────────────────────────────
@push_bp.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    data     = request.get_json()
    endpoint = data.get('endpoint', '')
    keys     = data.get('keys', {})
    p256dh   = keys.get('p256dh', '')
    auth_key = keys.get('auth', '')

    if not endpoint:
        return jsonify(error='endpoint missing'), 400

    # 이미 등록된 경우 업데이트
    sub = PushSubscription.query.filter_by(
        user_id=current_user.id, endpoint=endpoint).first()
    if sub:
        sub.p256dh   = p256dh
        sub.auth_key = auth_key
    else:
        sub = PushSubscription(
            user_id=current_user.id,
            endpoint=endpoint, p256dh=p256dh, auth_key=auth_key)
        db.session.add(sub)
    db.session.commit()
    return jsonify(ok=True)


# ── 구독 해제 ─────────────────────────────────────
@push_bp.route('/unsubscribe', methods=['POST'])
@login_required
def unsubscribe():
    data     = request.get_json()
    endpoint = data.get('endpoint', '')
    PushSubscription.query.filter_by(
        user_id=current_user.id, endpoint=endpoint).delete()
    db.session.commit()
    return jsonify(ok=True)


# ── 테스트 푸시 전송 ──────────────────────────────
@push_bp.route('/test', methods=['POST'])
@login_required
def test_push():
    _send_push(current_user.id,
               title='MyFinance 알림 테스트 🔔',
               body='푸시 알림이 정상 작동합니다!')
    return jsonify(ok=True)


# ── 내부 함수: 푸시 전송 ──────────────────────────
def _send_push(user_id, title, body, url='/'):
    from pywebpush import webpush, WebPushException

    private_key = current_app.config.get('VAPID_PRIVATE_KEY', '')
    claims      = current_app.config.get('VAPID_CLAIMS', {})
    if not private_key:
        return

    subs = PushSubscription.query.filter_by(user_id=user_id).all()
    payload = json.dumps({'title': title, 'body': body, 'url': url})
    dead = []

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth_key}
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=claims,
            )
        except WebPushException as e:
            # 410 Gone = 구독 만료
            if '410' in str(e) or '404' in str(e):
                dead.append(sub.id)

    if dead:
        PushSubscription.query.filter(PushSubscription.id.in_(dead)).delete()
        db.session.commit()
