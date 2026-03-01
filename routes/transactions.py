from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import db, Transaction, Category, Notification, Budget
from sqlalchemy import func, desc
from datetime import date, datetime
import calendar, io

transactions_bp = Blueprint('transactions', __name__)


def _cats():
    return (Category.query
            .filter((Category.user_id == current_user.id) | (Category.is_default == True))
            .order_by(Category.type, Category.name).all())


def _month_range(y, m):
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


@transactions_bp.route('/')
@login_required
def index():
    y    = request.args.get('year',  date.today().year,  type=int)
    m    = request.args.get('month', date.today().month, type=int)
    typ  = request.args.get('type',  'all')
    cat  = request.args.get('cat',   0, type=int)
    s, e = _month_range(y, m)

    q = Transaction.query.filter(Transaction.user_id == current_user.id,
                                 Transaction.date.between(s, e))
    if typ != 'all': q = q.filter(Transaction.type == typ)
    if cat:          q = q.filter(Transaction.category_id == cat)
    txns = q.order_by(desc(Transaction.date), desc(Transaction.id)).all()

    inc = sum(t.amount for t in txns if t.type == 'income')
    exp = sum(t.amount for t in txns if t.type == 'expense')

    prev = date(y, m, 1) - __import__('datetime').timedelta(days=1)
    nxt  = e + __import__('datetime').timedelta(days=1)

    return render_template('transactions/index.html',
        txns=txns, y=y, m=m, typ=typ, cat_id=cat,
        inc=inc, exp=exp, cats=_cats(),
        prev_y=prev.year, prev_m=prev.month,
        next_y=nxt.year,  next_m=nxt.month)


@transactions_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        t = _form_to_txn()
        if t:
            db.session.add(t)
            db.session.commit()
            _budget_alert(t)
            flash('거래가 추가되었습니다.', 'success')
            return redirect(url_for('transactions.index'))
    return render_template('transactions/form.html', cats=_cats(),
                           today=date.today().isoformat(), txn=None)


@transactions_bp.route('/edit/<int:tid>', methods=['GET', 'POST'])
@login_required
def edit(tid):
    t = Transaction.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    if request.method == 'POST':
        t.amount      = float(request.form.get('amount','0').replace(',',''))
        t.type        = request.form.get('type','expense')
        t.category_id = request.form.get('category_id', type=int) or None
        t.description = request.form.get('description','').strip()
        t.memo        = request.form.get('memo','').strip()
        t.date        = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        db.session.commit()
        flash('수정되었습니다.', 'success')
        return redirect(url_for('transactions.index', year=t.date.year, month=t.date.month))
    return render_template('transactions/form.html', cats=_cats(), txn=t,
                           today=t.date.isoformat())


@transactions_bp.route('/delete/<int:tid>', methods=['POST'])
@login_required
def delete(tid):
    t = Transaction.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    y, m = t.date.year, t.date.month
    db.session.delete(t)
    db.session.commit()
    flash('삭제되었습니다.', 'success')
    return redirect(url_for('transactions.index', year=y, month=m))


@transactions_bp.route('/export')
@login_required
def export_excel():
    """거래내역 Excel 내보내기"""
    y = request.args.get('year',  date.today().year,  type=int)
    m = request.args.get('month', date.today().month, type=int)
    s, e = _month_range(y, m)

    txns = (Transaction.query
            .filter(Transaction.user_id == current_user.id,
                    Transaction.date.between(s, e))
            .order_by(Transaction.date, Transaction.id).all())

    try:
        import pandas as pd, io as _io
        rows = []
        for t in txns:
            rows.append({
                '날짜':     t.date.strftime('%Y-%m-%d'),
                '유형':     '수입' if t.type == 'income' else '지출',
                '카테고리': t.category.name if t.category else '',
                '내용':     t.description or '',
                '금액':     int(t.amount),
                '메모':     t.memo or '',
            })
        df  = pd.DataFrame(rows)
        buf = _io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            df.to_excel(w, index=False, sheet_name=f'{y}년{m}월')
        buf.seek(0)
        from flask import send_file
        fname = f'myfinance_{y}{m:02d}.xlsx'
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except ImportError:
        flash('pandas/openpyxl 패키지가 필요합니다.', 'danger')
        return redirect(url_for('transactions.index', year=y, month=m))


@transactions_bp.route('/import', methods=['GET', 'POST'])
@login_required
def import_excel():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename.endswith(('.xlsx', '.xls')):
            flash('엑셀 파일을 선택해 주세요.', 'danger')
            return redirect(request.url)
        try:
            import pandas as pd
            df = pd.read_excel(io.BytesIO(f.read()))
            n  = _process_df(df)
            flash(f'{n}건 가져오기 완료!', 'success')
        except Exception as ex:
            flash(f'오류: {ex}', 'danger')
        return redirect(url_for('transactions.index'))
    return render_template('transactions/import.html')


def _form_to_txn():
    try:
        amount = float(request.form.get('amount','0').replace(',',''))
    except ValueError:
        flash('금액을 올바르게 입력해 주세요.', 'danger')
        return None
    try:
        d = datetime.strptime(request.form.get('date',''), '%Y-%m-%d').date()
    except ValueError:
        d = date.today()
    return Transaction(
        user_id=current_user.id, amount=amount,
        type=request.form.get('type','expense'),
        category_id=request.form.get('category_id', type=int) or None,
        description=request.form.get('description','').strip(),
        memo=request.form.get('memo','').strip(), date=d)


