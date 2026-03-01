"""
오픈뱅킹 Mock 구현
- 실제 금융결제원 오픈뱅킹 API는 API 신청 + 심사 필요 (수개월)
- 이 모듈은 UI/UX 플로우를 완전히 구현하고, 실제 API 연결을 위한 구조를 제공합니다
- OPENBANKING_CLIENT_ID/SECRET 설정 시 실제 테스트 API 연결 가능
"""
import random, string
from datetime import date, datetime, timedelta
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, current_app)
from flask_login import login_required, current_user
from models import db, LinkedAccount, Transaction, Category, BANKS

openbanking_bp = Blueprint('openbanking', __name__)

# 은행별 Mock 데이터
MOCK_MERCHANTS = {
    '식비':       ['스타벅스', '맥도날드', '이디야커피', 'CU편의점', '마켓컬리', '배달의민족'],
    '교통':       ['T-money', '카카오T', '주유소', 'KTX', '버스'],
    '쇼핑':       ['쿠팡', '네이버쇼핑', 'G마켓', '올리브영', 'H&M'],
    '카페/간식':  ['스타벅스', '투썸플레이스', '메가커피', '빽다방'],
    '의료/건강':  ['약국', '병원', '헬스장', '필라테스'],
    '문화/여가':  ['CGV', '롯데시네마', '멜론', '넷플릭스'],
    '통신':       ['SKT', 'KT', 'LG U+'],
}

AMOUNT_RANGE = {
    '식비':       (3000, 30000),
    '교통':       (1300, 50000),
    '쇼핑':       (5000, 200000),
    '카페/간식':  (2000, 8000),
    '의료/건강':  (5000, 80000),
    '문화/여가':  (5000, 50000),
    '통신':       (30000, 80000),
}


def _mask_account(num):
    """계좌번호 마스킹"""
    return f"****-****-{num[-4:]}"


def _gen_account_num():
    return ''.join(random.choices(string.digits, k=12))


# ── 메인 페이지 ───────────────────────────────────
@openbanking_bp.route('/')
@login_required
def index():
    linked = LinkedAccount.query.filter_by(user_id=current_user.id).all()
    return render_template('openbanking/index.html',
                           linked=linked, banks=BANKS)


# ── 계좌 연결 (Mock) ──────────────────────────────
@openbanking_bp.route('/link', methods=['POST'])
@login_required
def link_account():
    bank_code    = request.form.get('bank_code', '')
    account_type = request.form.get('account_type', 'checking')

    if bank_code not in BANKS:
        flash('지원하지 않는 은행입니다.', 'danger')
        return redirect(url_for('openbanking.index'))

    # 같은 은행 중복 연결 방지 (계좌별로는 가능)
    bank_icon, bank_name = BANKS[bank_code]
    acc_num = _gen_account_num()

    # Mock 잔액
    balance = random.randint(500_000, 30_000_000)

    a = LinkedAccount(
        user_id=current_user.id,
        bank_code=bank_code,
        bank_name=bank_name,
        account_type=account_type,
        account_num=_mask_account(acc_num),
        balance=balance,
        last_sync=None,
    )
    db.session.add(a)
    db.session.commit()
    flash(f'✅ {bank_name} 계좌 연결 완료! (잔액: {balance:,.0f}원)', 'success')
    return redirect(url_for('openbanking.index'))


# ── 거래내역 동기화 (Mock) ────────────────────────
@openbanking_bp.route('/sync/<int:aid>', methods=['POST'])
@login_required
def sync_account(aid):
    acc = LinkedAccount.query.filter_by(id=aid, user_id=current_user.id).first_or_404()

    # 실제 API 연결 가능 여부 확인
    if current_app.config.get('OPENBANKING_CLIENT_ID'):
        # TODO: 실제 오픈뱅킹 API 호출
        # access_token = _get_openbanking_token()
        # transactions = _fetch_transactions(acc, access_token)
        pass

    # Mock: 최근 30일 랜덤 거래 생성 (중복 방지: 이미 sync된 경우 7일만)
    last = acc.last_sync
    days = 30 if not last else max(1, (datetime.utcnow() - last).days + 1)
    days = min(days, 30)

    cats   = Category.query.filter(
        (Category.user_id == current_user.id) | (Category.is_default == True),
        Category.type == 'expense'
    ).all()

    count = 0
    today = date.today()
    for _ in range(random.randint(10, 25)):
        d    = today - timedelta(days=random.randint(0, days - 1))
        cat  = random.choice(cats)
        lo, hi = AMOUNT_RANGE.get(cat.name, (5000, 50000))
        amt  = random.randint(lo, hi)
        merchants = MOCK_MERCHANTS.get(cat.name, ['기타결제'])
        desc = f"[{acc.bank_name}] {random.choice(merchants)}"
        db.session.add(Transaction(
            user_id=current_user.id, amount=amt, type='expense',
            category_id=cat.id, description=desc, date=d,
            memo=f"계좌연동 자동수집"
        ))
        count += 1

    # 잔액 약간 변동
    acc.balance = max(0, acc.balance - random.randint(10_000, 200_000))
    acc.last_sync = datetime.utcnow()
    db.session.commit()
    flash(f'🔄 {acc.bank_name} 동기화 완료 — 거래 {count}건 추가됨', 'success')
    return redirect(url_for('openbanking.index'))


# ── 계좌 연결 해제 ────────────────────────────────
@openbanking_bp.route('/unlink/<int:aid>', methods=['POST'])
@login_required
def unlink_account(aid):
    acc = LinkedAccount.query.filter_by(id=aid, user_id=current_user.id).first_or_404()
    name = acc.bank_name
    db.session.delete(acc)
    db.session.commit()
    flash(f'{name} 계좌 연결이 해제되었습니다.', 'info')
    return redirect(url_for('openbanking.index'))


# ── 잔액 조회 (AJAX) ──────────────────────────────
@openbanking_bp.route('/balance/<int:aid>')
@login_required
def get_balance(aid):
    acc = LinkedAccount.query.filter_by(id=aid, user_id=current_user.id).first_or_404()
    # Mock: 소폭 변동
    acc.balance += random.randint(-50000, 50000)
    if acc.balance < 0:
        acc.balance = 0
    db.session.commit()
    return jsonify(balance=acc.balance, account_num=acc.account_num)
