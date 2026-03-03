# 📊 MyFinance – 한국 주식 지표 기능 기획 & 개발 스펙

> **대상 개발자**: OpenClaw AI Agent
> **기준 프로젝트**: `C:/Users/master/Desktop/myfinance` (Flask + PostgreSQL + Railway)
> **목표**: 한국 거래소(KOSPI/KOSDAQ/KONEX) 전체 종목의 PER·PBR·ROE·EPS 등 지표 제공 + 관심종목·포트폴리오 통합

---

## 1. 기능 개요

| 화면 | 주요 기능 |
|------|-----------|
| 주식 홈 (`/stocks`) | 전체 종목 리스트, 검색, 시장/업종 필터, PER·PBR 정렬 |
| 종목 상세 (`/stocks/<ticker>`) | 가격 차트, PER·PBR·ROE·EPS·배당률, 재무요약 |
| 스크리너 (`/stocks/screener`) | PER 범위·PBR 범위·시가총액·업종으로 조건 검색 |
| 관심종목 (`/stocks/watchlist`) | 로그인 유저별 즐겨찾기 종목 |
| 주식 포트폴리오 (`/stocks/portfolio`) | 보유 주식 입력 → 평가손익, 비중 차트 |
| 데이터 동기화 (`/api/stocks/sync`) | 관리자용 KRX 데이터 갱신 API (+ 스케줄러 자동 실행) |

---

## 2. 데이터 소스 & 라이브러리

### 2-1. pykrx (핵심)
```
pip install pykrx
```
- KRX(한국거래소) 공식 데이터, **무료, API 키 불필요**
- KOSPI / KOSDAQ / KONEX 전종목 지원
- 제공 데이터: PER, PBR, EPS, BPS, DPS, DIV(배당률), 시가총액, 가격

#### 주요 pykrx 함수
```python
from pykrx import stock

# 날짜 기준 전체 종목 코드 (ex: KOSPI)
tickers = stock.get_market_ticker_list(date="20260301", market="KOSPI")
# market: "KOSPI" | "KOSDAQ" | "KONEX" | "ALL"

# 종목명
name = stock.get_market_ticker_name("005930")  # "삼성전자"

# 전체 종목 일별 OHLCV (한방에)
ohlcv_df = stock.get_market_ohlcv("20260301", "20260301", "ALL")

# 전체 종목 지표 (PER, PBR, ROE 등) - 가장 중요!
# 컬럼: BPS, PER, PBR, EPS, DIV, DPS
metrics_df = stock.get_market_fundamental("20260301", "20260301", "ALL")
# 인덱스 = 티커코드, 컬럼 = [BPS, PER, PBR, EPS, DIV, DPS]

# 시가총액
cap_df = stock.get_market_cap("20260301", "20260301", "ALL")
# 컬럼: 시가총액, 거래량, 거래대금, 상장주식수

# KRX 업종(섹터) 분류
sector_df = stock.get_market_sector_classifications(date="20260301", market="KOSPI")
# 컬럼: 종목코드, 종목명, 업종코드, 업종명
```

### 2-2. APScheduler (자동 갱신)
```
pip install APScheduler==3.10.4
```
- 매 영업일 18:00 KST에 자동 데이터 갱신

### 2-3. 기존 스택 활용
- Flask, SQLAlchemy (PostgreSQL), Chart.js (이미 있음)
- 새 의존성: `pykrx`, `APScheduler`

---

## 3. DB 모델 설계

> 파일: `models.py` 에 추가 (기존 User, Transaction 등 유지)

### 3-1. Stock (종목 기본 정보)
```python
class Stock(db.Model):
    __tablename__ = 'stocks'
    ticker      = db.Column(db.String(10), primary_key=True)   # "005930"
    name        = db.Column(db.String(100), nullable=False)     # "삼성전자"
    market      = db.Column(db.String(10))   # KOSPI / KOSDAQ / KONEX
    sector      = db.Column(db.String(50))   # 업종명
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    daily_data  = db.relationship('StockDaily', backref='stock', lazy='dynamic',
                                  foreign_keys='StockDaily.ticker')
```

