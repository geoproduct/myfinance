"""
routes/stocks.py
한국/미국 주식 지표 기능 – 전체 라우트
"""
import logging
from flask import (Blueprint, render_template, request, jsonify,
                   redirect, url_for, flash, abort)
from flask_login import login_required, current_user
from sqlalchemy import func, and_, or_
from datetime import date, timedelta

from models import db, Stock, StockDaily, StockWatchlist, StockHolding

log = logging.getLogger(__name__)
stocks_bp = Blueprint('stocks', __name__, url_prefix='/stocks')


# ── 유틸 ────────────────────────────────────────
def _latest_date():
    """DB에 저장된 가장 최신 날짜"""
    return db.session.query(func.max(StockDaily.date)).scalar()


def _fmt_cap(cap: int | None, market: str = 'KOSPI') -> str:
    """시가총액 표시: 한국은 조/억, 미국은 T/B/M (USD)"""
    if not cap:
        return '-'
    if market == 'US':
        if cap >= 1_000_000_000_000:
            return f"${cap / 1_000_000_000_000:.1f}T"
        if cap >= 1_000_000_000:
            return f"${cap / 1_000_000_000:.1f}B"
        return f"${cap / 1_000_000:.0f}M"
    # KRW
    if cap >= 1_0000_0000_0000:
        return f"{cap / 1_0000_0000_0000:.1f}조"
    return f"{cap / 1_0000_0000:.0f}억"


def _ensure_history(ticker: str, market: str):
    """
    종목 상세 페이지 진입 시 최근 90일 이력이 10일 미만이면
    NAVER fchart API에서 자동 수집 (한국 주식만).
    """
    if market not in ('KOSPI', 'KOSDAQ'):
        return
    cutoff = date.today() - timedelta(days=90)
    cnt = (StockDaily.query
           .filter(StockDaily.ticker == ticker,
                   StockDaily.date >= cutoff)
           .count())
    if cnt >= 10:
        return
    try:
        from stock_sync import fetch_history_kr, _save_history_to_db
        history = fetch_history_kr(ticker, count=90)
        if history:
            n = _save_history_to_db(ticker, history)
            log.info(f'[EnsureHistory] {ticker} {n}일 이력 수집 완료')
    except Exception as e:
        log.warning(f'[EnsureHistory] {ticker} 실패: {e}')


# ── 1. 종목 리스트 ───────────────────────────────
@stocks_bp.route('/')
@login_required
def index():
    page   = request.args.get('page',   1,     type=int)
    q      = request.args.get('q',      '').strip()
    market = request.args.get('market', 'ALL')
    sector = request.args.get('sector', '')
    sort   = request.args.get('sort',   'market_cap')
    order  = request.args.get('order',  'desc')

    latest = _latest_date()
    if not latest:
        return render_template('stocks/index.html',
                               pagination=None, stocks=[],
                               latest_date=None, sectors=[],
                               q=q, market=market, sector=sector,
                               sort=sort, order=order,
                               no_data=True)

    qry = (db.session.query(Stock, StockDaily)
           .join(StockDaily, and_(
               Stock.ticker == StockDaily.ticker,
               StockDaily.date == latest)))

    if q:
        qry = qry.filter(or_(
            Stock.name.ilike(f'%{q}%'),
            Stock.ticker.ilike(f'%{q}%')))
    if market != 'ALL':
        qry = qry.filter(Stock.market == market)
    if sector:
        qry = qry.filter(Stock.sector == sector)

    col_map = {
        'per':        StockDaily.per,
        'pbr':        StockDaily.pbr,
        'div':        StockDaily.div,
        'market_cap': StockDaily.market_cap,
        'close':      StockDaily.close,
    }
    sort_col = col_map.get(sort, StockDaily.market_cap)
    qry = qry.filter(sort_col.isnot(None), sort_col > 0)
    qry = qry.order_by(sort_col.asc() if order == 'asc' else sort_col.desc())

    pagination = qry.paginate(page=page, per_page=50, error_out=False)

    # 관심종목 티커 집합
    watched = {
        w.ticker for w in
        StockWatchlist.query.filter_by(user_id=current_user.id).all()
    }

    # 업종 목록 (필터 드롭다운)
    sectors = [r[0] for r in
               db.session.query(Stock.sector).distinct().order_by(Stock.sector)
               if r[0]]

    return render_template('stocks/index.html',
                           pagination=pagination,
                           stocks=pagination.items,
                           latest_date=latest,
                           sectors=sectors,
                           watched=watched,
                           fmt_cap=_fmt_cap,
                           q=q, market=market, sector=sector,
                           sort=sort, order=order,
                           no_data=False,
                           markets=['ALL', 'KOSPI', 'KOSDAQ', 'US'])


