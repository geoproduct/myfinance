"""
scheduler.py
APScheduler 설정 – 평일 18:10 KST 자동 주식 데이터 갱신
app.py의 create_app() 마지막에 init_scheduler(app) 호출
"""
import logging
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Seoul"))
_KST = pytz.timezone("Asia/Seoul")


def _stock_sync_job(app):
    """스케줄러 콜백 – 한국 주식 (KOSPI/KOSDAQ) 자동 갱신"""
    with app.app_context():
        try:
            from stock_sync import sync_stocks
            count = sync_stocks()
            log.info(f"[Scheduler] 한국 주식 동기화 완료: {count}개")
        except Exception as e:
            log.error(f"[Scheduler] 한국 주식 동기화 실패: {e}", exc_info=True)


def _us_sync_job(app):
    """스케줄러 콜백 – 미국 주식 (yfinance) 자동 갱신"""
    with app.app_context():
        try:
            from stock_sync import sync_us_stocks
            count = sync_us_stocks()
            log.info(f"[Scheduler] 미국 주식 동기화 완료: {count}개")
        except Exception as e:
            log.error(f"[Scheduler] 미국 주식 동기화 실패: {e}", exc_info=True)


def init_scheduler(app):
    """
    백그라운드 스케줄러 초기화.
    - 한국 주식: 평일(월~금) 18:10 KST (장 마감 후)
    - 미국 주식: 평일(월~금) 08:00 KST (미국 전일 종가 반영)
    """
    if _scheduler.running:
        return

    # 한국 주식 – 평일 18:10 KST
    _scheduler.add_job(
        func=_stock_sync_job,
        args=[app],
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=18, minute=10,
            timezone=_KST
        ),
        id="stock_sync_kr",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 미국 주식 – 평일 08:00 KST (미국 전일 종가 기준)
    _scheduler.add_job(
        func=_us_sync_job,
        args=[app],
        trigger=CronTrigger(
            day_of_week="tue-sat",   # 미국 월~금 = KST 화~토
            hour=8, minute=0,
            timezone=_KST
        ),
        id="stock_sync_us",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    log.info("[Scheduler] 주식 자동 동기화 스케줄러 시작 – KR 18:10 / US 08:00 KST")