### 3-2. StockDaily (일별 가격 + 지표)
```python
class StockDaily(db.Model):
    __tablename__ = 'stock_daily'
    id          = db.Column(db.Integer, primary_key=True)
    ticker      = db.Column(db.String(10), db.ForeignKey('stocks.ticker'), nullable=False)
    date        = db.Column(db.Date, nullable=False)
    # 가격
    open        = db.Column(db.BigInteger, default=0)
    high        = db.Column(db.BigInteger, default=0)
    low         = db.Column(db.BigInteger, default=0)
    close       = db.Column(db.BigInteger, default=0)
    volume      = db.Column(db.BigInteger, default=0)
    # 지표
    per         = db.Column(db.Float)   # 주가수익비율
    pbr         = db.Column(db.Float)   # 주가순자산비율
    eps         = db.Column(db.Float)   # 주당순이익
    bps         = db.Column(db.Float)   # 주당순자산
    div         = db.Column(db.Float)   # 배당수익률(%)
    dps         = db.Column(db.Float)   # 주당배당금
    market_cap  = db.Column(db.BigInteger)  # 시가총액(원)

    __table_args__ = (db.UniqueConstraint('ticker', 'date', name='uq_stock_daily'),)
```

### 3-3. StockWatchlist (관심종목)
```python
class StockWatchlist(db.Model):
    __tablename__ = 'stock_watchlist'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ticker     = db.Column(db.String(10), db.ForeignKey('stocks.ticker'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'ticker', name='uq_watchlist'),)
```

### 3-4. StockHolding (보유 주식 포트폴리오)
```python
class StockHolding(db.Model):
    __tablename__ = 'stock_holdings'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ticker      = db.Column(db.String(10), db.ForeignKey('stocks.ticker'), nullable=False)
    quantity    = db.Column(db.Integer, default=0)      # 보유 수량
    avg_price   = db.Column(db.Float, default=0)        # 평균 매수가
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, onupdate=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'ticker', name='uq_holding'),)
```

### User 모델에 관계 추가
```python
# User 클래스에 추가:
watchlist = db.relationship('StockWatchlist', backref='user', lazy='dynamic')
holdings  = db.relationship('StockHolding',   backref='user', lazy='dynamic')
```

---

## 4. 데이터 수집 모듈

> 파일: `stock_sync.py` (프로젝트 루트)