def _budget_alert(t):
    if t.type != 'expense' or not t.category_id:
        return
    ym = f'{t.date.year:04d}-{t.date.month:02d}'
    b  = Budget.query.filter_by(user_id=current_user.id,
                                 category_id=t.category_id, month=ym).first()
    if not b: return
    s, e = date(t.date.year, t.date.month, 1), \
           date(t.date.year, t.date.month, calendar.monthrange(t.date.year, t.date.month)[1])
    spent = (db.session.query(func.sum(Transaction.amount))
             .filter(Transaction.user_id == current_user.id,
                     Transaction.category_id == t.category_id,
                     Transaction.type == 'expense',
                     Transaction.date.between(s, e)).scalar() or 0)
    pct = spent / b.amount * 100 if b.amount > 0 else 0
    if pct >= 100:
        msg = f'"{t.category.name}" 예산 초과! ({int(spent):,}원 / {int(b.amount):,}원)'
    elif pct >= 80:
        msg = f'"{t.category.name}" 예산 {int(pct)}% 사용'
    else:
        return
    db.session.add(Notification(user_id=current_user.id, type='budget_alert',
                                ref_id=b.id, message=msg, link='/budget'))
    db.session.commit()
    # 실제 웹 푸시 알림도 전송
    try:
        from routes.push import _send_push
        title = '💰 예산 초과!' if pct >= 100 else '💸 예산 알림'
        _send_push(current_user.id, title=title, body=msg, url='/budget')
    except Exception:
        pass


def _process_df(df):
    """
    주요 한국 은행 CSV/Excel 포맷 자동 인식:
    - KB국민은행: 거래일시, 거래내용, 출금금액, 입금금액
    - 신한은행:   거래일시, 적요, 출금액, 입금액
    - 하나은행:   거래일자, 적요, 출금금액, 입금금액
    - 우리은행:   거래일자, 내용, 출금금액, 입금금액
    - 카카오뱅크: 거래일시, 거래내용, 출금금액, 입금금액
    - 토스뱅크:   날짜, 내용, 금액(원)
    - 일반 포맷:  date/날짜/일자, amount/금액, type/유형
    """
    import pandas as pd

    cols = [c.strip() for c in df.columns]
    col_map = {}

    # ── 날짜 ──
    for c in cols:
        cl = c.lower()
        if any(k in cl for k in ['거래일시','거래일자','날짜','일자','date','transaction date']):
            col_map['date'] = c; break

    # ── 출금/입금 분리 포맷 (대부분의 은행) ──
    out_col = in_col = None
    for c in cols:
        cl = c.lower()
        if any(k in cl for k in ['출금','출금금액','출금액','debit','withdrawl']):
            out_col = c
        if any(k in cl for k in ['입금','입금금액','입금액','credit','deposit']):
            in_col = c

    # ── 단일 금액 컬럼 (토스 스타일) ──
    amt_col = None
    for c in cols:
        cl = c.lower()
        if any(k in cl for k in ['금액','amount','거래금액']):
            amt_col = c; break

    # ── 내용/적요 ──
    desc_col = None
    for c in cols:
        cl = c.lower()
        if any(k in cl for k in ['거래내용','적요','내용','description','desc','메모','summary']):
            desc_col = c; break

    # ── 유형 (있는 경우) ──
    type_col = None
    for c in cols:
        cl = c.lower()
        if any(k in cl for k in ['구분','유형','type','거래구분']):
            type_col = c; break

    n = 0
    for _, row in df.iterrows():
        try:
            # 날짜
            raw_date = row.get(col_map.get('date', ''))
            if raw_date is None or str(raw_date).strip() in ('', 'nan'):
                continue
            d = pd.to_datetime(str(raw_date), errors='coerce')
            if pd.isna(d): continue
            d = d.date()

            # 금액 & 유형
            if out_col and in_col:
                # 출금/입금 분리 포맷
                out_raw = str(row.get(out_col, 0) or 0).replace(',', '').strip()
                in_raw  = str(row.get(in_col,  0) or 0).replace(',', '').strip()
                out_amt = float(out_raw) if out_raw not in ('', 'nan', '-') else 0
                in_amt  = float(in_raw)  if in_raw  not in ('', 'nan', '-') else 0
                if in_amt > 0:
                    amt, typ = in_amt, 'income'
                elif out_amt > 0:
                    amt, typ = out_amt, 'expense'
                else:
                    continue
            elif amt_col:
                # 단일 금액 포맷 (토스: 음수=지출)
                raw = str(row.get(amt_col, 0)).replace(',', '').replace('원', '').strip()
                val = float(raw) if raw not in ('', 'nan') else 0
                if val == 0: continue
                if val < 0:
                    amt, typ = abs(val), 'expense'
                else:
                    amt, typ = val, 'income'
                # type 컬럼으로 override
                if type_col:
                    t_val = str(row.get(type_col, '')).strip()
                    if t_val in ('수입', '입금', 'income', 'credit'):
                        typ = 'income'
                    elif t_val in ('지출', '출금', 'expense', 'debit'):
                        typ = 'expense'
            else:
                continue

            # 내용
            desc = str(row.get(desc_col, '') if desc_col else '').strip()[:200] or '가져오기'

            db.session.add(Transaction(
                user_id=current_user.id, amount=amt,
                type=typ, description=desc, date=d,
                memo='은행 CSV 가져오기'))
            n += 1
        except Exception:
            continue
    db.session.commit()
    return n
