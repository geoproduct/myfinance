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
    """스케줄러 콜백 – app context 생성 후 sync 실행"""
    with app.app_context():
        try:
            from stock_sync import sync_stocks
            count = sync_stocks()
            log.info(f"[Scheduler] 주식 동기화 완료: {count}개")
        except Exception as e:
            log.error(f"[Scheduler] 주식 동기화 실패: {e}", exc_info=True)


def init_scheduler(app):
    """
    백그라운드 스케줄러 초기화.
    평일(월~금) 18:10 KST 에 KRX 데이터 자동 수집.
    gunicorn 멀티 워커 환경에서 중복 실행 방지:
        WERKZEUG_RUN_MAIN == 'true' 체크 없이 Railway에서 단일 워커로 실행.
    """
    if _scheduler.running:
        return

    _scheduler.add_job(
        func=_stock_sync_job,
        args=[app],
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=18, minute=10,
            timezone=_KST
        ),
        id="stock_sync_daily",
        replace_existing=True,
        misfire_grace_time=3600,   # 1시간 내 재실행 허용
    )
    _scheduler.start()
    log.info("[Scheduler] 주식 자동 동기화 스케줄러 시작 – 평일 18:10 KST")