```python
"""
stock_sync.py
KRX 데이터 수집 및 DB 저장 모듈
사용법:
    python stock_sync.py                  # 오늘 데이터 수집
    python stock_sync.py --date 20260301  # 특정 날짜
"""
import argparse
from datetime import datetime, date, timedelta
import pandas as pd
from pykrx import stock as krx
from models import db, Stock, StockDaily
import logging

log = logging.getLogger(__name__)


def get_latest_trading_day():
    """가장 최근 영업일(주말 건너뜀)"""
    d = date.today()
    while d.weekday() >= 5:  # 토=5, 일=6
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def sync_stocks(target_date: str = None):
    """
    전체 종목 정보 + 일별 지표 수집 후 DB 저장
    target_date: "YYYYMMDD" 형식, None이면 최근 영업일
    """
    if not target_date:
        target_date = get_latest_trading_day()

    log.info(f"[StockSync] 데이터 수집 시작: {target_date}")

    # ── 1. 전체 종목 코드 + 업종 수집 ──────────────────
    all_tickers = {}  # {ticker: {name, market, sector}}

    for market in ["KOSPI", "KOSDAQ", "KONEX"]:
        try:
            tickers = krx.get_market_ticker_list(target_date, market=market)
            # 업종 분류
            try:
                sector_df = krx.get_market_sector_classifications(
                    date=target_date, market=market
                )
                sector_map = dict(zip(
                    sector_df['종목코드'].astype(str).str.zfill(6),
                    sector_df['업종명']
                ))
            except Exception:
                sector_map = {}

            for ticker in tickers:
                name = krx.get_market_ticker_name(ticker)
                all_tickers[ticker] = {
                    "name": name,
                    "market": market,
                    "sector": sector_map.get(ticker, "기타")
                }
        except Exception as e:
            log.error(f"[StockSync] {market} 종목 수집 실패: {e}")

    # DB에 Stock 기본 정보 upsert
    for ticker, info in all_tickers.items():
        s = Stock.query.get(ticker)
        if not s:
            s = Stock(ticker=ticker)
            db.session.add(s)
        s.name    = info['name']
        s.market  = info['market']
        s.sector  = info['sector']
    db.session.commit()
    log.info(f"[StockSync] 종목 기본정보 저장 완료: {len(all_tickers)}개")

    # ── 2. 전체 종목 지표 수집 (PER, PBR, EPS 등) ──────
    try:
        metrics = krx.get_market_fundamental(
            target_date, target_date, "ALL"
        )
        # 컬럼: BPS, PER, PBR, EPS, DIV, DPS (인덱스=티커)
    except Exception as e:
        log.error(f"[StockSync] 지표 수집 실패: {e}")
        metrics = pd.DataFrame()

    # ── 3. 전체 종목 시가총액 + 가격 ─────────────────────
    try:
        caps = krx.get_market_cap(target_date, target_date, "ALL")
        # 컬럼: 시가총액, 거래량, 거래대금, 상장주식수
    except Exception as e:
        log.error(f"[StockSync] 시가총액 수집 실패: {e}")
        caps = pd.DataFrame()

    try:
        ohlcv = krx.get_market_ohlcv(target_date, target_date, "ALL")
        # 컬럼: 시가, 고가, 저가, 종가, 거래량
    except Exception as e:
        log.error(f"[StockSync] OHLCV 수집 실패: {e}")
        ohlcv = pd.DataFrame()

    # ── 4. DB에 StockDaily upsert ────────────────────────
    target_date_obj = datetime.strptime(target_date, "%Y%m%d").date()
    saved = 0

    for ticker in all_tickers.keys():
        try:
            row = StockDaily.query.filter_by(
                ticker=ticker, date=target_date_obj
            ).first()
            if not row:
                row = StockDaily(ticker=ticker, date=target_date_obj)
                db.session.add(row)

            # 가격 데이터
            if not ohlcv.empty and ticker in ohlcv.index:
                o = ohlcv.loc[ticker]
                row.open   = int(o.get('시가', 0) or 0)
                row.high   = int(o.get('고가', 0) or 0)
                row.low    = int(o.get('저가', 0) or 0)
                row.close  = int(o.get('종가', 0) or 0)
                row.volume = int(o.get('거래량', 0) or 0)

            # 지표 데이터
            if not metrics.empty and ticker in metrics.index:
                m = metrics.loc[ticker]
                row.per = float(m.get('PER', 0) or 0) or None
                row.pbr = float(m.get('PBR', 0) or 0) or None
                row.eps = float(m.get('EPS', 0) or 0) or None
                row.bps = float(m.get('BPS', 0) or 0) or None
                row.div = float(m.get('DIV', 0) or 0) or None
                row.dps = float(m.get('DPS', 0) or 0) or None

            # 시가총액
            if not caps.empty and ticker in caps.index:
                row.market_cap = int(caps.loc[ticker].get('시가총액', 0) or 0)

            saved += 1
        except Exception as e:
            log.warning(f"[StockSync] {ticker} 저장 실패: {e}")

    db.session.commit()
    log.info(f"[StockSync] 일별 데이터 저장 완료: {saved}개")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="YYYYMMDD")
    args = parser.parse_args()

    from app import create_app
    app = create_app()
    with app.app_context():
        sync_stocks(args.date)
```

---

## 5. 스케줄러 설정

> 파일: `scheduler.py` (프로젝트 루트)