# ── 2. 종목 상세 ─────────────────────────────────
@stocks_bp.route('/<ticker>')
@login_required
def detail(ticker):
    stock = Stock.query.get_or_404(ticker)

    # 한국 주식: 이력 부족하면 NAVER fchart에서 자동 보완
    _ensure_history(ticker, stock.market)

    daily_data = (StockDaily.query
                  .filter_by(ticker=ticker)
                  .filter(StockDaily.date >= date.today() - timedelta(days=95))
                  .order_by(StockDaily.date.asc())
                  .all())

    latest = daily_data[-1] if daily_data else None

    is_watched = bool(StockWatchlist.query.filter_by(
        user_id=current_user.id, ticker=ticker).first())

    holding = StockHolding.query.filter_by(
        user_id=current_user.id, ticker=ticker).first()

    is_us = (stock.market == 'US')

    # 차트 데이터 – US는 cents → USD 변환
    chart_labels = [d.date.strftime('%m/%d') for d in daily_data]
    if is_us:
        chart_close  = [round(d.close / 100, 2) for d in daily_data]
    else:
        chart_close  = [d.close for d in daily_data]
    chart_volume = [d.volume for d in daily_data]

    # 전일 대비
    prev_close = daily_data[-2].close if len(daily_data) >= 2 else None
    change = change_pct = None
    if latest and prev_close:
        change     = latest.close - prev_close
        change_pct = change / prev_close * 100
        if is_us:
            change     = round(change / 100, 2)    # USD
            change_pct = round(change_pct, 2)

    return render_template('stocks/detail.html',
                           stock=stock,
                           latest=latest,
                           holding=holding,
                           is_watched=is_watched,
                           is_us=is_us,
                           chart_labels=chart_labels,
                           chart_close=chart_close,
                           chart_volume=chart_volume,
                           change=change,
                           change_pct=change_pct,
                           fmt_cap=_fmt_cap)


# ── 3. 스크리너 ──────────────────────────────────
@stocks_bp.route('/screener')
@login_required
def screener():
    per_min  = request.args.get('per_min',  type=float)
    per_max  = request.args.get('per_max',  type=float)
    pbr_min  = request.args.get('pbr_min',  type=float)
    pbr_max  = request.args.get('pbr_max',  type=float)
    div_min  = request.args.get('div_min',  type=float)
    cap_min  = request.args.get('cap_min',  type=int)    # 억원
    cap_max  = request.args.get('cap_max',  type=int)
    market   = request.args.get('market',   'ALL')
    sector   = request.args.get('sector',   '')
    page     = request.args.get('page',     1, type=int)

    latest = _latest_date()
    qry = (db.session.query(Stock, StockDaily)
           .join(StockDaily, and_(
               Stock.ticker == StockDaily.ticker,
               StockDaily.date == latest)))

    if per_min  is not None: qry = qry.filter(StockDaily.per >= per_min)
    if per_max  is not None: qry = qry.filter(StockDaily.per <= per_max)
    if pbr_min  is not None: qry = qry.filter(StockDaily.pbr >= pbr_min)
    if pbr_max  is not None: qry = qry.filter(StockDaily.pbr <= pbr_max)
    if div_min  is not None: qry = qry.filter(StockDaily.div >= div_min)
    if cap_min  is not None: qry = qry.filter(StockDaily.market_cap >= cap_min * 1_0000_0000)
    if cap_max  is not None: qry = qry.filter(StockDaily.market_cap <= cap_max * 1_0000_0000)
    if market != 'ALL':      qry = qry.filter(Stock.market == market)
    if sector:               qry = qry.filter(Stock.sector == sector)

    qry = (qry.filter(StockDaily.per.isnot(None), StockDaily.per > 0,
                      StockDaily.pbr.isnot(None), StockDaily.pbr > 0)
              .order_by(StockDaily.market_cap.desc()))

    pagination = qry.paginate(page=page, per_page=50, error_out=False)
    sectors = [r[0] for r in
               db.session.query(Stock.sector).distinct().order_by(Stock.sector)
               if r[0]]

    watched = {
        w.ticker for w in
        StockWatchlist.query.filter_by(user_id=current_user.id).all()
    }

    return render_template('stocks/screener.html',
                           pagination=pagination,
                           stocks=pagination.items,
                           latest_date=latest,
                           sectors=sectors,
                           watched=watched,
                           fmt_cap=_fmt_cap,
                           per_min=per_min, per_max=per_max,
                           pbr_min=pbr_min, pbr_max=pbr_max,
                           div_min=div_min,
                           cap_min=cap_min, cap_max=cap_max,
                           market=market, sector=sector)


