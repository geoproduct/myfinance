from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import (db, Post, PostLike, Comment, Group, GroupMember,
                    Challenge, ChallengeMember, Notification, Transaction)
from datetime import date, datetime

social_bp = Blueprint('social', __name__)

PCATS = [('tip','💡','절약팁'),('investment','📊','투자'),
         ('budget','📋','가계부'),('question','❓','질문')]


# ── 피드 ────────────────────────────────────────
@social_bp.route('/')
@login_required
def index():
    cat  = request.args.get('cat', 'all')
    sort = request.args.get('sort','latest')
    page = request.args.get('page', 1, type=int)
    q = Post.query
    if cat != 'all': q = q.filter_by(category=cat)
    if sort == 'popular':
        from sqlalchemy import desc
        q = q.order_by(desc(Post.likes), desc(Post.created_at))
    else:
        from sqlalchemy import desc
        q = q.order_by(desc(Post.created_at))
    pg    = q.paginate(page=page, per_page=10, error_out=False)
    liked = {pl.post_id for pl in PostLike.query.filter_by(user_id=current_user.id).all()}
    my_groups = GroupMember.query.filter_by(user_id=current_user.id).all()
    today = date.today()
    my_ch = []
    for cm in ChallengeMember.query.filter_by(user_id=current_user.id).all():
        ch = cm.challenge
        if ch.period_end and ch.period_end >= today:
            pct = int(cm.current_amount / ch.target_amount * 100) if ch.target_amount else 0
            my_ch.append({'ch': ch, 'cm': cm, 'pct': min(pct,100)})
    return render_template('social/index.html',
        posts=pg.items, pg=pg, liked=liked, cat=cat, sort=sort,
        pcats=PCATS, my_groups=my_groups, my_ch=my_ch)


@social_bp.route('/post/new', methods=['GET','POST'])
@login_required
def new_post():
    if request.method == 'POST':
        content = request.form.get('content','').strip()
        if len(content) < 5:
            flash('내용을 5자 이상 입력해 주세요.', 'danger')
            return redirect(request.url)
        p = Post(user_id=current_user.id, content=content,
                 category=request.form.get('category','tip'),
                 is_anonymous=request.form.get('is_anonymous')=='on')
        db.session.add(p); db.session.commit()
        flash('게시글이 등록되었습니다.', 'success')
        return redirect(url_for('social.index'))
    return render_template('social/new_post.html', pcats=PCATS)


@social_bp.route('/post/<int:pid>')
@login_required
def post_detail(pid):
    p     = Post.query.get_or_404(pid)
    liked = PostLike.query.filter_by(post_id=pid, user_id=current_user.id).first() is not None
    tops  = Comment.query.filter_by(post_id=pid, parent_id=None)\
                   .order_by(Comment.created_at).all()
    return render_template('social/post_detail.html', post=p, liked=liked,
                           top_comments=tops, pcats=PCATS)


@social_bp.route('/post/<int:pid>/like', methods=['POST'])
@login_required
def like_post(pid):
    p = Post.query.get_or_404(pid)
    ex = PostLike.query.filter_by(post_id=pid, user_id=current_user.id).first()
    if ex:
        db.session.delete(ex); p.likes = max(0, p.likes-1); liked=False
    else:
        db.session.add(PostLike(post_id=pid, user_id=current_user.id))
        p.likes += 1; liked=True
    db.session.commit()
    return jsonify(likes=p.likes, liked=liked)


@social_bp.route('/post/<int:pid>/comment', methods=['POST'])
@login_required
def add_comment(pid):
    c = Comment(post_id=pid, user_id=current_user.id,
                content=request.form.get('content','').strip(),
                parent_id=request.form.get('parent_id', type=int))
    db.session.add(c); db.session.commit()
    return redirect(url_for('social.post_detail', pid=pid))


@social_bp.route('/post/<int:pid>/delete', methods=['POST'])
@login_required
def delete_post(pid):
    p = Post.query.filter_by(id=pid, user_id=current_user.id).first_or_404()
    db.session.delete(p); db.session.commit()
    flash('삭제되었습니다.', 'success')
    return redirect(url_for('social.index'))


# ── 그룹 ────────────────────────────────────────
@social_bp.route('/groups')
@login_required
def groups():
    ms = GroupMember.query.filter_by(user_id=current_user.id).all()
    return render_template('social/groups.html', memberships=ms)


@social_bp.route('/groups/create', methods=['POST'])
@login_required
def create_group():
    name = request.form.get('name','').strip()
    if len(name) < 2: flash('그룹명 2자 이상', 'danger'); return redirect(url_for('social.groups'))
    g = Group(name=name, owner_id=current_user.id)
    db.session.add(g); db.session.flush()
    db.session.add(GroupMember(group_id=g.id, user_id=current_user.id, role='owner'))
    db.session.commit()
    flash(f'"{name}" 생성 완료! 초대코드: {g.invite_code}', 'success')
    return redirect(url_for('social.group_detail', gid=g.id))


