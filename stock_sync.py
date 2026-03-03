"""
stock_sync.py
네이버 금융 데이터 수집 및 DB 저장 모듈
- 종목 리스트 + PER + ROE: NAVER Finance sise_market_sum 스크래핑
- EPS / BPS / 배당금: NAVER polling API (bps → PBR 계산)
- 가격 / 거래량 / 시가총액: 동일 API

사용법:
    python stock_sync.py                  # 오늘(현재가) 수집
    python stock_sync.py --init           # 전종목 최초 수집
    python stock_sync.py --tickers 005930 000660
"""
import argparse
import logging
import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
log = logging.getLogger(__name__)

# ── HTTP 세션 ─────────────────────────────────────────────────────────────────
_session = requests.Session()
_session.headers.update({
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/121.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
})


# ── 1. 종목 리스트 수집 (NAVER sise_market_sum) ──────────────────────────────

def _get_tickers_naver(sosok: int) -> list:
    """
    NAVER 시가총액 페이지 전체 스크래핑
    sosok: 0=KOSPI, 1=KOSDAQ
    반환: [{'ticker', 'name', 'market', 'per', 'roe', 'close', 'market_cap'}]
    """
    market = 'KOSPI' if sosok == 0 else 'KOSDAQ'
    base   = f'https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}'
    result = []

    # 전체 페이지 수 파악
    try:
        r = _session.get(f'{base}&page=1')
        r.encoding = 'euc-kr'
        soup = BeautifulSoup(r.text, 'html.parser')
        pg_tag = soup.select('.pgRR a')
        last_page = int(re.search(r'page=(\d+)', pg_tag[-1]['href']).group(1)) if pg_tag else 1
    except Exception as e:
        log.error(f"[Naver] {market} 페이지 수 조회 실패: {e}")
        return []

    log.info(f"[Naver] {market} 전체 {last_page}페이지 수집 시작")

    for page in range(1, last_page + 1):
        try:
            r = _session.get(f'{base}&page={page}')
            r.encoding = 'euc-kr'
            soup = BeautifulSoup(r.text, 'html.parser')

            for row in soup.select('table.type_2 tr'):
                tds = row.find_all('td')
                if len(tds) < 12:
                    continue

                a_tag = tds[1].find('a', class_='tltle')
                if not a_tag:
                    continue

                href = a_tag.get('href', '')
                m = re.search(r'code=(\d{6})', href)
                if not m:
                    continue

                ticker = m.group(1)
                name   = a_tag.get_text(strip=True)

                def _num(td):
                    txt = td.get_text(strip=True).replace(',', '').replace('%', '')
                    try:
                        return float(txt)
                    except ValueError:
                        return None

                result.append({
                    'ticker':     ticker,
                    'name':       name,
                    'market':     market,
                    'close':      int(_num(tds[2]) or 0),
                    'market_cap': int((_num(tds[6]) or 0) * 1_0000_0000),   # 억원 → 원
                    'volume':     int(_num(tds[9]) or 0),
                    'per':        _num(tds[10]),
                    'roe':        _num(tds[11]),
                })

            time.sleep(0.3)   # NAVER 요청 간격

        except Exception as e:
            log.warning(f"[Naver] {market} {page}페이지 파싱 실패: {e}")

    log.info(f"[Naver] {market} 수집 완료: {len(result)}개")
    return result


# ── 2. 개별 지표 수집 (NAVER polling API) ────────────────────────────────────

def _get_fundamental(ticker: str) -> dict:
    """
    polling.finance.naver.com 에서 EPS / BPS / 배당금 조회
    반환: {'eps', 'bps', 'dps', 'close'}
    """
    url = (
        f'https://polling.finance.naver.com/api/realtime'
        f'?query=SERVICE_ITEM:{ticker}'
    )
    try:
        r = _session.get(url, timeout=5)
        areas = r.json()['result']['areas']
        if not areas or not areas[0].get('datas'):
            return {}
        d = areas[0]['datas'][0]
        price = d.get('nv') or d.get('sv') or 0
        return {
            'close': int(price),
            'eps':   float(d['eps']) if d.get('eps') else None,
            'bps':   float(d['bps']) if d.get('bps') else None,
            'dps':   float(d['dv'])  if d.get('dv')  else None,
        }
    except Exception:
        return {}