```python
"""
scheduler.py
APScheduler를 Flask 앱에 통합
app.py의 create_app()에서 init_scheduler(app) 호출
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import logging

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Seoul'))


def _run_sync():
    """스케줄러에서 호출되는 동기화 함수"""
    from stock_sync import sync_stocks
    try:
        count = sync_stocks()
        log.info(f"[Scheduler] 주식 동기화 완료: {count}개")
    except Exception as e:
        log.error(f"[Scheduler] 주식 동기화 실패: {e}")


def init_scheduler(app):
    """
    앱 컨텍스트 내에서 스케줄러 시작
    매 평일 18:10 KST 자동 실행 (장 마감 후)
    """
    if scheduler.running:
        return

    def job_with_context():
        with app.app_context():
            _run_sync()

    scheduler.add_job(
        job_with_context,
        trigger=CronTrigger(
            day_of_week='mon-fri',
            hour=18, minute=10,
            timezone=pytz.timezone('Asia/Seoul')
        ),
        id='stock_sync_daily',
        replace_existing=True
    )
    scheduler.start()
    log.info("[Scheduler] 주식 자동 동기화 스케줄러 시작 (평일 18:10 KST)")
```

> `app.py`의 `create_app()` 함수 끝에 추가:
```python
from scheduler import init_scheduler
init_scheduler(app)
```

---

## 6. 라우트 설계

> 파일: `routes/stocks.py` (새 파일)

### 6-1. 전체 구조
```python
from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user
from models import db, Stock, StockDaily, StockWatchlist, StockHolding
from sqlalchemy import func, and_, or_
from datetime import date, timedelta

stocks_bp = Blueprint('stocks', __name__, url_prefix='/stocks')
```

### 6-2. 엔드포인트 목록

| Method | URL | 기능 |
|--------|-----|------|
| GET | `/stocks` | 종목 리스트 (페이지네이션, 검색, 필터) |
| GET | `/stocks/<ticker>` | 종목 상세 페이지 |
| GET | `/stocks/screener` | 스크리너 (조건 검색) |
| GET | `/stocks/watchlist` | 관심종목 목록 |
| POST | `/stocks/watchlist/<ticker>` | 관심종목 추가/제거 (toggle) |
| GET | `/stocks/portfolio` | 주식 포트폴리오 |
| POST | `/stocks/portfolio` | 보유 주식 추가/수정 |
| DELETE | `/stocks/portfolio/<id>` | 보유 주식 삭제 |
| GET | `/stocks/api/search` | 종목 검색 JSON API (자동완성용) |
| POST | `/api/stocks/sync` | 관리자 수동 동기화 |

### 6-3. 주요 라우트 구현

#### `/stocks` – 종목 리스트
```python
@stocks_bp.route('/')
@login_required
def index():
    page    = request.args.get('page', 1, type=int)
    q       = request.args.get('q', '').strip()        # 검색어
    market  = request.args.get('market', 'ALL')        # KOSPI/KOSDAQ/ALL
    sector  = request.args.get('sector', '')
    sort    = request.args.get('sort', 'market_cap')   # per/pbr/market_cap
    order   = request.args.get('order', 'desc')        # asc/desc

    # 최신 날짜 기준 데이터
    latest_date = db.session.query(func.max(StockDaily.date)).scalar()
    if not latest_date:
        return render_template('stocks/index.html', stocks=[], message="데이터 없음")

    query = db.session.query(Stock, StockDaily)\
        .join(StockDaily, and_(
            Stock.ticker == StockDaily.ticker,
            StockDaily.date == latest_date
        ))

    # 필터
    if q:
        query = query.filter(or_(
            Stock.name.ilike(f'%{q}%'),
            Stock.ticker.ilike(f'%{q}%')
        ))
    if market != 'ALL':
        query = query.filter(Stock.market == market)
    if sector:
        query = query.filter(Stock.sector == sector)

    # 정렬
    sort_col = {
        'per': StockDaily.per,
        'pbr': StockDaily.pbr,
        'market_cap': StockDaily.market_cap,
        'close': StockDaily.close,
        'div': StockDaily.div,
    }.get(sort, StockDaily.market_cap)

    if order == 'asc':
        query = query.filter(sort_col.isnot(None), sort_col > 0).order_by(sort_col.asc())
    else:
        query = query.filter(sort_col.isnot(None), sort_col > 0).order_by(sort_col.desc())

    pagination = query.paginate(page=page, per_page=50, error_out=False)

    # 업종 목록 (필터용)
    sectors = [r[0] for r in db.session.query(Stock.sector).distinct().order_by(Stock.sector)]

    return render_template('stocks/index.html',
        pagination=pagination,
        stocks=pagination.items,
        latest_date=latest_date,
        sectors=sectors,
        q=q, market=market, sector=sector, sort=sort, order=order
    )
```

