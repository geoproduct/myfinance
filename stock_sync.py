"""
stock_sync.py
KRX(한국거래소) 데이터 수집 및 DB 저장 모듈
pykrx 사용 – API 키 불필요

사용법:
    python stock_sync.py              # 최근 영업일 데이터
    python stock_sync.py --date 20260301
    python stock_sync.py --init       # 최근 30일치 일괄 수집
"""
import argparse
import logging
from datetime import datetime, date, timedelta

import pandas as pd
from pykrx import stock as krx

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)


def get_latest_trading_day(ref: date = None) -> str:
    """주말을 건너뛴 가장 최근 영업일 (YYYYMMDD)"""
    d = ref or date.today()
    while d.weekday() >= 5:      # 토=5, 일=6
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


def _safe_float(val) -> float | None:
    """0 또는 NaN이면 None 반환"""
    try:
        f = float(val)
        return f if f != 0 else None
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return 0


def sync_stocks(target_date: str = None) -> int:
    """
    전체 종목 기본 정보 + 일별 지표를 수집해 DB에 upsert.
    app context 내에서 호출해야 함.
    """
    from models import db, Stock, StockDaily

    if not target_date:
        target_date = get_latest_trading_day()

    log.info(f"[StockSync] 시작 – 기준일: {target_date}")

    # ── 1. 전체 종목 코드 + 업종 수집 ─────────────────────────────
    all_tickers: dict[str, dict] = {}

    for market in ("KOSPI", "KOSDAQ", "KONEX"):
        try:
            tickers = krx.get_market_ticker_list(target_date, market=market)
            log.info(f"[StockSync] {market} 종목 수: {len(tickers)}")

            # 업종 분류
            try:
                sector_df = krx.get_market_sector_classifications(
                    date=target_date, market=market
                )
                sector_map = {
                    str(row["종목코드"]).zfill(6): row["업종명"]
                    for _, row in sector_df.iterrows()
                }
            except Exception:
                sector_map = {}

            for ticker in tickers:
                try:
                    name = krx.get_market_ticker_name(ticker)
                except Exception:
                    name = ticker
                all_tickers[ticker] = {
                    "name": name,
                    "market": market,
                    "sector": sector_map.get(ticker, "기타"),
                }
        except Exception as e:
            log.error(f"[StockSync] {market} 종목 목록 수집 실패: {e}")

    if not all_tickers:
        log.warning("[StockSync] 수집된 종목 없음 – 영업일이 아닐 수 있음")
        return 0

    # DB upsert – Stock 기본 정보
    for ticker, info in all_tickers.items():
        s = db.session.get(Stock, ticker)
        if not s:
            s = Stock(ticker=ticker)
            db.session.add(s)
        s.name   = info["name"]
        s.market = info["market"]
        s.sector = info["sector"]
    db.session.commit()
    log.info(f"[StockSync] 종목 기본정보 저장 완료 – {len(all_tickers)}개")

    # ── 2. 전체 종목 지표 (PER, PBR, EPS, BPS, DIV, DPS) ─────────
    try:
        metrics = krx.get_market_fundamental(target_date, target_date, "ALL")
        log.info(f"[StockSync] 지표 수집 완료 – {len(metrics)}행")
    except Exception as e:
        log.error(f"[StockSync] 지표 수집 실패: {e}")
        metrics = pd.DataFrame()

    # ── 3. 전체 종목 시가총액 ────────────────────────────────────
    try:
        caps = krx.get_market_cap(target_date, target_date, "ALL")
        log.info(f"[StockSync] 시가총액 수집 완료 – {len(caps)}행")
    except Exception as e:
        log.error(f"[StockSync] 시가총액 수집 실패: {e}")
        caps = pd.DataFrame()

    # ── 4. 전체 종목 OHLCV ───────────────────────────────────────
    try:
        ohlcv = krx.get_market_ohlcv(target_date, target_date, "ALL")
        log.info(f"[StockSync] OHLCV 수집 완료 – {len(ohlcv)}행")
    except Exception as e:
        log.error(f"[StockSync] OHLCV 수집 실패: {e}")
        ohlcv = pd.DataFrame()

    # ── 5. StockDaily upsert ─────────────────────────────────────
    target_date_obj = datetime.strptime(target_date, "%Y%m%d").date()
    saved = 0

    for ticker in all_tickers:
        try:
            row = StockDaily.query.filter_by(
                ticker=ticker, date=target_date_obj
            ).first()
            if not row:
                row = StockDaily(ticker=ticker, date=target_date_obj)
                db.session.add(row)

            # OHLCV
            if not ohlcv.empty and ticker in ohlcv.index:
                o = ohlcv.loc[ticker]
                row.open   = _safe_int(o.get("시가"))
                row.high   = _safe_int(o.get("고가"))
                row.low    = _safe_int(o.get("저가"))
                row.close  = _safe_int(o.get("종가"))
                row.volume = _safe_int(o.get("거래량"))

            # 지표
            if not metrics.empty and ticker in metrics.index:
                m = metrics.loc[ticker]
                row.per = _safe_float(m.get("PER"))
                row.pbr = _safe_float(m.get("PBR"))
                row.eps = _safe_float(m.get("EPS"))
                row.bps = _safe_float(m.get("BPS"))
                row.div = _safe_float(m.get("DIV"))
                row.dps = _safe_float(m.get("DPS"))

            # 시가총액
            if not caps.empty and ticker in caps.index:
                row.market_cap = _safe_int(caps.loc[ticker].get("시가총액"))

            saved += 1
        except Exception as e:
            log.warning(f"[StockSync] {ticker} 저장 실패: {e}")

        # 500개마다 중간 commit
        if saved % 500 == 0 and saved > 0:
            db.session.commit()
            log.info(f"[StockSync] {saved}개 중간 저장...")

    db.session.commit()
    log.info(f"[StockSync] 완료 – {saved}/{len(all_tickers)}개 저장")
    return saved


def sync_range(days: int = 30):
    """최근 N 영업일 데이터 일괄 수집 (초기화용)"""
    d = date.today()
    collected = 0
    for _ in range(days * 2):   # 주말 포함 여유있게
        if d.weekday() < 5:
            target = d.strftime("%Y%m%d")
            log.info(f"[StockSync] 날짜 수집: {target}")
            count = sync_stocks(target)
            if count > 0:
                collected += 1
        d -= timedelta(days=1)
        if collected >= days:
            break
    log.info(f"[StockSync] 범위 수집 완료 – {collected}일")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KRX 주식 데이터 수집")
    parser.add_argument("--date",  default=None, help="기준일 YYYYMMDD")
    parser.add_argument("--init",  action="store_true", help="최근 30일 일괄 수집")
    parser.add_argument("--days",  type=int, default=30, help="--init 시 수집 일수")
    args = parser.parse_args()

    from app import create_app
    app = create_app()
    with app.app_context():
        if args.init:
            sync_range(args.days)
        else:
            sync_stocks(args.date)