def _calc_pbr(close: int, bps) -> float:
    if bps and float(bps) > 0 and close > 0:
        return round(close / float(bps), 2)
    return None


def _calc_div(close: int, dps) -> float:
    if dps and float(dps) > 0 and close > 0:
        return round(float(dps) / close * 100, 2)
    return None


# ── 3. DB 저장 ───────────────────────────────────────────────────────────────

def _save_to_db(rows: list, target_date: date) -> int:
    from models import db, Stock, StockDaily

    saved = 0
    for info in rows:
        ticker = info['ticker']
        try:
            # Stock 기본 정보 upsert
            s = db.session.get(Stock, ticker)
            if not s:
                s = Stock(ticker=ticker)
                db.session.add(s)
            if info.get('name'):
                s.name = info['name']
            if info.get('market'):
                s.market = info['market']

            # StockDaily upsert
            row = StockDaily.query.filter_by(
                ticker=ticker, date=target_date
            ).first()
            if not row:
                row = StockDaily(ticker=ticker, date=target_date)
                db.session.add(row)

            row.close      = info.get('close') or 0
            row.volume     = info.get('volume') or 0
            row.market_cap = info.get('market_cap') or 0
            row.per        = info.get('per')
            row.eps        = info.get('eps')
            row.bps        = info.get('bps')
            row.pbr        = info.get('pbr')
            row.div        = info.get('div')
            row.dps        = info.get('dps')

            saved += 1
        except Exception as e:
            log.warning(f"[DB] {ticker} 저장 오류: {e}")

        if saved % 200 == 0 and saved > 0:
            db.session.commit()
            log.info(f"[DB] {saved}개 중간 저장...")

    db.session.commit()
    return saved


# ── 4. 메인 동기화 함수 ──────────────────────────────────────────────────────

def sync_stocks(target_date=None, only_tickers=None) -> int:
    """
    전종목 수집 메인 함수.
    app context 내에서 호출해야 함.
    """
    if target_date is None:
        target_date = date.today()

    log.info(f"[StockSync] 시작 - 기준일: {target_date}")

    if only_tickers:
        all_rows = []
        for ticker in only_tickers:
            data = _get_fundamental(ticker)
            if data:
                data['ticker'] = ticker
                data['name']   = ''
                data['market'] = ''
                data['pbr']    = _calc_pbr(data.get('close', 0), data.get('bps'))
                data['div']    = _calc_div(data.get('close', 0), data.get('dps'))
                all_rows.append(data)
    else:
        all_rows = []
        for sosok in (0, 1):
            rows = _get_tickers_naver(sosok)
            all_rows.extend(rows)

        log.info(f"[StockSync] 종목 리스트 완료: {len(all_rows)}개, 개별 지표 수집 시작...")

        for i, row in enumerate(all_rows):
            fund = _get_fundamental(row['ticker'])
            if fund:
                row['eps'] = fund.get('eps')
                row['bps'] = fund.get('bps')
                row['dps'] = fund.get('dps')
                row['pbr'] = _calc_pbr(row.get('close', 0), fund.get('bps'))
                row['div'] = _calc_div(row.get('close', 0), fund.get('dps'))
            else:
                row.setdefault('eps', None)
                row.setdefault('bps', None)
                row.setdefault('dps', None)
                row.setdefault('pbr', None)
                row.setdefault('div', None)

            if (i + 1) % 100 == 0:
                log.info(f"[StockSync] 지표 {i + 1}/{len(all_rows)}...")
            time.sleep(0.05)

    saved = _save_to_db(all_rows, target_date)
    log.info(f"[StockSync] 완료 - {saved}개 저장")
    return saved


