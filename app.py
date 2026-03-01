from flask import Flask
from flask_login import LoginManager, current_user
from sqlalchemy import desc
from config import Config
from models import db, User, Category, Notification
from models import EXPENSE_CATEGORIES, INCOME_CATEGORIES
import os, random

login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'instance'), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view    = 'auth.login'
    login_manager.login_message = '로그인이 필요합니다.'
    login_manager.login_message_category = 'warning'

    # ── Blueprint 등록 ────────────────────────────
    from routes.auth         import auth_bp, init_oauth
    from routes.dashboard    import dashboard_bp
    from routes.transactions import transactions_bp
    from routes.budget       import budget_bp
    from routes.assets       import assets_bp
    from routes.social       import social_bp
    from routes.openbanking  import openbanking_bp
    from routes.push         import push_bp

    app.register_blueprint(auth_bp,          url_prefix='/auth')
    app.register_blueprint(dashboard_bp,     url_prefix='/')
    app.register_blueprint(transactions_bp,  url_prefix='/transactions')
    app.register_blueprint(budget_bp,        url_prefix='/budget')
    app.register_blueprint(assets_bp,        url_prefix='/assets')
    app.register_blueprint(social_bp,        url_prefix='/social')
    app.register_blueprint(openbanking_bp,   url_prefix='/openbanking')
    app.register_blueprint(push_bp,          url_prefix='/push')

    # ── OAuth 초기화 ─────────────────────────────
    init_oauth(app)

    # ── 전역 템플릿 변수 ──────────────────────────
    @app.context_processor
    def inject_globals():
        notifs = []
        if current_user.is_authenticated:
            notifs = (Notification.query
                      .filter_by(user_id=current_user.id)
                      .order_by(desc(Notification.created_at)).limit(8).all())
        return {
            'g_notifs': notifs,
            'vapid_public_key': app.config.get('VAPID_PUBLIC_KEY', ''),
        }

    with app.app_context():
        db.create_all()
        _seed_categories()
        _seed_demo()

    return app


@login_manager.user_loader
def load_user(uid):
    return User.query.get(int(uid))


def _seed_categories():
    if Category.query.filter_by(is_default=True).count() > 0:
        return
    for name, icon, color in EXPENSE_CATEGORIES:
        db.session.add(Category(name=name, icon=icon, color=color,
                                type='expense', is_default=True))
    for name, icon, color in INCOME_CATEGORIES:
        db.session.add(Category(name=name, icon=icon, color=color,
                                type='income', is_default=True))
    db.session.commit()


def _seed_demo():
    if User.query.filter_by(email='demo@myfinance.kr').first():
        return
    u = User(email='demo@myfinance.kr', nickname='데모유저',
              monthly_income=4_500_000, onboarding_done=True)
    u.set_password('Demo1234!')
    db.session.add(u)
    db.session.commit()

    from models import Transaction, Budget, Asset, AssetSnapshot
    from datetime import date, timedelta

    today = date.today()
    cats  = Category.query.filter_by(is_default=True).all()
    ec    = [c for c in cats if c.type == 'expense']
    ic    = [c for c in cats if c.type == 'income']

    # 90일치 거래
    for _ in range(80):
        d = today - timedelta(days=random.randint(0, 89))
        if random.random() < 0.12:
            c = random.choice(ic)
            amt = random.choice([4_000_000, 4_500_000, 500_000, 200_000, 300_000])
            db.session.add(Transaction(user_id=u.id, amount=amt, type='income',
                                       category_id=c.id, description=c.name, date=d))
        else:
            c = random.choice(ec)
            amt = random.randint(3_000, 200_000)
            db.session.add(Transaction(user_id=u.id, amount=amt, type='expense',
                                       category_id=c.id, description=c.name, date=d))

    # 예산 (이번달)
    ym = today.strftime('%Y-%m')
    for c in ec[:7]:
        db.session.add(Budget(user_id=u.id, category_id=c.id, month=ym,
                              amount=random.choice([150_000,200_000,300_000,500_000])))

    # 자산
    assets_data = [
        ('국민은행 예금통장', 'bank',   18_500_000, 'KRW', 'KB국민은행'),
        ('카카오뱅크',        'bank',    3_200_000, 'KRW', '카카오뱅크'),
        ('삼성전자 주식',     'stock',   5_600_000, 'KRW', '키움증권'),
        ('애플 ETF',          'stock',   2_400_000, 'KRW', '키움증권'),
        ('비트코인',          'crypto',  1_800_000, 'KRW', 'Upbit'),
        ('미국 달러 현금',    'cash',          500, 'USD', ''),
    ]
    for name, atype, amt, cur, bank in assets_data:
        db.session.add(Asset(user_id=u.id, name=name, type=atype,
                             amount=amt, currency=cur, bank_name=bank))

    # 6개월 스냅샷
    for i in range(6, 0, -1):
        d = today - timedelta(days=i*30)
        ym2 = d.strftime('%Y-%m')
        db.session.add(AssetSnapshot(user_id=u.id, month=ym2,
                                     total_krw=random.randint(25_000_000, 35_000_000)))

    # 샘플 게시글
    from models import Post
    sample_posts = [
        ('tip',        '이번 달 식비를 20% 줄였어요! 주말에 미리 밀프렙하면 정말 효과적이에요 😊'),
        ('investment', 'S&P500 ETF 꾸준히 적립 중입니다. 장기투자의 힘을 믿어요 📈'),
        ('budget',     '가계부 쓴 지 3개월째! 소비 패턴이 확실히 보이네요. 모두 화이팅! 💪'),
        ('question',   '청약통장 vs 적금, 어떤 걸 우선으로 해야 할까요?'),
        ('tip',        '카페 대신 텀블러 챙기기 시작했는데 한 달에 5만원 이상 절약됩니다!'),
    ]
    for cat, content in sample_posts:
        db.session.add(Post(user_id=u.id, category=cat, content=content))

    db.session.commit()


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5001)