# ── 4. 관심종목 ──────────────────────────────────
@stocks_bp.route('/watchlist')
@login_required
def watchlist():
    latest = _latest_date()

    items = (db.session.query(Stock, StockDaily, StockWatchlist)
             .join(StockWatchlist, Stock.ticker == StockWatchlist.ticker)
             .outerjoin(StockDaily, and_(
                 Stock.ticker == StockDaily.ticker,
                 StockDaily.date == latest))
             .filter(StockWatchlist.user_id == current_user.id)
             .order_by(StockWatchlist.created_at.desc())
             .all())

    return render_template('stocks/watchlist.html',
                           items=items, latest_date=latest,
                           fmt_cap=_fmt_cap)


# ── 5. 관심종목 토글 (AJAX) ───────────────────────
@stocks_bp.route('/watchlist/toggle/<ticker>', methods=['POST'])
@login_required
def watchlist_toggle(ticker):
    stock = Stock.query.get(ticker)
    if not stock:
        return jsonify(ok=False, msg='종목 없음'), 404

    wl = StockWatchlist.query.filter_by(
        user_id=current_user.id, ticker=ticker).first()

    if wl:
        db.session.delete(wl)
        db.session.commit()
        return jsonify(ok=True, action='removed')
    else:
        db.session.add(StockWatchlist(user_id=current_user.id, ticker=ticker))
        db.session.commit()
        return jsonify(ok=True, action='added')


# ── 6. 주식 포트폴리오 ────────────────────────────
@stocks_bp.route('/portfolio')
@login_required
def portfolio():
    latest = _latest_date()

    holdings = (db.session.query(StockHolding, Stock, StockDaily)
                .join(Stock, StockHolding.ticker == Stock.ticker)
                .outerjoin(StockDaily, and_(
                    StockHolding.ticker == StockDaily.ticker,
                    StockDaily.date == latest))
                .filter(StockHolding.user_id == current_user.id)
                .all())

    rows = []
    for h, s, d in holdings:
        is_us = (s.market == 'US')
        if is_us:
            # US: close stored as cents → convert to USD
            close    = round((d.close or 0) / 100, 2) if d else 0.0
        else:
            close    = d.close if d else 0
        eval_amt = close * h.quantity
        cost_amt = h.avg_price * h.quantity
        gain     = eval_amt - cost_amt
        gain_pct = (gain / cost_amt * 100) if cost_amt else 0
        rows.append({
            'holding':  h, 'stock': s, 'daily': d,
            'close':    close,
            'eval_amt': eval_amt,
            'cost_amt': cost_amt,
            'gain':     gain,
            'gain_pct': gain_pct,
            'currency': 'USD' if is_us else 'KRW',
        })

    # KRW / USD 총합 분리
    kr_rows   = [r for r in rows if r['currency'] == 'KRW']
    us_rows   = [r for r in rows if r['currency'] == 'USD']
    kr_eval   = sum(r['eval_amt'] for r in kr_rows)
    kr_cost   = sum(r['cost_amt'] for r in kr_rows)
    us_eval   = sum(r['eval_amt'] for r in us_rows)
    us_cost   = sum(r['cost_amt'] for r in us_rows)
    kr_gain   = kr_eval - kr_cost
    us_gain   = us_eval - us_cost
    kr_gain_pct = (kr_gain / kr_cost * 100) if kr_cost else 0
    us_gain_pct = (us_gain / us_cost * 100) if us_cost else 0

    # 도넛 차트 (KRW 기준, USD는 별도 표시)
    chart_labels = [r['stock'].name for r in rows]
    chart_data   = [r['eval_amt'] for r in rows]
    chart_colors = ['#3699FF','#0BB783','#FFA800','#F64E60','#8950FC',
                    '#1BC5BD','#6993FF','#E4E6EF','#B5B5C3','#7E8299']

    return render_template('stocks/portfolio.html',
                           rows=rows,
                           kr_rows=kr_rows, us_rows=us_rows,
                           kr_eval=kr_eval, kr_cost=kr_cost,
                           kr_gain=kr_gain, kr_gain_pct=kr_gain_pct,
                           us_eval=us_eval, us_cost=us_cost,
                           us_gain=us_gain, us_gain_pct=us_gain_pct,
                           latest_date=latest,
                           chart_labels=chart_labels,
                           chart_data=chart_data,
                           chart_colors=chart_colors[:len(rows)])


