from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from models import db, Transaction, Budget, Category, Asset, LinkedAccount
from sqlalchemy import func, desc
from datetime import date, timedelta
import calendar

dashboard_bp = Blueprint('dashboard', __name__)


def month_range(y, m):
    last = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last)


@dashboard_bp.route('/')
@login_required
def index():
    today = date.today()
    y, m  = today.year, today.month
    ym    = f'{y:04d}-{m:02d}'
    s, e  = month_range(y, m)

    # 이번달 수입/지출
    rows = (db.session.query(Transaction.type, func.sum(Transaction.amount))
            .filter(Transaction.user_id == current_user.id,
                    Transaction.date.between(s, e))
            .group_by(Transaction.type).all())
    inc = next((r[1] for r in rows if r[0] == 'income'),  0) or 0
    exp = next((r[1] for r in rows if r[0] == 'expense'), 0) or 0

    # 총 자산 (수동 등록 자산 + 오픈뱅킹 연결 계좌 잔액)
    asset_sum  = (db.session.query(func.sum(Asset.amount))
                  .filter_by(user_id=current_user.id).scalar() or 0)
    linked_sum = (db.session.query(func.sum(LinkedAccount.balance))
                  .filter_by(user_id=current_user.id).scalar() or 0)
    total_assets = asset_sum + linked_sum

    # 예산 현황
    budgets = Budget.query.filter_by(user_id=current_user.id, month=ym).all()
    budget_items = []
    for b in budgets:
        spent = (db.session.query(func.sum(Transaction.amount))
                 .filter(Transaction.user_id == current_user.id,
                         Transaction.category_id == b.category_id,
                         Transaction.type == 'expense',
                         Transaction.date.between(s, e)).scalar() or 0)
        pct = int(spent / b.amount * 100) if b.amount > 0 else 0
        budget_items.append({'b': b, 'spent': spent, 'pct': min(pct, 100)})

    # 최근 거래 5건
    recent = (Transaction.query
              .filter_by(user_id=current_user.id)
              .order_by(desc(Transaction.date), desc(Transaction.id))
              .limit(5).all())

    # 카테고리별 지출 (도넛)
    cat_rows = (db.session.query(Category.name, Category.color,
                                 func.sum(Transaction.amount).label('total'))
                .join(Transaction, Transaction.category_id == Category.id)
                .filter(Transaction.user_id == current_user.id,
                        Transaction.type == 'expense',
                        Transaction.date.between(s, e))
                .group_by(Category.id)
                .order_by(desc('total')).limit(6).all())
    cat_data = [{'name': r[0], 'color': r[1], 'total': float(r[2])} for r in cat_rows]

    # 최근 6개월 월별
    monthly = []
    for i in range(5, -1, -1):
        dt = (today.replace(day=1) - timedelta(days=i * 28))
        sy, sm = dt.year, dt.month
        ms, me = month_range(sy, sm)
        rs = (db.session.query(Transaction.type, func.sum(Transaction.amount))
              .filter(Transaction.user_id == current_user.id,
                      Transaction.date.between(ms, me))
              .group_by(Transaction.type).all())
        mi = next((r[1] for r in rs if r[0] == 'income'),  0) or 0
        me2= next((r[1] for r in rs if r[0] == 'expense'), 0) or 0
        monthly.append({'label': f'{sm}월', 'income': float(mi), 'expense': float(me2)})

    return render_template('dashboard/index.html',
        inc=inc, exp=exp, bal=inc - exp, total_assets=total_assets,
        budget_items=budget_items, recent=recent,
        cat_data=cat_data, monthly=monthly,
        today=today, ym=ym)


@dashboard_bp.route('/api/notif/read-all', methods=['POST'])
@login_required
def read_all():
    from models import Notification
    Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .update({'is_read': True})
    db.session.commit()
    return jsonify(ok=True)