@social_bp.route('/groups/join', methods=['POST'])
@login_required
def join_group():
    code = request.form.get('invite_code','').strip().upper()
    g = Group.query.filter_by(invite_code=code).first()
    if not g: flash('유효하지 않은 코드입니다.', 'danger'); return redirect(url_for('social.groups'))
    if GroupMember.query.filter_by(group_id=g.id, user_id=current_user.id).first():
        flash('이미 가입된 그룹입니다.', 'info')
    elif GroupMember.query.filter_by(group_id=g.id).count() >= 10:
        flash('최대 인원 초과', 'danger')
    else:
        db.session.add(GroupMember(group_id=g.id, user_id=current_user.id, role='editor'))
        db.session.commit(); flash(f'"{g.name}" 가입 완료!', 'success')
    return redirect(url_for('social.group_detail', gid=g.id))


@social_bp.route('/groups/<int:gid>')
@login_required
def group_detail(gid):
    g   = Group.query.get_or_404(gid)
    me  = GroupMember.query.filter_by(group_id=gid, user_id=current_user.id).first_or_404()
    txns= Transaction.query.filter_by(group_id=gid).order_by(Transaction.date.desc()).limit(30).all()
    settle = {}
    for t in txns:
        if t.type == 'expense':
            settle[t.user_id] = settle.get(t.user_id, 0) + t.amount
    return render_template('social/group_detail.html', group=g, me=me,
                           members=g.members.all(), txns=txns, settle=settle,
                           today=date.today())


# ── 챌린지 ──────────────────────────────────────
@social_bp.route('/challenges')
@login_required
def challenges():
    today   = date.today()
    public  = Challenge.query.filter(Challenge.is_public == True,
                                     Challenge.period_end >= today)\
                .order_by(Challenge.created_at.desc()).all()
    joined  = {cm.challenge_id for cm in
               ChallengeMember.query.filter_by(user_id=current_user.id).all()}
    return render_template('social/challenges.html', challenges=public,
                           joined=joined, today=today)


@social_bp.route('/challenges/create', methods=['POST'])
@login_required
def create_challenge():
    try:
        target = float(request.form.get('target_amount','0').replace(',',''))
        ps = datetime.strptime(request.form.get('period_start',''), '%Y-%m-%d').date()
        pe = datetime.strptime(request.form.get('period_end',''),   '%Y-%m-%d').date()
    except ValueError:
        flash('날짜 또는 금액을 올바르게 입력해 주세요.', 'danger')
        return redirect(url_for('social.challenges'))
    ch = Challenge(creator_id=current_user.id,
                   title=request.form.get('title','').strip(),
                   description=request.form.get('description','').strip(),
                   target_amount=target, period_start=ps, period_end=pe,
                   is_public=request.form.get('is_public') != 'off')
    db.session.add(ch); db.session.flush()
    db.session.add(ChallengeMember(challenge_id=ch.id, user_id=current_user.id))
    db.session.commit()
    flash('챌린지가 생성되었습니다!', 'success')
    return redirect(url_for('social.challenge_detail', cid=ch.id))


@social_bp.route('/challenges/<int:cid>')
@login_required
def challenge_detail(cid):
    ch = Challenge.query.get_or_404(cid)
    me = ChallengeMember.query.filter_by(challenge_id=cid, user_id=current_user.id).first()
    members = ChallengeMember.query.filter_by(challenge_id=cid)\
                .order_by(ChallengeMember.current_amount.desc()).all()
    return render_template('social/challenge_detail.html', ch=ch, me=me,
                           members=members, today=date.today())


@social_bp.route('/challenges/<int:cid>/join', methods=['POST'])
@login_required
def join_challenge(cid):
    ch = Challenge.query.get_or_404(cid)
    if not ChallengeMember.query.filter_by(challenge_id=cid, user_id=current_user.id).first():
        db.session.add(ChallengeMember(challenge_id=cid, user_id=current_user.id))
        db.session.commit(); flash('챌린지 참가 완료!', 'success')
    return redirect(url_for('social.challenge_detail', cid=cid))


@social_bp.route('/challenges/<int:cid>/update', methods=['POST'])
@login_required
def update_challenge(cid):
    cm = ChallengeMember.query.filter_by(challenge_id=cid, user_id=current_user.id).first_or_404()
    try:
        cm.current_amount += float(request.form.get('amount','0').replace(',',''))
    except ValueError:
        pass
    db.session.commit(); flash('진행 현황 업데이트!', 'success')
    return redirect(url_for('social.challenge_detail', cid=cid))