# ── 7. 포트폴리오 추가/수정 ───────────────────────
@stocks_bp.route('/portfolio/save', methods=['POST'])
@login_required
def portfolio_save():
    ticker    = request.form.get('ticker', '').strip().upper()
    quantity  = request.form.get('quantity', 0, type=int)
    avg_price = request.form.get('avg_price', 0.0, type=float)

    if not ticker or quantity <= 0 or avg_price <= 0:
        flash('종목코드, 수량, 매수가를 올바르게 입력하세요.', 'danger')
        return redirect(url_for('stocks.portfolio'))

    stock = Stock.query.get(ticker)
    if not stock:
        flash(f'종목코드 {ticker} 를 찾을 수 없습니다.', 'danger')
        return redirect(url_for('stocks.portfolio'))

    h = StockHolding.query.filter_by(
        user_id=current_user.id, ticker=ticker).first()
    if h:
        # 수량 평균 재계산
        total_qty  = h.quantity + quantity
        h.avg_price = (h.avg_price * h.quantity + avg_price * quantity) / total_qty
        h.quantity  = total_qty
    else:
        h = StockHolding(user_id=current_user.id, ticker=ticker,
                         quantity=quantity, avg_price=avg_price)
        db.session.add(h)

    db.session.commit()
    flash(f'{stock.name} 보유 주식이 저장되었습니다.', 'success')
    return redirect(url_for('stocks.portfolio'))


# ── 8. 포트폴리오 삭제 ────────────────────────────
@stocks_bp.route('/portfolio/delete/<int:hid>', methods=['POST'])
@login_required
def portfolio_delete(hid):
    h = StockHolding.query.get_or_404(hid)
    if h.user_id != current_user.id:
        abort(403)
    db.session.delete(h)
    db.session.commit()
    flash('삭제되었습니다.', 'success')
    return redirect(url_for('stocks.portfolio'))


# ── 9. 종목 검색 API (자동완성) ───────────────────
@stocks_bp.route('/api/search')
@login_required
def api_search():
    q = request.args.get('q', '').strip()
    if len(q) < 1:
        return jsonify([])

    results = (Stock.query
               .filter(or_(
                   Stock.name.ilike(f'%{q}%'),
                   Stock.ticker.ilike(f'%{q}%')))
               .limit(10).all())

    return jsonify([
        {'ticker': s.ticker, 'name': s.name, 'market': s.market}
        for s in results
    ])


# ── 10. 수동 동기화 (관리자) ──────────────────────
@stocks_bp.route('/api/sync', methods=['POST'])
@login_required
def api_sync():
    """Railway shell 또는 관리자가 직접 호출하는 동기화 엔드포인트"""
    try:
        from stock_sync import sync_stocks
        target = request.json.get('date') if request.json else None
        count = sync_stocks(target)
        return jsonify(ok=True, count=count)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500
