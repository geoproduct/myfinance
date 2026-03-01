from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, Budget, Transaction, Category
from sqlalchemy import func
from datetime import date
import calendar

budget_bp = Blueprint('budget', __name__)


def _month_range(y, m):
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


@budget_bp.route('/')
@login_required
def index():
    today = date.today()
    y = request.args.get('year',  today.year,  type=int)
    m = request.args.get('month', today.month, type=int)
    ym   = f'{y:04d}-{m:02d}'
    s, e = _month_range(y, m)

    budgets = Budget.query.filter_by(user_id=current_user.id, month=ym).all()
    items, tb, ts = [], 0, 0
    for b in budgets:
        spent = (db.session.query(func.sum(Transaction.amount))
                 .filter(Transaction.user_id == current_user.id,
                         Transaction.category_id == b.category_id,
                         Transaction.type == 'expense',
                         Transaction.date.between(s, e)).scalar() or 0)
        pct = int(spent / b.amount * 100) if b.amount > 0 else 0
        items.append({'b': b, 'spent': spent, 'remain': b.amount - spent, 'pct': min(pct, 120)})
        tb += b.amount; ts += spent

    exp_cats = (Category.query.filter(
        Category.type == 'expense',
        (Category.user_id == current_user.id) | (Category.is_default == True)
    ).order_by(Category.name).all())

    set_ids = {b.category_id for b in budgets}
    unbudgeted = (db.session.query(Category.name, Category.icon,
                                   func.sum(Transaction.amount).label('t'))
                  .join(Transaction, Transaction.category_id == Category.id)
                  .filter(Transaction.user_id == current_user.id,
                          Transaction.type == 'expense',
                          Transaction.date.between(s, e),
                          Transaction.category_id.notin_(set_ids))
                  .group_by(Category.id).all())

    if m == 1: py, pm = y-1, 12
    else:      py, pm = y, m-1
    if m == 12: ny, nm = y+1, 1
    else:       ny, nm = y, m+1

    return render_template('budget/index.html',
        items=items, tb=tb, ts=ts, exp_cats=exp_cats,
        unbudgeted=unbudgeted, y=y, m=m, ym=ym,
        py=py, pm=pm, ny=ny, nm=nm)


@budget_bp.route('/set', methods=['POST'])
@login_required
def set_budget():
    cat_id = request.form.get('category_id', type=int)
    ym     = request.form.get('month', '')
    try:
        amount = float(request.form.get('amount','0').replace(',',''))
    except ValueError:
        flash('올바른 금액을 입력해 주세요.', 'danger')
        return redirect(url_for('budget.index'))
    if not cat_id or not ym or amount <= 0:
        flash('모든 항목을 입력해 주세요.', 'danger')
        return redirect(url_for('budget.index'))
    b = Budget.query.filter_by(user_id=current_user.id, category_id=cat_id, month=ym).first()
    if b:
        b.amount = amount
    else:
        db.session.add(Budget(user_id=current_user.id, category_id=cat_id,
                              month=ym, amount=amount))
    db.session.commit()
    flash('예산이 저장되었습니다.', 'success')
    p = ym.split('-')
    return redirect(url_for('budget.index', year=p[0], month=int(p[1])))


@budget_bp.route('/delete/<int:bid>', methods=['POST'])
@login_required
def delete(bid):
    b = Budget.query.filter_by(id=bid, user_id=current_user.id).first_or_404()
    ym = b.month
    db.session.delete(b); db.session.commit()
    flash('삭제되었습니다.', 'success')
    p = ym.split('-')
    return redirect(url_for('budget.index', year=p[0], month=int(p[1])))


@budget_bp.route('/copy', methods=['POST'])
@login_required
def copy():
    from_ym = request.form.get('from_ym','')
    to_ym   = request.form.get('to_ym','')
    for b in Budget.query.filter_by(user_id=current_user.id, month=from_ym).all():
        if not Budget.query.filter_by(user_id=current_user.id,
                                      category_id=b.category_id, month=to_ym).first():
            db.session.add(Budget(user_id=current_user.id, category_id=b.category_id,
                                  month=to_ym, amount=b.amount))
    db.session.commit()
    flash(f'{from_ym} → {to_ym} 예산 복사 완료', 'success')
    p = to_ym.split('-')
    return redirect(url_for('budget.index', year=p[0], month=int(p[1])))