#### `/stocks/<ticker>` – 종목 상세
```python
@stocks_bp.route('/<ticker>')
@login_required
def detail(ticker):
    stock = Stock.query.get_or_404(ticker)

    # 최근 90일 데이터
    daily_data = StockDaily.query.filter_by(ticker=ticker)\
        .filter(StockDaily.date >= date.today() - timedelta(days=90))\
        .order_by(StockDaily.date.asc()).all()

    # 관심종목 여부
    is_watched = StockWatchlist.query.filter_by(
        user_id=current_user.id, ticker=ticker
    ).first() is not None

    # 보유 여부
    holding = StockHolding.query.filter_by(
        user_id=current_user.id, ticker=ticker
    ).first()

    # 최신 지표
    latest = daily_data[-1] if daily_data else None

    return render_template('stocks/detail.html',
        stock=stock, daily_data=daily_data,
        latest=latest, is_watched=is_watched, holding=holding
    )
```

#### `/stocks/screener` – 스크리너
```python
@stocks_bp.route('/screener')
@login_required
def screener():
    # 조건 파라미터
    per_min  = request.args.get('per_min',  type=float)
    per_max  = request.args.get('per_max',  type=float)
    pbr_min  = request.args.get('pbr_min',  type=float)
    pbr_max  = request.args.get('pbr_max',  type=float)
    div_min  = request.args.get('div_min',  type=float)   # 배당률 최소
    cap_min  = request.args.get('cap_min',  type=int)     # 시가총액 최소 (억원)
    cap_max  = request.args.get('cap_max',  type=int)
    market   = request.args.get('market', 'ALL')
    sector   = request.args.get('sector', '')
    page     = request.args.get('page', 1, type=int)

    latest_date = db.session.query(func.max(StockDaily.date)).scalar()
    query = db.session.query(Stock, StockDaily)\
        .join(StockDaily, and_(
            Stock.ticker == StockDaily.ticker,
            StockDaily.date == latest_date
        ))

    # 조건 적용
    if per_min is not None: query = query.filter(StockDaily.per >= per_min)
    if per_max is not None: query = query.filter(StockDaily.per <= per_max)
    if pbr_min is not None: query = query.filter(StockDaily.pbr >= pbr_min)
    if pbr_max is not None: query = query.filter(StockDaily.pbr <= pbr_max)
    if div_min is not None: query = query.filter(StockDaily.div >= div_min)
    if cap_min is not None: query = query.filter(StockDaily.market_cap >= cap_min * 1e8)
    if cap_max is not None: query = query.filter(StockDaily.market_cap <= cap_max * 1e8)
    if market != 'ALL':     query = query.filter(Stock.market == market)
    if sector:              query = query.filter(Stock.sector == sector)

    query = query.filter(
        StockDaily.per.isnot(None), StockDaily.per > 0,
        StockDaily.pbr.isnot(None), StockDaily.pbr > 0,
    ).order_by(StockDaily.market_cap.desc())

    pagination = query.paginate(page=page, per_page=50, error_out=False)
    sectors = [r[0] for r in db.session.query(Stock.sector).distinct().order_by(Stock.sector)]

    return render_template('stocks/screener.html',
        pagination=pagination, stocks=pagination.items,
        sectors=sectors, latest_date=latest_date,
        **request.args
    )
```

---

## 7. 템플릿 설계

> 모두 `templates/stocks/` 폴더에 생성, `base.html` 상속

### 7-1. `stocks/index.html`

