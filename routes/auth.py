import os, re
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app, jsonify)
from flask_login import login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from models import db, User, Notification

auth_bp = Blueprint('auth', __name__)
PW_RE   = re.compile(r'^(?=.*[A-Za-z])(?=.*\d)(?=.*[!@#$%^&*]).{8,}$')

oauth = OAuth()


def init_oauth(app):
    """앱 초기화 시 OAuth 클라이언트 등록"""
    os.environ.setdefault('AUTHLIB_INSECURE_TRANSPORT', '1')   # 개발용 HTTP 허용
    oauth.init_app(app)

    if app.config.get('GOOGLE_CLIENT_ID'):
        oauth.register(
            name='google',
            client_id=app.config['GOOGLE_CLIENT_ID'],
            client_secret=app.config['GOOGLE_CLIENT_SECRET'],
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'},
        )

    if app.config.get('KAKAO_CLIENT_ID'):
        oauth.register(
            name='kakao',
            client_id=app.config['KAKAO_CLIENT_ID'],
            client_secret=app.config.get('KAKAO_CLIENT_SECRET') or None,
            access_token_url='https://kauth.kakao.com/oauth/token',
            authorize_url='https://kauth.kakao.com/oauth/authorize',
            api_base_url='https://kapi.kakao.com',
            client_kwargs={'scope': 'profile_nickname account_email'},
        )


# ── 이메일 로그인 ─────────────────────────────────
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        pw    = request.form.get('password', '')
        user  = User.query.filter_by(email=email).first()
        if user and user.check_password(pw):
            login_user(user, remember=True)
            return redirect(request.args.get('next') or url_for('dashboard.index'))
        flash('이메일 또는 비밀번호가 올바르지 않습니다.', 'danger')
    return render_template('auth/login.html',
        google_enabled=bool(current_app.config.get('GOOGLE_CLIENT_ID')),
        kakao_enabled=bool(current_app.config.get('KAKAO_CLIENT_ID')))


# ── 회원가입 ──────────────────────────────────────
@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        pw       = request.form.get('password', '')
        pw2      = request.form.get('password2', '')
        nickname = request.form.get('nickname', '').strip()
        if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            flash('올바른 이메일을 입력해 주세요.', 'danger')
        elif not PW_RE.match(pw):
            flash('비밀번호: 영문+숫자+특수문자 8자 이상', 'danger')
        elif pw != pw2:
            flash('비밀번호가 일치하지 않습니다.', 'danger')
        elif len(nickname) < 2:
            flash('닉네임은 2자 이상이어야 합니다.', 'danger')
        elif User.query.filter_by(email=email).first():
            flash('이미 가입된 이메일입니다.', 'danger')
        else:
            u = User(email=email, nickname=nickname, onboarding_done=True)
            u.set_password(pw)
            db.session.add(u)
            db.session.commit()
            login_user(u)
            flash('회원가입 완료!', 'success')
            return redirect(url_for('dashboard.index'))
    return render_template('auth/signup.html')


# ── 로그아웃 ──────────────────────────────────────
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


# ── 계정 설정 ─────────────────────────────────────
@auth_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'profile':
            nick = request.form.get('nickname', '').strip()
            inc  = request.form.get('monthly_income', '0').replace(',', '')
            if len(nick) >= 2:
                current_user.nickname = nick
            try:
                current_user.monthly_income = float(inc)
            except ValueError:
                pass
            db.session.commit()
            flash('프로필이 수정되었습니다.', 'success')
        elif action == 'password':
            old  = request.form.get('old_pw', '')
            new  = request.form.get('new_pw', '')
            new2 = request.form.get('new_pw2', '')
            if not current_user.check_password(old):
                flash('현재 비밀번호가 올바르지 않습니다.', 'danger')
            elif not PW_RE.match(new):
                flash('새 비밀번호: 영문+숫자+특수문자 8자 이상', 'danger')
            elif new != new2:
                flash('새 비밀번호가 일치하지 않습니다.', 'danger')
            else:
                current_user.set_password(new)
                db.session.commit()
                flash('비밀번호가 변경되었습니다.', 'success')
        return redirect(url_for('auth.settings'))
    return render_template('auth/settings.html')


# ── Google OAuth ──────────────────────────────────
@auth_bp.route('/google')
def google_login():
    if not current_app.config.get('GOOGLE_CLIENT_ID'):
        flash('Google 로그인 미설정. .env에 GOOGLE_CLIENT_ID/SECRET 입력 필요.', 'warning')
        return redirect(url_for('auth.login'))
    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/google/callback')
def google_callback():
    try:
        token     = oauth.google.authorize_access_token()
        user_info = token.get('userinfo') or oauth.google.userinfo()
        email     = user_info['email'].lower()
        nickname  = user_info.get('name', email.split('@')[0])
    except Exception as e:
        flash(f'Google 로그인 실패: {e}', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, nickname=nickname,
                    provider='google', is_verified=True, onboarding_done=True)
        db.session.add(user)
        db.session.commit()
        flash(f'구글 계정으로 가입되었습니다. 환영합니다, {nickname}님!', 'success')
    login_user(user, remember=True)
    return redirect(url_for('dashboard.index'))


# ── Kakao OAuth ───────────────────────────────────
@auth_bp.route('/kakao')
def kakao_login():
    if not current_app.config.get('KAKAO_CLIENT_ID'):
        flash('카카오 로그인 미설정. .env에 KAKAO_CLIENT_ID 입력 필요.', 'warning')
        return redirect(url_for('auth.login'))
    redirect_uri = url_for('auth.kakao_callback', _external=True)
    return oauth.kakao.authorize_redirect(redirect_uri)


@auth_bp.route('/kakao/callback')
def kakao_callback():
    try:
        token   = oauth.kakao.authorize_access_token()
        resp    = oauth.kakao.get('https://kapi.kakao.com/v2/user/me', token=token)
        profile = resp.json()
        account = profile.get('kakao_account', {})
        email   = account.get('email', f"kakao_{profile['id']}@kakao.local")
        nickname = account.get('profile', {}).get('nickname',
                                f"카카오유저{str(profile['id'])[-4:]}")
    except Exception as e:
        flash(f'카카오 로그인 실패: {e}', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email, nickname=nickname,
                    provider='kakao', is_verified=True, onboarding_done=True)
        db.session.add(user)
        db.session.commit()
        flash(f'카카오 계정으로 가입되었습니다. 환영합니다, {nickname}님!', 'success')
    login_user(user, remember=True)
    return redirect(url_for('dashboard.index'))


# ── 알림 모두 읽음 ────────────────────────────────
@auth_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def notifications_read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .update({'is_read': True})
    db.session.commit()
    return jsonify(ok=True)


# ── 개발용 빠른 로그인 ────────────────────────────
@auth_bp.route('/dev/<int:uid>')
def dev_login(uid=1):
    if not current_app.debug:
        return 'dev only', 403
    u = User.query.get(uid) or User.query.first()
    if u:
        login_user(u, remember=True)
        return redirect(url_for('dashboard.index'))
    return '유저 없음', 404