# ── 5. 한국 주식 일봉 이력 수집 (NAVER fchart) ─────────────────────────────

def fetch_history_kr(ticker: str, count: int = 90) -> list:
    """
    NAVER fchart XML API로 일봉 이력 수집
    반환: [{'date': date, 'open', 'high', 'low', 'close', 'volume'}]
    """
    from xml.etree import ElementTree as ET
    url = (
        f'https://fchart.stock.naver.com/sise.nhn'
        f'?symbol={ticker}&timeframe=day&count={count}&requestType=0'
    )
    try:
        r = _session.get(url, timeout=10)
        # EUC-KR XML 선언을 UTF-8로 교체해야 ET가 파싱 가능
        content = r.content.replace(b'EUC-KR', b'utf-8')
        root = ET.fromstring(content)
        rows = []
        for item in root.iter('item'):
            raw = item.get('data', '')
            parts = raw.split('|')
            if len(parts) < 6:
                continue
            try:
                ds = parts[0].strip()
                d = date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
                rows.append({
                    'date':   d,
                    'open':   int(float(parts[1]) if parts[1] else 0),
                    'high':   int(float(parts[2]) if parts[2] else 0),
                    'low':    int(float(parts[3]) if parts[3] else 0),
                    'close':  int(float(parts[4]) if parts[4] else 0),
                    'volume': int(float(parts[5]) if parts[5] else 0),
                })
            except (ValueError, IndexError):
                continue
        return rows
    except Exception as e:
        log.warning(f'[fchart] {ticker} 이력 조회 실패: {e}')
        return []


def _save_history_to_db(ticker: str, history: list) -> int:
    """일봉 이력 리스트를 StockDaily에 upsert (OHLCV만, 기존 지표 유지)"""
    from models import db, StockDaily
    saved = 0
    for row in history:
        try:
            rec = StockDaily.query.filter_by(ticker=ticker, date=row['date']).first()
            if not rec:
                rec = StockDaily(ticker=ticker, date=row['date'])
                db.session.add(rec)
            if row.get('open'):   rec.open   = row['open']
            if row.get('high'):   rec.high   = row['high']
            if row.get('low'):    rec.low    = row['low']
            if row.get('close'):  rec.close  = row['close']
            if row.get('volume'): rec.volume = row['volume']
            saved += 1
        except Exception as e:
            log.warning(f'[DB history] {ticker} {row.get("date")} 저장 오류: {e}')
    db.session.commit()
    return saved


# ── 6. 미국 주식 수집 (S&P 500 전종목 + yfinance 배치) ────────────────────

# ── 6-1. S&P 500 전종목 목록 (Wikipedia) ──────────────────────────────────

def _get_sp500_tickers() -> list:
    """
    Wikipedia에서 S&P 500 종목 목록 스크래핑
    반환: [(ticker, name, sector), ...]
    """
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        r = _session.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'constituents'})
        if not table:
            log.warning('[US] Wikipedia S&P 500 표 찾기 실패')
            return []
        body = table.find('tbody') or table
        result = []
        for row in body.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 3:
                continue
            ticker = cells[0].get_text(strip=True).replace('.', '-')
            name   = cells[1].get_text(strip=True)
            sector = cells[2].get_text(strip=True)
            if ticker:
                result.append((ticker, name, sector))
        log.info(f'[US] S&P 500 목록 수집: {len(result)}개')
        return result
    except Exception as e:
        log.warning(f'[US] S&P 500 목록 수집 실패: {e}')
        return []


# ── 6-2. 배치 OHLCV 다운로드 (50개 청크) ─────────────────────────────────