**레이아웃:**
```
┌─────────────────────────────────────────────────┐
│  🔍 [검색창] [KOSPI▼] [업종▼] [정렬: 시가총액▼]   │
├──────┬──────────────┬──────┬──────┬──────┬──────┤
│ 코드 │ 종목명       │시장  │ PER  │ PBR  │시총  │
├──────┼──────────────┼──────┼──────┼──────┼──────┤
│005930│ 삼성전자     │KOSPI │ 12.3 │  1.2 │400조 │
│ ...  │ ...          │ ...  │ ...  │ ...  │ ...  │
└──────┴──────────────┴──────┴──────┴──────┴──────┘
  ← 1 2 3 ... 50 →
```

**기능:**
- 종목명/코드 검색 (실시간 debounce)
- 시장 탭 (전체/KOSPI/KOSDAQ)
- PER, PBR, 시가총액, 배당률 클릭으로 오름/내림 정렬
- 관심종목 ☆ 버튼 (AJAX toggle)
- 마지막 데이터 날짜 표시

### 7-2. `stocks/detail.html`

**레이아웃:**
```
┌─────────────────────────────────────────────────┐
│ 삼성전자 (005930)  KOSPI · 반도체           [☆관심] │
│                                                  │
│  현재가 72,400 ▲200(+0.28%)  시총 431.2조원      │
├─────────────────────────────────────────────────┤
│  [주가 차트 - Line Chart 90일]                    │
├──────────┬──────────┬──────────┬────────────────┤
│ PER 12.3 │ PBR  1.2 │ ROE 9.8%│ EPS 5,882원    │
│ BPS 60,100│DIV 2.1% │ DPS 1,444│ 거래량 8.2M    │
├─────────────────────────────────────────────────┤
│  📂 보유 주식 등록  [수량: ____] [매수가: ____] [저장]│
└─────────────────────────────────────────────────┘
```

**차트:** Chart.js Line 차트 (종가 90일)

### 7-3. `stocks/screener.html`

**레이아웃:**
```
┌───────────────────────────────────────────────┐
│ 📊 주식 스크리너                               │
│ PER: [0] ~ [30]  PBR: [0] ~ [2]              │
│ 배당률: [3]% 이상  시총: [1000]억~[  ]억       │
│ 시장: [전체▼]  업종: [반도체▼]   [검색]        │
├─────────────────────────────────────────────┤
│ 결과 234개                                   │
│ (종목 테이블 – index.html과 동일 구조)         │
└─────────────────────────────────────────────┘
```

### 7-4. `stocks/watchlist.html`
- 관심종목 카드 그리드 (종목명, 현재가, PER, PBR, 등락률)
- 제거 버튼

### 7-5. `stocks/portfolio.html`

**레이아웃:**
```
┌─────────────────────────────────────────────────┐
│  📈 주식 포트폴리오              총 평가금액: 12.3M │
├──────────────────────────────────────────────────┤
│ [도넛 차트 - 종목별 비중]                          │
├──────┬────────┬─────┬─────┬───────┬─────────────┤
│종목  │현재가  │수량 │평균가│평가금액│  손익       │
├──────┼────────┼─────┼─────┼───────┼─────────────┤
│삼성전│72,400  │ 100 │65,000│7.24M │+740K(+11.4%)│
└──────┴────────┴─────┴─────┴───────┴─────────────┘
  [+ 종목 추가]
```

---

## 8. app.py 수정 사항

`app.py`의 `create_app()` 내 블루프린트 등록 부분에 추가:

```python
from routes.stocks import stocks_bp
app.register_blueprint(stocks_bp)

# 스케줄러 시작 (프로덕션 환경에서)
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    from scheduler import init_scheduler
    init_scheduler(app)
```

---

## 9. base.html 사이드바 추가

기존 `templates/base.html`의 사이드바에 추가:
```html
<li class="nav-item">
  <a href="{{ url_for('stocks.index') }}" class="nav-link {% if 'stocks' in request.path %}active{% endif %}">
    <i class="fas fa-chart-line"></i>
    <span>주식 지표</span>
  </a>
</li>
```

---

## 10. requirements.txt 추가

```
pykrx==1.0.47
APScheduler==3.10.4
```

---

