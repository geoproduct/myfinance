from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import random, string

db = SQLAlchemy()

def rand_code(n=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

# ── 사용자 ──────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id              = db.Column(db.Integer, primary_key=True)
    email           = db.Column(db.String(120), unique=True, nullable=False)
    password_hash   = db.Column(db.String(255))
    nickname        = db.Column(db.String(50), default='')
    profile_img     = db.Column(db.String(255), default='')
    monthly_income  = db.Column(db.Float, default=0)
    provider        = db.Column(db.String(20), default='email')
    is_verified     = db.Column(db.Boolean, default=True)
    onboarding_done = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship('Transaction', backref='user', lazy='dynamic',
                                   foreign_keys='Transaction.user_id')
    budgets      = db.relationship('Budget',      backref='user', lazy='dynamic')
    assets       = db.relationship('Asset',       backref='user', lazy='dynamic')
    posts        = db.relationship('Post',        backref='user', lazy='dynamic')
    notifications= db.relationship('Notification',backref='user', lazy='dynamic')

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return bool(self.password_hash and check_password_hash(self.password_hash, pw))

    @property
    def display_name(self):
        return self.nickname or self.email.split('@')[0]

    def unread_count(self):
        return Notification.query.filter_by(user_id=self.id, is_read=False).count()


# ── 카테고리 ────────────────────────────────────
class Category(db.Model):
    __tablename__ = 'categories'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(50), nullable=False)
    icon       = db.Column(db.String(10), default='📌')
    color      = db.Column(db.String(7),  default='#B5B5C3')
    type       = db.Column(db.String(10), nullable=False)   # income / expense
    is_default = db.Column(db.Boolean,   default=True)
    user_id    = db.Column(db.Integer,   db.ForeignKey('users.id'))

    transactions = db.relationship('Transaction', backref='category', lazy='dynamic')
    budgets      = db.relationship('Budget',      backref='category', lazy='dynamic')


EXPENSE_CATEGORIES = [
    ('식비',       '🍽️', '#F64E60'),
    ('교통',       '🚌', '#3699FF'),
    ('쇼핑',       '🛍️', '#FFA800'),
    ('카페/간식',  '☕', '#8950FC'),
    ('의료/건강',  '💊', '#1BC5BD'),
    ('문화/여가',  '🎬', '#6993FF'),
    ('교육',       '📚', '#0BB783'),
    ('주거/관리비','🏠', '#F64E60'),
    ('통신',       '📱', '#3699FF'),
    ('보험',       '🛡️', '#B5B5C3'),
    ('미용',       '💅', '#FFA800'),
    ('술/유흥',    '🍺', '#8950FC'),
    ('기타지출',   '📌', '#B5B5C3'),
]
INCOME_CATEGORIES = [
    ('급여',      '💵', '#0BB783'),
    ('부수입',    '💼', '#1BC5BD'),
    ('투자수익',  '📊', '#3699FF'),
    ('용돈',      '🎁', '#FFA800'),
    ('기타수입',  '✅', '#B5B5C3'),
]


# ── 거래 ────────────────────────────────────────
class Transaction(db.Model):
    __tablename__ = 'transactions'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'),      nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    group_id    = db.Column(db.Integer, db.ForeignKey('groups.id'))
    amount      = db.Column(db.Float,   nullable=False)
    type        = db.Column(db.String(10), nullable=False)  # income / expense
    description = db.Column(db.String(200), default='')
    memo        = db.Column(db.Text,    default='')
    date        = db.Column(db.Date,    nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)


# ── 예산 ────────────────────────────────────────
class Budget(db.Model):
    __tablename__ = 'budgets'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'),      nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    amount      = db.Column(db.Float,   nullable=False)
    month       = db.Column(db.String(7), nullable=False)  # YYYY-MM
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'category_id', 'month'),)


# ── 자산 ────────────────────────────────────────
class Asset(db.Model):
    __tablename__ = 'assets'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name         = db.Column(db.String(100), nullable=False)
    type         = db.Column(db.String(20))   # bank/stock/crypto/cash/real_estate/other
    amount       = db.Column(db.Float,  nullable=False)
    currency     = db.Column(db.String(3), default='KRW')
    bank_name    = db.Column(db.String(50), default='')
    note         = db.Column(db.String(200), default='')
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AssetSnapshot(db.Model):
    __tablename__ = 'asset_snapshots'
    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    month     = db.Column(db.String(7), nullable=False)
    total_krw = db.Column(db.Float,    nullable=False)
    created_at= db.Column(db.DateTime, default=datetime.utcnow)