def _batch_download_us(syms: list, period: str = '3mo') -> dict:
    """
    여러 미국 종목의 일봉 이력을 yfinance 배치로 다운로드.
    50개씩 청크 → MultiIndex DataFrame에서 종목별 분리.
    반환: {ticker: pd.DataFrame(Open/High/Low/Close/Volume)}
    """
    import yfinance as yf

    result   = {}
    chunk_sz = 50

    for i in range(0, len(syms), chunk_sz):
        chunk = syms[i:i + chunk_sz]
        try:
            raw = yf.download(
                tickers=chunk,
                period=period,
                auto_adjust=True,
                group_by='ticker',
                threads=True,
                progress=False,
            )
            for sym in chunk:
                try:
                    h = raw[sym] if len(chunk) > 1 else raw
                    h = h.dropna(how='all')
                    if not h.empty:
                        result[sym] = h
                except (KeyError, TypeError, AttributeError):
                    pass
        except Exception as e:
            log.warning(f'[US batch] 청크 {i}~{i + chunk_sz} 배치 실패: {e}')
            for sym in chunk:   # 개별 재시도
                try:
                    h = yf.Ticker(sym).history(period=period, auto_adjust=True)
                    if not h.empty:
                        result[sym] = h
                except Exception:
                    pass

        done = min(i + chunk_sz, len(syms))
        log.info(f'[US batch] OHLCV {done}/{len(syms)} 완료')
        time.sleep(1)

    return result


# ── 6-3. 기본 폴백 목록 (S&P 500 스크래핑 실패 시) ───────────────────────

US_STOCK_LIST = [
    # Big Tech
    ('AAPL', 'Apple'), ('MSFT', 'Microsoft'), ('NVDA', 'NVIDIA'),
    ('GOOGL', 'Alphabet'), ('META', 'Meta Platforms'), ('AMZN', 'Amazon'),
    ('TSLA', 'Tesla'), ('AVGO', 'Broadcom'), ('ORCL', 'Oracle'),
    ('CRM', 'Salesforce'), ('AMD', 'AMD'), ('INTC', 'Intel'),
    ('QCOM', 'Qualcomm'), ('TXN', 'Texas Instruments'), ('AMAT', 'Applied Materials'),
    # Finance
    ('JPM', 'JPMorgan Chase'), ('BAC', 'Bank of America'), ('WFC', 'Wells Fargo'),
    ('GS', 'Goldman Sachs'), ('MS', 'Morgan Stanley'), ('V', 'Visa'), ('MA', 'Mastercard'),
    # Healthcare
    ('JNJ', 'Johnson & Johnson'), ('UNH', 'UnitedHealth'), ('LLY', 'Eli Lilly'),
    ('PFE', 'Pfizer'), ('ABBV', 'AbbVie'), ('MRK', 'Merck'),
    # Consumer
    ('WMT', 'Walmart'), ('COST', 'Costco'), ('PG', 'Procter & Gamble'),
    ('KO', 'Coca-Cola'), ('PEP', 'PepsiCo'), ('MCD', "McDonald's"), ('NKE', 'Nike'),
    # Energy / Industrial / ETF
    ('XOM', 'ExxonMobil'), ('CVX', 'Chevron'), ('CAT', 'Caterpillar'),
    ('BA', 'Boeing'), ('SPY', 'S&P 500 ETF'), ('QQQ', 'Nasdaq 100 ETF'),
    ('VTI', 'Vanguard Total Market ETF'),
]


# ── 6-4. NaN 안전 변환 헬퍼 ──────────────────────────────────────────────

def _safe_cents(val) -> int:
    """float USD → cents (×100 int), NaN/None은 0 반환"""
    try:
        import math
        v = float(val)
        return 0 if math.isnan(v) else int(v * 100)
    except (TypeError, ValueError):
        return 0


def _safe_int(val) -> int:
    """float → int, NaN/None은 0 반환"""
    try:
        import math
        v = float(val)
        return 0 if math.isnan(v) else int(v)
    except (TypeError, ValueError):
        return 0


# ── 6-5. 메인 미국 주식 수집 함수 ────────────────────────────────────────