## 11. 초기 데이터 수집 방법

Railway 배포 후 최초 1회 실행:
```bash
# Railway CLI 또는 Railway Shell에서
python stock_sync.py
# 약 2500~3000개 종목, 3~5분 소요
```

또는 앱에서 관리자가 `/api/stocks/sync` POST 요청으로 트리거 가능

---

## 12. 개발 순서 (우선순위 순)

### Step 1: 의존성 설치 및 DB 모델
1. `requirements.txt`에 `pykrx==1.0.47`, `APScheduler==3.10.4` 추가
2. `models.py`에 `Stock`, `StockDaily`, `StockWatchlist`, `StockHolding` 클래스 추가
3. `User` 클래스에 `watchlist`, `holdings` 관계 추가
4. 로컬에서 `python -c "from app import create_app; app=create_app(); app.app_context().push(); from models import db; db.create_all()"` 실행

### Step 2: 데이터 수집 모듈
1. `stock_sync.py` 작성 (위 코드 그대로)
2. 로컬에서 `python stock_sync.py` 실행하여 데이터 수집 확인

### Step 3: 스케줄러
1. `scheduler.py` 작성
2. `app.py`에 `init_scheduler` 연동

### Step 4: 라우트
1. `routes/stocks.py` 작성 (index, detail, screener, watchlist, portfolio 순)
2. `app.py`에 블루프린트 등록
3. API 엔드포인트 (`/stocks/api/search`, `/api/stocks/sync`) 구현

### Step 5: 템플릿
1. `templates/stocks/` 폴더 생성
2. `index.html` → `detail.html` → `screener.html` → `watchlist.html` → `portfolio.html` 순서
3. `base.html` 사이드바에 주식 메뉴 추가

### Step 6: 통합 및 연동
1. 대시보드(`routes/dashboard.py`)에 주식 포트폴리오 총평가액 추가
2. 자산관리(`routes/assets.py`)에 주식 포트폴리오 섹션 연동
3. Railway 배포 + 환경변수 확인 + `python stock_sync.py` 초기 실행

---

## 13. 주의 사항 & 예외 처리

### pykrx 관련
- 주말/공휴일에는 데이터 없음 → `get_latest_trading_day()` 함수로 가장 최근 영업일 사용
- KRX 서버 점검 시간(8:00~9:00, 장중 일부) 피해서 수집
- pykrx는 KRX 웹 스크래핑 기반 → 간헐적 타임아웃 발생 가능, 재시도 로직 권장
- PER=0 또는 None = 적자 기업 → 표시 시 "-" 또는 "N/A" 처리

### Railway 환경
- pykrx는 KRX 서버에서 데이터 가져오므로 별도 환경변수 불필요
- PostgreSQL에 `stock_daily` 테이블 약 3000행/일 적재 → 90일 기준 ~270,000행 (무리 없음)
- `railway run python stock_sync.py` 로 초기 데이터 수집

### 데이터 표시
- PER이 0이거나 None인 종목은 스크리너에서 자동 제외
- 시가총액 단위: DB는 원(₩), UI는 억원/조원으로 변환하여 표시
- 음수 PBR/PER은 "-" 표시 (자본잠식 등)

---

## 14. 파일 체크리스트

```
myfinance/
├── requirements.txt          ← pykrx, APScheduler 추가
├── stock_sync.py             ← 새 파일 (데이터 수집)
├── scheduler.py              ← 새 파일 (자동 스케줄)
├── app.py                    ← stocks_bp, init_scheduler 추가
├── models.py                 ← Stock, StockDaily, StockWatchlist, StockHolding 추가
├── routes/
│   └── stocks.py             ← 새 파일 (전체 라우트)
└── templates/
    └── stocks/
        ├── index.html        ← 종목 리스트
        ├── detail.html       ← 종목 상세
        ← screener.html       ← 스크리너
        ├── watchlist.html    ← 관심종목
        └── portfolio.html    ← 주식 포트폴리오
```

총 **신규 파일 9개**, **수정 파일 4개** (requirements.txt, app.py, models.py, base.html)