# ── 소셜: 피드 ──────────────────────────────────
class Post(db.Model):
    __tablename__ = 'posts'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category     = db.Column(db.String(20), default='tip')
    content      = db.Column(db.Text, nullable=False)
    is_anonymous = db.Column(db.Boolean, default=False)
    likes        = db.Column(db.Integer, default=0)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    comments     = db.relationship('Comment', backref='post', lazy='dynamic',
                                   cascade='all,delete-orphan')
    like_records = db.relationship('PostLike', backref='post', lazy='dynamic',
                                   cascade='all,delete-orphan')


class PostLike(db.Model):
    __tablename__ = 'post_likes'
    id      = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('post_id', 'user_id'),)


class Comment(db.Model):
    __tablename__ = 'comments'
    id         = db.Column(db.Integer, primary_key=True)
    post_id    = db.Column(db.Integer, db.ForeignKey('posts.id'),    nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'),    nullable=False)
    parent_id  = db.Column(db.Integer, db.ForeignKey('comments.id'))
    content    = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    author     = db.relationship('User', foreign_keys=[user_id])
    replies    = db.relationship('Comment', backref=db.backref('parent', remote_side='Comment.id'),
                                 lazy='dynamic')


# ── 소셜: 그룹 ──────────────────────────────────
class Group(db.Model):
    __tablename__ = 'groups'
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), nullable=False)
    owner_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    invite_code = db.Column(db.String(10), unique=True, default=rand_code)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    owner       = db.relationship('User', foreign_keys=[owner_id])
    members     = db.relationship('GroupMember', backref='group', lazy='dynamic',
                                  cascade='all,delete-orphan')


class GroupMember(db.Model):
    __tablename__ = 'group_members'
    id        = db.Column(db.Integer, primary_key=True)
    group_id  = db.Column(db.Integer, db.ForeignKey('groups.id'),  nullable=False)
    user_id   = db.Column(db.Integer, db.ForeignKey('users.id'),   nullable=False)
    role      = db.Column(db.String(10), default='editor')   # owner/editor/viewer
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    member    = db.relationship('User', foreign_keys=[user_id])
    __table_args__ = (db.UniqueConstraint('group_id', 'user_id'),)


# ── 소셜: 챌린지 ────────────────────────────────
class Challenge(db.Model):
    __tablename__ = 'challenges'
    id            = db.Column(db.Integer, primary_key=True)
    creator_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title         = db.Column(db.String(200), nullable=False)
    description   = db.Column(db.Text, default='')
    target_amount = db.Column(db.Float, default=0)
    period_start  = db.Column(db.Date)
    period_end    = db.Column(db.Date)
    is_public     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    creator       = db.relationship('User', foreign_keys=[creator_id])
    c_members     = db.relationship('ChallengeMember', backref='challenge', lazy='dynamic',
                                    cascade='all,delete-orphan')


class ChallengeMember(db.Model):
    __tablename__ = 'challenge_members'
    id             = db.Column(db.Integer, primary_key=True)
    challenge_id   = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'),      nullable=False)
    current_amount = db.Column(db.Float, default=0)
    joined_at      = db.Column(db.DateTime, default=datetime.utcnow)
    member         = db.relationship('User', foreign_keys=[user_id])
    __table_args__ = (db.UniqueConstraint('challenge_id', 'user_id'),)


# ── 알림 ────────────────────────────────────────
class Notification(db.Model):
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type       = db.Column(db.String(30))
    ref_id     = db.Column(db.Integer)
    message    = db.Column(db.String(200))
    link       = db.Column(db.String(200), default='')
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── 연동 계좌 (오픈뱅킹/Mock) ───────────────────
BANKS = {
    'kb':      ('🏦', 'KB국민은행'),
    'shinhan': ('🏦', '신한은행'),
    'hana':    ('🏦', '하나은행'),
    'woori':   ('🏦', '우리은행'),
    'nh':      ('🏦', 'NH농협은행'),
    'ibk':     ('🏦', 'IBK기업은행'),
    'kakao':   ('💛', '카카오뱅크'),
    'toss':    ('💙', '토스뱅크'),
}

class LinkedAccount(db.Model):
    __tablename__ = 'linked_accounts'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    bank_code    = db.Column(db.String(20))
    bank_name    = db.Column(db.String(50))
    account_type = db.Column(db.String(20), default='checking')  # checking/savings/credit
    account_num  = db.Column(db.String(30))   # 마스킹: ****-****-1234
    balance      = db.Column(db.Float, default=0)
    last_sync    = db.Column(db.DateTime)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    user         = db.relationship('User', backref='linked_accounts')


# ── 웹 푸시 구독 ─────────────────────────────────
class PushSubscription(db.Model):
    __tablename__ = 'push_subscriptions'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    endpoint   = db.Column(db.Text, nullable=False)
    p256dh     = db.Column(db.Text)
    auth_key   = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship('User', backref='push_subscriptions')