def sync_us_stocks() -> int:
    """
    S&P 500 전종목 수집 (Wikipedia 스크래핑 → yfinance 배치 OHLCV → 개별 지표).
    가격은 USD × 100 (센트) BigInteger 저장 → 템플릿에서 ÷100 표시.
    시가총액은 USD 그대로 저장.
    app context 내에서 호출해야 함.
    """
    try:
        import yfinance as yf
    except ImportError:
        log.error('[US] yfinance 미설치: pip install yfinance')
        return 0

    from models import db, Stock, StockDaily

    # 1. 종목 목록 확보 (S&P 500 → 실패 시 기본 42개 폴백)
    tickers_info = _get_sp500_tickers()
    if not tickers_info:
        log.warning('[US] S&P 500 수집 실패 → 기본 목록으로 수집')
        tickers_info = [(sym, name, '') for sym, name in US_STOCK_LIST]

    log.info(f'[US] 수집 대상: {len(tickers_info)}개')

    syms       = [t[0] for t in tickers_info]
    name_map   = {t[0]: t[1] for t in tickers_info}
    sector_map = {t[0]: t[2] for t in tickers_info}

    # 2. OHLCV 배치 다운로드 (50개 청크씩, 빠름)
    hist_map = _batch_download_us(syms, period='3mo')
    log.info(f'[US] 이력 수집 완료: {len(hist_map)}/{len(syms)}개')

    # 3. 지표(info) + DB 저장 (종목별 개별 처리)
    saved = 0
    for sym, default_name, default_sector in tickers_info:
        hist = hist_map.get(sym)
        if hist is None or hist.empty:
            continue
        try:
            # 지표 수집 (느림, rate limit 주의)
            try:
                info = yf.Ticker(sym).info
            except Exception:
                info = {}

            # Stock 기본 정보 upsert
            s = db.session.get(Stock, sym)
            if not s:
                s = Stock(ticker=sym)
                db.session.add(s)
            s.name   = info.get('longName') or info.get('shortName') or default_name
            s.market = 'US'
            s.sector = info.get('sector') or default_sector

            latest_date = hist.index[-1].date()

            # 일봉 이력 저장 (3개월치)
            for idx, row_data in hist.iterrows():
                row_date = idx.date()
                rec = StockDaily.query.filter_by(ticker=sym, date=row_date).first()
                if not rec:
                    rec = StockDaily(ticker=sym, date=row_date)
                    db.session.add(rec)

                rec.close  = _safe_cents(row_data.get('Close'))
                rec.open   = _safe_cents(row_data.get('Open'))
                rec.high   = _safe_cents(row_data.get('High'))
                rec.low    = _safe_cents(row_data.get('Low'))
                rec.volume = _safe_int(row_data.get('Volume'))

                if row_date == latest_date:
                    rec.per        = info.get('trailingPE')
                    rec.pbr        = info.get('priceToBook')
                    rec.eps        = info.get('trailingEps')
                    rec.bps        = info.get('bookValue')
                    div_yield      = info.get('dividendYield') or 0
                    rec.div        = round(div_yield * 100, 2) if div_yield else None
                    rec.dps        = info.get('lastDividendValue')
                    rec.market_cap = info.get('marketCap')

            saved += 1
            if saved % 10 == 0:
                db.session.commit()
                log.info(f'[US] {saved}/{len(tickers_info)}개 저장 중...')

            time.sleep(0.2)

        except Exception as e:
            log.warning(f'[US] {sym} 오류: {e}')

    db.session.commit()
    log.info(f'[US] 수집 완료: {saved}/{len(tickers_info)}개')
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NAVER/yfinance 주식 데이터 수집")
    parser.add_argument("--init",    action="store_true", help="전종목 최초 수집")
    parser.add_argument("--us",      action="store_true", help="미국 주요 종목 수집")
    parser.add_argument("--tickers", nargs="+",           help="특정 종목 코드만")
    args = parser.parse_args()

    from app import create_app
    application = create_app()
    with application.app_context():
        if args.us:
            sync_us_stocks()
        elif args.tickers:
            sync_stocks(only_tickers=args.tickers)
        else:
            sync_stocks()
