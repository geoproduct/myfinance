from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, Asset, AssetSnapshot, LinkedAccount
from sqlalchemy import func
from datetime import date, datetime

assets_bp = Blueprint('assets', __name__)

TYPES = {
    'bank':        ('🏦', '예금/저축'),
    'stock':       ('📈', '주식/ETF'),
    'crypto':      ('₿',  '가상자산'),
    'cash':        ('💵', '현금/외화'),
    'real_estate': ('🏠', '부동산'),
    'insurance':   ('🛡️', '보험'),
    'other':       ('📦', '기타'),
}
RATES = {'KRW':1,'USD':1380,'JPY':9.2,'EUR':1500,'CNY':190}


def to_krw(a):
    return a.amount * RATES.get(a.currency, 1)


@assets_bp.route('/')
@login_required
def index():
    assets  = Asset.query.filter_by(user_id=current_user.id)\
                   .order_by(Asset.type, Asset.name).all()
    linked  = LinkedAccount.query.filter_by(user_id=current_user.id).all()
    linked_total = sum(a.balance for a in linked)
    total   = sum(to_krw(a) for a in assets) + linked_total

    by_type = {}
    for a in assets:
        by_type.setdefault(a.type, []).append(a)

    summary = []
    for t, lst in by_type.items():
        s = sum(to_krw(a) for a in lst)
        icon, label = TYPES.get(t, ('📦', t))
        pct = int(s / total * 100) if total > 0 else 0
        summary.append({'type': t, 'icon': icon, 'label': label,
                        'total': s, 'pct': pct, 'assets': lst})

    snaps = AssetSnapshot.query.filter_by(user_id=current_user.id)\
                .order_by(AssetSnapshot.month).limit(12).all()

    # JSON 직렬화용
    summary_j = [{'label':x['label'],'icon':x['icon'],
                  'total':x['total'],'pct':x['pct']} for x in summary]
    snaps_j   = [{'month':s.month,'total':s.total_krw} for s in snaps]
    types_j   = {k:{'icon':v[0],'label':v[1]} for k,v in TYPES.items()}

    return render_template('assets/index.html',
        assets=assets, total=total, summary=summary,
        summary_j=summary_j, snaps_j=snaps_j, types_j=types_j,
        types=TYPES, currencies=list(RATES.keys()),
        linked=linked, linked_total=linked_total)


@assets_bp.route('/add', methods=['POST'])
@login_required
def add():
    try:
        amount = float(request.form.get('amount','0').replace(',',''))
    except ValueError:
        flash('금액 오류', 'danger')
        return redirect(url_for('assets.index'))
    a = Asset(user_id=current_user.id,
              name=request.form.get('name','').strip(),
              type=request.form.get('type','other'),
              amount=amount,
              currency=request.form.get('currency','KRW'),
              bank_name=request.form.get('bank_name','').strip(),
              note=request.form.get('note','').strip())
    db.session.add(a)
    db.session.commit()
    _snap()
    flash('자산이 추가되었습니다.', 'success')
    return redirect(url_for('assets.index'))


@assets_bp.route('/edit/<int:aid>', methods=['POST'])
@login_required
def edit(aid):
    a = Asset.query.filter_by(id=aid, user_id=current_user.id).first_or_404()
    try:
        a.amount = float(request.form.get('amount','0').replace(',',''))
    except ValueError:
        flash('금액 오류', 'danger')
        return redirect(url_for('assets.index'))
    a.name      = request.form.get('name','').strip()
    a.type      = request.form.get('type','other')
    a.currency  = request.form.get('currency','KRW')
    a.bank_name = request.form.get('bank_name','').strip()
    a.note      = request.form.get('note','').strip()
    a.updated_at= datetime.utcnow()
    db.session.commit()
    _snap()
    flash('수정되었습니다.', 'success')
    return redirect(url_for('assets.index'))


@assets_bp.route('/delete/<int:aid>', methods=['POST'])
@login_required
def delete(aid):
    a = Asset.query.filter_by(id=aid, user_id=current_user.id).first_or_404()
    db.session.delete(a); db.session.commit()
    _snap()
    flash('삭제되었습니다.', 'success')
    return redirect(url_for('assets.index'))


def _snap():
    ym    = date.today().strftime('%Y-%m')
    total = db.session.query(func.sum(Asset.amount))\
                      .filter_by(user_id=current_user.id).scalar() or 0
    s = AssetSnapshot.query.filter_by(user_id=current_user.id, month=ym).first()
    if s: s.total_krw = total
    else: db.session.add(AssetSnapshot(user_id=current_user.id, month=ym, total_krw=total))
    db.session.commit()
