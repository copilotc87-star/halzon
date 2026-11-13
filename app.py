# -*- coding: utf-8 -*-
"""
Halzon v5.0 — پیام‌رسان + کلاس + آزمون + فایل + گروه + پشتیبانی + تبلیغات + مدیریت ورود
"""

import os
import sqlite3
import uuid
import zipfile
import shutil
from datetime import datetime
from flask import Flask, request, jsonify, session, send_from_directory, redirect, send_file
from flask_socketio import SocketIO, join_room
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# تغییر مسیرها به /data برای دائمی شدن روی Fly.io
UPLOAD_DIR = '/data/uploads'
SITE_DIR = '/data/sites'
ADS_DIR = '/data/ads'
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SITE_DIR, exist_ok=True)
os.makedirs(ADS_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "halzon-secret-2024"
app.config['UPLOAD_FOLDER'] = UPLOAD_DIR
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

DB = '/data/chat.db'
ADMIN_USER = "admin"
ADMIN_PASS = "1234"
SITE_NAME = "کلام برتري ها"

def init_db():
    conn = sqlite3.connect(DB)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL, last_name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        avatar_color TEXT DEFAULT '#6366f1', bio TEXT DEFAULT '',
        is_online INTEGER DEFAULT 0, last_seen TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        meet_link TEXT DEFAULT '', description TEXT DEFAULT '',
        teacher TEXT DEFAULT '', schedule TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        url TEXT DEFAULT '', description TEXT DEFAULT '',
        file_path TEXT DEFAULT '', type TEXT DEFAULT 'link',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL, receiver_id INTEGER NOT NULL,
        type TEXT NOT NULL DEFAULT 'text', content TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        description TEXT DEFAULT '', duration_minutes INTEGER DEFAULT 10,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER NOT NULL,
        text TEXT NOT NULL, option_a TEXT, option_b TEXT,
        option_c TEXT, option_d TEXT, correct TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS exam_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, exam_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL, score INTEGER DEFAULT 0,
        total INTEGER DEFAULT 0, started_at TEXT DEFAULT CURRENT_TIMESTAMP,
        finished_at TEXT
    );
    CREATE TABLE IF NOT EXISTS answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL, chosen TEXT
    );
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, filename TEXT, original_name TEXT,
        file_type TEXT, size INTEGER,
        uploaded_by INTEGER, is_public INTEGER DEFAULT 1,
        site_folder TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        created_by INTEGER,
        is_public INTEGER DEFAULT 1,
        is_support INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS group_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(group_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS group_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        type TEXT NOT NULL DEFAULT 'text',
        content TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS ads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT DEFAULT '',
        description TEXT DEFAULT '',
        link TEXT DEFAULT '',
        image_filename TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.execute("INSERT INTO groups (name, description, is_public, is_support) SELECT 'گفتگوی عمومی', 'چت گروهی همه کاربران', 1, 0 WHERE NOT EXISTS (SELECT 1 FROM groups WHERE name='گفتگوی عمومی')")
    conn.execute("INSERT INTO groups (name, description, is_public, is_support) SELECT 'پشتیبانی', 'پرسش و پاسخ با ادمین', 1, 1 WHERE NOT EXISTS (SELECT 1 FROM groups WHERE is_support=1)")
    conn.commit()
    conn.close()

init_db()

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def now():
    return datetime.now().isoformat()

AVATAR_COLORS = ['#6366f1','#8b5cf6','#ec4899','#ef4444','#f59e0b',
                 '#10b981','#14b8a6','#3b82f6','#06b6d4','#84cc16']

def pick_color(phone):
    return AVATAR_COLORS[sum(ord(c) for c in phone) % len(AVATAR_COLORS)]

def current_user():
    uid = session.get('user_id')
    if not uid: return None
    conn = db()
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return dict(u) if u else None

def is_admin():
    return session.get('is_admin') is True

# ═══════════ AUTH ═══════════
@app.route('/api/register', methods=['POST'])
def api_register():
    d = request.json or {}
    fn = (d.get('first_name') or '').strip()
    ln = (d.get('last_name') or '').strip()
    ph = (d.get('phone') or '').strip()
    pw = (d.get('password') or '').strip()
    if not all([fn, ln, ph, pw]):
        return jsonify(ok=False, msg='همه فیلدها را پر کنید'), 400
    
    conn = db()
    ex = conn.execute("SELECT * FROM users WHERE phone=?", (ph,)).fetchone()
    
    # سیستم قفل ورود: فقط کسانی که ادمین از قبل ساخته می‌تونن وارد بشن
    if not ex:
        conn.close()
        return jsonify(ok=False, msg='شما مجاز به ورود نیستید. با ادمین تماس بگیرید.'), 401
        
    if not check_password_hash(ex['password'], pw):
        conn.close()
        return jsonify(ok=False, msg='رمز اشتباه است'), 401
        
    uid = ex['id']
    conn.execute("UPDATE users SET is_online=1, last_seen=? WHERE id=?", (now(), uid))
    conn.commit()
    conn.close()
    session['user_id'] = uid
    session['name'] = f"{ex['first_name']} {ex['last_name']}"
    return jsonify(ok=True, user_id=uid, name=session['name'])

@app.route('/api/logout', methods=['POST'])
def api_logout():
    uid = session.get('user_id')
    if uid:
        conn = db()
        conn.execute("UPDATE users SET is_online=0, last_seen=? WHERE id=?", (now(), uid))
        conn.commit(); conn.close()
    session.clear()
    return jsonify(ok=True)

@app.route('/api/me')
def api_me():
    u = current_user()
    if not u: return jsonify(ok=False), 401
    return jsonify(ok=True, user_id=u['id'], name=f"{u['first_name']} {u['last_name']}",
                   first_name=u['first_name'], last_name=u['last_name'],
                   phone=u['phone'], avatar_color=u['avatar_color'])

# ═══════════ کلاس‌ها و ویدیوها ═══════════
@app.route('/api/classes')
def api_classes():
    conn = db()
    rows = conn.execute("SELECT * FROM classes ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/videos')
def api_videos():
    conn = db()
    rows = conn.execute("SELECT * FROM videos ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ═══════════ کاربران و چت خصوصی ═══════════
@app.route('/api/users')
def api_users():
    u = current_user()
    if not u: return jsonify(ok=False), 401
    conn = db()
    rows = conn.execute("""SELECT id,first_name,last_name,phone,is_online,
                                  last_seen,avatar_color,bio FROM users WHERE id!=?""",
                        (u['id'],)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d['unread'] = conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE sender_id=? AND receiver_id=? AND is_read=0",
            (d['id'], u['id'])).fetchone()['c']
        result.append(d)
    conn.close()
    return jsonify(result)

@app.route('/api/messages/<int:other>')
def api_messages(other):
    u = current_user()
    if not u: return jsonify(ok=False), 401
    conn = db()
    conn.execute("UPDATE messages SET is_read=1 WHERE sender_id=? AND receiver_id=?",
                 (other, u['id']))
    conn.commit()
    rows = conn.execute("""SELECT * FROM messages
        WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
        ORDER BY id ASC LIMIT 300""",
        (u['id'], other, other, u['id'])).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/send_text', methods=['POST'])
def api_send_text():
    u = current_user()
    if not u: return jsonify(ok=False), 401
    d = request.json or {}
    to_id = d.get('to_id')
    text = (d.get('text') or '').strip()
    if not text or not to_id: return jsonify(ok=False), 400
    conn = db()
    cur = conn.execute(
        "INSERT INTO messages (sender_id,receiver_id,type,content) VALUES (?,?,?,?)",
        (u['id'], to_id, 'text', text))
    conn.commit(); mid = cur.lastrowid; conn.close()
    msg = {'id': mid, 'sender_id': u['id'], 'receiver_id': to_id,
           'type': 'text', 'content': text, 'created_at': now()}
    socketio.emit('new_message', msg, room=f"user_{to_id}")
    socketio.emit('new_message', msg, room=f"user_{u['id']}")
    return jsonify(ok=True, msg=msg)

@app.route('/api/send_file', methods=['POST'])
def api_send_file():
    u = current_user()
    if not u: return jsonify(ok=False), 401
    to_id = request.form.get('to_id')
    ftype = request.form.get('type', 'file')
    f = request.files.get('file')
    if not to_id or not f: return jsonify(ok=False), 400
    ext = f.filename.rsplit('.', 1)[-1] if '.' in f.filename else 'bin'
    fname = f"{ftype}_{uuid.uuid4().hex}.{ext}"
    f.save(os.path.join(UPLOAD_DIR, fname))
    conn = db()
    cur = conn.execute(
        "INSERT INTO messages (sender_id,receiver_id,type,content) VALUES (?,?,?,?)",
        (u['id'], to_id, ftype, fname))
    conn.commit(); mid = cur.lastrowid; conn.close()
    msg = {'id': mid, 'sender_id': u['id'], 'receiver_id': to_id,
           'type': ftype, 'content': f"/uploads/{fname}", 'created_at': now()}
    socketio.emit('new_message', msg, room=f"user_{to_id}")
    socketio.emit('new_message', msg, room=f"user_{u['id']}")
    return jsonify(ok=True, msg=msg)

@app.route('/api/typing', methods=['POST'])
def api_typing():
    u = current_user()
    if not u: return jsonify(ok=False), 401
    to = (request.json or {}).get('to')
    socketio.emit('typing', {'from': u['id'], 'to': to}, room=f"user_{to}")
    return jsonify(ok=True)

# ═══════════ گروه‌ها ═══════════
@app.route('/api/groups')
def api_groups():
    u = current_user()
    if not u: return jsonify(ok=False), 401
    conn = db()
    rows = conn.execute("""SELECT g.*, 
                           (SELECT COUNT(*) FROM group_members WHERE group_id=g.id) AS member_count
                           FROM groups g WHERE g.is_public=1 
                           OR g.id IN (SELECT group_id FROM group_members WHERE user_id=?)
                           ORDER BY g.is_support DESC, g.id ASC""",
                        (u['id'],)).fetchall()
    out = []
    for r in rows:
        g = dict(r)
        last = conn.execute("""SELECT content, type, created_at FROM group_messages
                               WHERE group_id=? ORDER BY id DESC LIMIT 1""",
                            (g['id'],)).fetchone()
        g['last_msg'] = dict(last) if last else None
        g['unread'] = conn.execute("""
            SELECT COUNT(*) AS c FROM group_messages gm
            WHERE gm.group_id=? AND gm.sender_id!=? AND gm.id > COALESCE(
                (SELECT MAX(id) FROM group_messages WHERE group_id=? AND sender_id=?), 0)
        """, (g['id'], u['id'], g['id'], u['id'])).fetchone()['c']
        out.append(g)
    conn.close()
    return jsonify(out)

@app.route('/api/group/<int:gid>/messages')
def api_group_messages(gid):
    u = current_user()
    if not u: return jsonify(ok=False), 401
    conn = db()
    rows = conn.execute("""SELECT gm.*, us.first_name, us.last_name, us.avatar_color
        FROM group_messages gm JOIN users us ON us.id=gm.sender_id
        WHERE gm.group_id=? ORDER BY gm.id ASC LIMIT 300""", (gid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/group/send', methods=['POST'])
def api_group_send():
    u = current_user()
    if not u: return jsonify(ok=False), 401
    d = request.json or {}
    gid = d.get('group_id')
    text = (d.get('text') or '').strip()
    if not gid or not text: return jsonify(ok=False), 400
    conn = db()
    cur = conn.execute(
        "INSERT INTO group_messages (group_id,sender_id,type,content) VALUES (?,?,?,?)",
        (gid, u['id'], 'text', text))
    conn.commit(); mid = cur.lastrowid; conn.close()
    msg = {'id': mid, 'group_id': gid, 'sender_id': u['id'], 'type': 'text',
           'content': text, 'created_at': now(),
           'first_name': u['first_name'], 'last_name': u['last_name'],
           'avatar_color': u['avatar_color']}
    socketio.emit('new_group_message', msg, room=f"group_{gid}")
    return jsonify(ok=True, msg=msg)

@app.route('/api/group/send_file', methods=['POST'])
def api_group_send_file():
    u = current_user()
    if not u: return jsonify(ok=False), 401
    gid = request.form.get('group_id')
    ftype = request.form.get('type', 'file')
    f = request.files.get('file')
    if not gid or not f: return jsonify(ok=False), 400
    ext = f.filename.rsplit('.', 1)[-1] if '.' in f.filename else 'bin'
    fname = f"{ftype}_{uuid.uuid4().hex}.{ext}"
    f.save(os.path.join(UPLOAD_DIR, fname))
    conn = db()
    cur = conn.execute(
        "INSERT INTO group_messages (group_id,sender_id,type,content) VALUES (?,?,?,?)",
        (gid, u['id'], ftype, fname))
    conn.commit(); mid = cur.lastrowid; conn.close()
    msg = {'id': mid, 'group_id': gid, 'sender_id': u['id'], 'type': ftype,
           'content': f"/uploads/{fname}", 'created_at': now(),
           'first_name': u['first_name'], 'last_name': u['last_name'],
           'avatar_color': u['avatar_color']}
    socketio.emit('new_group_message', msg, room=f"group_{gid}")
    return jsonify(ok=True, msg=msg)

@app.route('/api/group/<int:gid>/members')
def api_group_members(gid):
    if not current_user() and not is_admin(): return jsonify(ok=False), 401
    conn = db()
    rows = conn.execute("""SELECT u.id, u.first_name, u.last_name, u.avatar_color, u.is_online
        FROM group_members gm JOIN users u ON u.id=gm.user_id WHERE gm.group_id=?""", (gid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/groups', methods=['GET','POST'])
def admin_groups():
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    if request.method == 'POST':
        d = request.json or {}
        name = (d.get('name') or '').strip()
        if not name:
            conn.close(); return jsonify(ok=False, msg='نام الزامی'), 400
        cur = conn.execute("INSERT INTO groups (name,description,created_by,is_public) VALUES (?,?,?,?)",
                           (name, d.get('description','').strip(), 0, 1 if d.get('is_public', 1) else 0))
        conn.commit(); gid = cur.lastrowid; conn.close()
        return jsonify(ok=True, id=gid)
    rows = conn.execute("""SELECT g.*, 
                           (SELECT COUNT(*) FROM group_members WHERE group_id=g.id) AS member_count,
                           (SELECT COUNT(*) FROM group_messages WHERE group_id=g.id) AS msg_count
                           FROM groups g ORDER BY g.is_support DESC, g.id ASC""").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/groups/<int:gid>', methods=['DELETE'])
def admin_del_group(gid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    g = conn.execute("SELECT is_support FROM groups WHERE id=?", (gid,)).fetchone()
    if g and g['is_support']:
        conn.close(); return jsonify(ok=False, msg='گروه پشتیبانی قابل حذف نیست'), 400
    conn.execute("DELETE FROM group_messages WHERE group_id=?", (gid,))
    conn.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
    conn.execute("DELETE FROM groups WHERE id=?", (gid,))
    conn.commit(); conn.close()
    return jsonify(ok=True)

# ═══════════ تبلیغات ═══════════
@app.route('/api/ads')
def api_ads():
    conn = db()
    rows = conn.execute("SELECT id,title,description,link,image_filename FROM ads WHERE is_active=1 ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/ads/<path:fn>')
def route_ads(fn):
    return send_from_directory(ADS_DIR, fn)

@app.route('/api/admin/ads', methods=['GET','POST'])
def admin_ads():
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        link = request.form.get('link', '').strip()
        f = request.files.get('image')
        if not f: 
            conn.close(); return jsonify(ok=False, msg='عکس الزامی است'), 400
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else 'jpg'
        if ext not in ('jpg','jpeg','png','gif','webp','svg'):
            conn.close(); return jsonify(ok=False, msg='فرمت عکس پشتیبانی نمی‌شود'), 400
        fname = f"ad_{uuid.uuid4().hex}.{ext}"
        f.save(os.path.join(ADS_DIR, fname))
        cur = conn.execute("INSERT INTO ads (title,description,link,image_filename) VALUES (?,?,?,?)",
                           (title, description, link, fname))
        conn.commit(); aid = cur.lastrowid; conn.close()
        return jsonify(ok=True, id=aid)
    rows = conn.execute("SELECT * FROM ads ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/ads/<int:aid>', methods=['DELETE','PUT'])
def admin_edit_ad(aid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    if request.method == 'DELETE':
        ad = conn.execute("SELECT image_filename FROM ads WHERE id=?", (aid,)).fetchone()
        if ad:
            try: os.remove(os.path.join(ADS_DIR, ad['image_filename']))
            except: pass
        conn.execute("DELETE FROM ads WHERE id=?", (aid,))
    else:
        d = request.json or {}
        if 'is_active' in d:
            conn.execute("UPDATE ads SET is_active=? WHERE id=?", (1 if d['is_active'] else 0, aid))
        if 'title' in d:
            conn.execute("UPDATE ads SET title=? WHERE id=?", (d['title'], aid))
        if 'description' in d:
            conn.execute("UPDATE ads SET description=? WHERE id=?", (d['description'], aid))
        if 'link' in d:
            conn.execute("UPDATE ads SET link=? WHERE id=?", (d['link'], aid))
    conn.commit(); conn.close()
    return jsonify(ok=True)

# ═══════════ آزمون ═══════════
@app.route('/api/exams')
def api_exams():
    u = current_user()
    if not u: return jsonify(ok=False), 401
    conn = db()
    rows = conn.execute("SELECT * FROM exams WHERE is_active=1 ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        e = dict(r)
        taken = conn.execute("""SELECT id,score,total,finished_at FROM exam_attempts
                                WHERE exam_id=? AND user_id=? AND finished_at IS NOT NULL
                                ORDER BY id DESC LIMIT 1""",
                             (e['id'], u['id'])).fetchone()
        e['my_attempt'] = dict(taken) if taken else None
        e['q_count'] = conn.execute("SELECT COUNT(*) AS c FROM questions WHERE exam_id=?",
                                    (e['id'],)).fetchone()['c']
        out.append(e)
    conn.close()
    return jsonify(out)

@app.route('/api/exam/<int:eid>/start', methods=['POST'])
def api_exam_start(eid):
    u = current_user()
    if not u: return jsonify(ok=False), 401
    conn = db()
    ex = conn.execute("SELECT * FROM exams WHERE id=? AND is_active=1", (eid,)).fetchone()
    if not ex:
        conn.close(); return jsonify(ok=False, msg='آزمون در دسترس نیست'), 404
    done = conn.execute(
        "SELECT id FROM exam_attempts WHERE exam_id=? AND user_id=? AND finished_at IS NOT NULL",
        (eid, u['id'])).fetchone()
    if done:
        conn.close(); return jsonify(ok=False, msg='قبلاً شرکت کرده‌اید'), 400
    qs = conn.execute(
        "SELECT id,text,option_a,option_b,option_c,option_d FROM questions WHERE exam_id=? ORDER BY id",
        (eid,)).fetchall()
    if not qs:
        conn.close(); return jsonify(ok=False, msg='سوالی تعریف نشده'), 400
    cur = conn.execute("INSERT INTO exam_attempts (exam_id,user_id,total) VALUES (?,?,?)",
                       (eid, u['id'], len(qs)))
    conn.commit(); aid = cur.lastrowid; conn.close()
    return jsonify(ok=True, attempt_id=aid, duration=ex['duration_minutes']*60,
                   title=ex['title'], questions=[dict(q) for q in qs])

@app.route('/api/attempt/<int:aid>/submit', methods=['POST'])
def api_attempt_submit(aid):
    u = current_user()
    if not u: return jsonify(ok=False), 401
    answers = (request.json or {}).get('answers', {})
    conn = db()
    att = conn.execute(
        "SELECT * FROM exam_attempts WHERE id=? AND user_id=? AND finished_at IS NULL",
        (aid, u['id'])).fetchone()
    if not att:
        conn.close(); return jsonify(ok=False, msg='آزمون معتبر نیست'), 400
    qs = conn.execute("SELECT id,correct FROM questions WHERE exam_id=?",
                      (att['exam_id'],)).fetchall()
    cmap = {q['id']: q['correct'] for q in qs}
    score = 0
    for qid_str, chosen in answers.items():
        qid = int(qid_str)
        if qid in cmap and cmap[qid] == chosen: score += 1
        conn.execute("INSERT INTO answers (attempt_id,question_id,chosen) VALUES (?,?,?)",
                     (aid, qid, chosen))
    conn.execute("UPDATE exam_attempts SET score=?, finished_at=? WHERE id=?",
                 (score, now(), aid))
    conn.commit(); total = att['total']; conn.close()
    return jsonify(ok=True, score=score, total=total)

@app.route('/api/exam/<int:eid>/leaderboard')
def api_leaderboard(eid):
    conn = db()
    rows = conn.execute("""
        SELECT a.score, a.total, a.finished_at,
               u.first_name, u.last_name, u.avatar_color
        FROM exam_attempts a JOIN users u ON u.id=a.user_id
        WHERE a.exam_id=? AND a.finished_at IS NOT NULL
        ORDER BY a.score DESC, a.finished_at ASC LIMIT 30
    """, (eid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ═══════════ فایل‌ها ═══════════
@app.route('/api/files')
def api_files():
    conn = db()
    rows = conn.execute("""SELECT f.*, u.first_name, u.last_name
                           FROM files f LEFT JOIN users u ON u.id=f.uploaded_by
                           WHERE f.is_public=1 ORDER BY f.id DESC""").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/upload', methods=['POST'])
def api_upload():
    if not is_admin():
        u = current_user()
        if not u: return jsonify(ok=False), 401
    title = request.form.get('title', '').strip()
    f = request.files.get('file')
    if not f: return jsonify(ok=False, msg='فایلی ارسال نشد'), 400
    original = f.filename
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else 'bin'
    uid_hex = uuid.uuid4().hex
    fname = f"file_{uid_hex}.{ext}"
    fpath = os.path.join(UPLOAD_DIR, fname)
    f.save(fpath)
    size = os.path.getsize(fpath)
    ftype = ext
    site_folder = ''

    if ext == 'zip':
        site_folder = f"site_{uid_hex}"
        target = os.path.join(SITE_DIR, site_folder)
        os.makedirs(target, exist_ok=True)
        try:
            with zipfile.ZipFile(fpath, 'r') as z:
                z.extractall(target)
            items = os.listdir(target)
            if len(items) == 1 and os.path.isdir(os.path.join(target, items[0])):
                inner = os.path.join(target, items[0])
                for it in os.listdir(inner):
                    shutil.move(os.path.join(inner, it), os.path.join(target, it))
                os.rmdir(inner)
            ftype = 'zip'
        except Exception as e:
            return jsonify(ok=False, msg=f'خطای ZIP: {e}'), 400

    conn = db()
    u = current_user()
    uploader = u['id'] if u else 0
    cur = conn.execute("""INSERT INTO files (title,filename,original_name,file_type,size,uploaded_by,site_folder)
                          VALUES (?,?,?,?,?,?,?)""",
                       (title or original, fname, original, ftype, size, uploader, site_folder))
    conn.commit(); fid = cur.lastrowid; conn.close()
    return jsonify(ok=True, id=fid)

@app.route('/api/file/<int:fid>/delete', methods=['POST'])
def api_delete_file(fid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    if not f:
        conn.close(); return jsonify(ok=False), 404
    try: os.remove(os.path.join(UPLOAD_DIR, f['filename']))
    except: pass
    if f['site_folder']:
        shutil.rmtree(os.path.join(SITE_DIR, f['site_folder']), ignore_errors=True)
    conn.execute("DELETE FROM files WHERE id=?", (fid,))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route('/api/admin/files')
def api_admin_files():
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    rows = conn.execute("""SELECT f.*, u.first_name, u.last_name
                           FROM files f LEFT JOIN users u ON u.id=f.uploaded_by
                           ORDER BY f.id DESC""").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ═══════════ ادمین ═══════════
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    d = request.json or {}
    if d.get('username') == ADMIN_USER and d.get('password') == ADMIN_PASS:
        session['is_admin'] = True
        return jsonify(ok=True)
    return jsonify(ok=False, msg='نام کاربری یا رمز اشتباه'), 401

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('is_admin', None)
    return jsonify(ok=True)

@app.route('/api/admin/check')
def admin_check():
    return jsonify(ok=is_admin())

# -- مدیریت دانش‌آموزان (جدید) --
@app.route('/api/admin/students', methods=['GET', 'POST'])
def admin_students():
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    if request.method == 'POST':
        d = request.json or {}
        fn = (d.get('first_name') or '').strip()
        ln = (d.get('last_name') or '').strip()
        ph = (d.get('phone') or '').strip()
        pw = (d.get('password') or '').strip()
        if not all([fn, ln, ph, pw]):
            conn.close(); return jsonify(ok=False, msg='همه فیلدها الزامی است'), 400
        
        ex = conn.execute("SELECT id FROM users WHERE phone=?", (ph,)).fetchone()
        if ex:
            conn.execute("UPDATE users SET first_name=?, last_name=?, password=? WHERE id=?",
                         (fn, ln, generate_password_hash(pw), ex['id']))
        else:
            conn.execute("INSERT INTO users (first_name,last_name,phone,password,avatar_color) VALUES (?,?,?,?,?)",
                         (fn, ln, ph, generate_password_hash(pw), pick_color(ph)))
        conn.commit(); conn.close()
        return jsonify(ok=True)
    
    rows = conn.execute("SELECT id,first_name,last_name,phone,is_online FROM users ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/students/<int:uid>', methods=['DELETE'])
def admin_del_student(uid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    conn.execute("DELETE FROM messages WHERE sender_id=? OR receiver_id=?", (uid, uid))
    conn.execute("DELETE FROM group_messages WHERE sender_id=?", (uid,))
    conn.execute("DELETE FROM answers WHERE attempt_id IN (SELECT id FROM exam_attempts WHERE user_id=?)", (uid,))
    conn.execute("DELETE FROM exam_attempts WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit(); conn.close()
    return jsonify(ok=True)

# -- بقیه بخش‌های ادمین --
@app.route('/api/admin/classes', methods=['POST'])
def admin_add_class():
    if not is_admin(): return jsonify(ok=False), 403
    d = request.json or {}
    conn = db()
    conn.execute("INSERT INTO classes (name,meet_link,description,teacher,schedule) VALUES (?,?,?,?,?)",
                 (d.get('name','').strip(), d.get('meet_link','').strip(),
                  d.get('description','').strip(), d.get('teacher','').strip(),
                  d.get('schedule','').strip()))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route('/api/admin/classes/<int:cid>', methods=['PUT','DELETE'])
def admin_edit_class(cid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    if request.method == 'DELETE':
        conn.execute("DELETE FROM classes WHERE id=?", (cid,))
    else:
        d = request.json or {}
        conn.execute("""UPDATE classes SET name=?, meet_link=?, description=?, teacher=?, schedule=?
                        WHERE id=?""",
                     (d.get('name',''), d.get('meet_link',''), d.get('description',''),
                      d.get('teacher',''), d.get('schedule',''), cid))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route('/api/admin/videos', methods=['POST'])
def admin_add_video():
    if not is_admin(): return jsonify(ok=False), 403
    d = request.json or {}
    conn = db()
    conn.execute("INSERT INTO videos (title,url,description,type) VALUES (?,?,?,?)",
                 (d.get('title','').strip(), d.get('url','').strip(),
                  d.get('description','').strip(), 'link'))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route('/api/admin/videos/<int:vid>', methods=['DELETE'])
def admin_del_video(vid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    conn.execute("DELETE FROM videos WHERE id=?", (vid,))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route('/api/admin/users')
def admin_users():
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    rows = conn.execute("""SELECT id,first_name,last_name,phone,is_online,last_seen,
                                  avatar_color,created_at FROM users ORDER BY id DESC""").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/all_chats')
def admin_all_chats():
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    rows = conn.execute("""
        SELECT m.*,
               s.first_name AS s_fn, s.last_name AS s_ln,
               r.first_name AS r_fn, r.last_name AS r_ln
        FROM messages m
        JOIN users s ON s.id = m.sender_id
        JOIN users r ON r.id = m.receiver_id
        ORDER BY m.id ASC
    """).fetchall()
    conn.close()
    chats = {}
    for r in rows:
        key = tuple(sorted([r['sender_id'], r['receiver_id']]))
        chats.setdefault(key, []).append({
            'sender_name': f"{r['s_fn']} {r['s_ln']}",
            'receiver_name': f"{r['r_fn']} {r['r_ln']}",
            'type': r['type'],
            'content': f"/uploads/{r['content']}" if r['type'] in ('audio','video','image','file') else r['content'],
            'created_at': r['created_at']
        })
    return jsonify([{'a':k[0],'b':k[1],'messages':v} for k,v in chats.items()])

@app.route('/api/admin/all_group_chats')
def admin_all_group_chats():
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    groups = conn.execute("SELECT id, name, is_support FROM groups ORDER BY id").fetchall()
    out = []
    for g in groups:
        msgs = conn.execute("""
            SELECT gm.*, u.first_name, u.last_name
            FROM group_messages gm JOIN users u ON u.id=gm.sender_id
            WHERE gm.group_id=? ORDER BY gm.id ASC
        """, (g['id'],)).fetchall()
        out.append({'id': g['id'], 'name': g['name'], 'is_support': g['is_support'],
                    'messages': [{
                        'sender_name': f"{m['first_name']} {m['last_name']}",
                        'type': m['type'],
                        'content': f"/uploads/{m['content']}" if m['type'] in ('audio','video','image','file') else m['content'],
                        'created_at': m['created_at']
                    } for m in msgs]})
    conn.close()
    return jsonify(out)

@app.route('/api/admin/exams', methods=['GET','POST'])
def admin_exams():
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    if request.method == 'POST':
        d = request.json or {}
        title = (d.get('title') or '').strip()
        dur = int(d.get('duration_minutes') or 10)
        desc = (d.get('description') or '').strip()
        if not title:
            conn.close(); return jsonify(ok=False, msg='عنوان الزامی'), 400
        cur = conn.execute("INSERT INTO exams (title,description,duration_minutes) VALUES (?,?,?)",
                           (title, desc, dur))
        conn.commit(); eid = cur.lastrowid; conn.close()
        return jsonify(ok=True, id=eid)
    rows = conn.execute("""
        SELECT e.*,
          (SELECT COUNT(*) FROM questions WHERE exam_id=e.id) AS q_count,
          (SELECT COUNT(*) FROM exam_attempts WHERE exam_id=e.id AND finished_at IS NOT NULL) AS a_count
        FROM exams e ORDER BY e.id DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/exams/<int:eid>', methods=['DELETE','PUT'])
def admin_edit_exam(eid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    if request.method == 'DELETE':
        conn.execute("DELETE FROM answers WHERE attempt_id IN (SELECT id FROM exam_attempts WHERE exam_id=?)", (eid,))
        conn.execute("DELETE FROM exam_attempts WHERE exam_id=?", (eid,))
        conn.execute("DELETE FROM questions WHERE exam_id=?", (eid,))
        conn.execute("DELETE FROM exams WHERE id=?", (eid,))
    else:
        d = request.json or {}
        if 'is_active' in d:
            conn.execute("UPDATE exams SET is_active=? WHERE id=?", (1 if d['is_active'] else 0, eid))
        if 'title' in d:
            conn.execute("UPDATE exams SET title=? WHERE id=?", (d['title'], eid))
        if 'duration_minutes' in d:
            conn.execute("UPDATE exams SET duration_minutes=? WHERE id=?", (int(d['duration_minutes']), eid))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route('/api/admin/exams/<int:eid>/questions', methods=['GET','POST'])
def admin_questions(eid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    if request.method == 'POST':
        d = request.json or {}
        text = (d.get('text') or '').strip()
        if not text or d.get('correct') not in ('A','B','C','D'):
            conn.close(); return jsonify(ok=False, msg='سوال و پاسخ الزامی'), 400
        conn.execute("""INSERT INTO questions (exam_id,text,option_a,option_b,option_c,option_d,correct)
                        VALUES (?,?,?,?,?,?,?)""",
                     (eid, text, d.get('option_a',''), d.get('option_b',''),
                      d.get('option_c',''), d.get('option_d',''), d.get('correct')))
        conn.commit(); conn.close()
        return jsonify(ok=True)
    rows = conn.execute("SELECT * FROM questions WHERE exam_id=? ORDER BY id", (eid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/questions/<int:qid>', methods=['DELETE'])
def admin_del_question(qid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    conn.execute("DELETE FROM questions WHERE id=?", (qid,))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route('/api/admin/exams/<int:eid>/results')
def admin_exam_results(eid):
    if not is_admin(): return jsonify(ok=False), 403
    conn = db()
    rows = conn.execute("""
        SELECT a.id, a.score, a.total, a.started_at, a.finished_at,
               u.first_name, u.last_name, u.phone, u.avatar_color
        FROM exam_attempts a JOIN users u ON u.id=a.user_id
        WHERE a.exam_id=? AND a.finished_at IS NOT NULL
        ORDER BY a.score DESC, a.finished_at ASC
    """, (eid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# ═══════════ سرو فایل‌ها ═══════════
@app.route('/uploads/<path:fn>')
def route_uploads(fn):
    return send_from_directory(UPLOAD_DIR, fn)

@app.route('/sites/<path:fn>')
def route_sites(fn):
    return send_from_directory(SITE_DIR, fn)

@app.route('/view/<int:fid>')
def view_file(fid):
    conn = db()
    f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    conn.close()
    if not f: return "فایل پیدا نشد", 404
    f = dict(f)
    if f['site_folder']:
        folder = os.path.join(SITE_DIR, f['site_folder'])
        for candidate in ['index.html', 'Index.html', 'INDEX.HTML', 'main.html']:
            if os.path.exists(os.path.join(folder, candidate)):
                return redirect(f"/sites/{f['site_folder']}/{candidate}")
        for root, dirs, files in os.walk(folder):
            for name in files:
                if name.lower().endswith('.html'):
                    rel = os.path.relpath(os.path.join(root, name), folder).replace('\\', '/')
                    return redirect(f"/sites/{f['site_folder']}/{rel}")
        items = []
        for root, dirs, files in os.walk(folder):
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), folder).replace('\\', '/')
                items.append(f'<li><a href="/sites/{f["site_folder"]}/{rel}" target="_blank">{rel}</a></li>')
        return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><title>{f['title']}</title>
        <style>body{{font-family:Tahoma;padding:20px;background:#f4f4f5}}ul{{line-height:2}}a{{color:#6366f1}}</style></head>
        <body><h1>📦 {f['title']}</h1><ul>{''.join(items)}</ul></body></html>"""
    else:
        ext = f['file_type'].lower()
        path = os.path.join(UPLOAD_DIR, f['filename'])
        if ext in ('html', 'htm'):
            return send_file(path, mimetype='text/html')
        return send_file(path, as_attachment=True, download_name=f['original_name'])

@app.route('/api/file/<int:fid>/download')
def download_file(fid):
    conn = db()
    f = conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()
    conn.close()
    if not f: return "Not found", 404
    f = dict(f)
    if f['site_folder']:
        zip_path = os.path.join(UPLOAD_DIR, f['filename'])
        return send_file(zip_path, as_attachment=True, download_name=f['original_name'])
    return send_file(os.path.join(UPLOAD_DIR, f['filename']),
                     as_attachment=True, download_name=f['original_name'])

# ═══════════ SocketIO ═══════════
@socketio.on('connect')
def on_connect():
    uid = session.get('user_id')
    if uid:
        join_room(f"user_{uid}")
    conn = db()
    for g in conn.execute("SELECT id FROM groups WHERE is_public=1").fetchall():
        join_room(f"group_{g['id']}")
    conn.close()

# ============================================================
#                       CSS & HTML & JS
# ============================================================
CSS = r"""
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;600;700;800&display=swap');
:root{--bg-primary:#fff;--bg-secondary:#f4f4f5;--bg-tertiary:#e4e4e7;--text-primary:#18181b;--text-secondary:#71717a;--text-muted:#a1a1aa;--accent:#6366f1;--accent-hover:#4f46e5;--accent-soft:#eef2ff;--success:#10b981;--danger:#ef4444;--warning:#f59e0b;--border:#e4e4e7;--chat-bg:#efeae2;--msg-out:#d9fdd3;--msg-in:#fff;--radius:12px;--radius-lg:20px;}
[data-theme="dark"]{--bg-primary:#17212b;--bg-secondary:#0e1621;--bg-tertiary:#242f3d;--text-primary:#e4e4e7;--text-secondary:#a1a1aa;--text-muted:#71717a;--accent:#818cf8;--accent-hover:#6366f1;--accent-soft:#1e293b;--border:#242f3d;--chat-bg:#0e1621;--msg-out:#2b5278;--msg-in:#182533;}
*{box-sizing:border-box;margin:0;padding:0}html,body{height:100%}
body{font-family:'Vazirmatn',Tahoma,sans-serif;background:var(--bg-secondary);color:var(--text-primary);direction:rtl;overflow:hidden;transition:background .3s,color .3s}
button{font-family:inherit;cursor:pointer;border:none;background:none;color:inherit}
input,textarea,select{font-family:inherit;outline:none;border:none;background:none;color:inherit}
a{color:var(--accent);text-decoration:none}
.auth-page{display:flex;align-items:center;justify-content:center;min-height:100vh;background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 50%,#ec4899 100%);position:relative;overflow:hidden}
.auth-page::before{content:'';position:absolute;width:400px;height:400px;background:rgba(255,255,255,.1);border-radius:50%;top:-100px;right:-100px}
.auth-page::after{content:'';position:absolute;width:300px;height:300px;background:rgba(255,255,255,.08);border-radius:50%;bottom:-80px;left:-80px}
.auth-card{background:rgba(255,255,255,.98);backdrop-filter:blur(20px);padding:40px 36px;border-radius:24px;box-shadow:0 20px 60px rgba(0,0,0,.25);width:100%;max-width:400px;position:relative;z-index:2}
.auth-logo{text-align:center;font-size:32px;margin-bottom:8px}
.auth-title{text-align:center;font-size:22px;font-weight:700;color:#18181b;margin-bottom:4px}
.auth-subtitle{text-align:center;font-size:13px;color:#71717a;margin-bottom:28px}
.auth-field{margin-bottom:14px}
.auth-field input{width:100%;padding:14px 16px;border-radius:12px;background:#f4f4f5;border:2px solid transparent;font-size:14px;color:#18181b;transition:all .2s}
.auth-field input:focus{background:#fff;border-color:#6366f1;box-shadow:0 0 0 4px rgba(99,102,241,.1)}
.auth-btn{width:100%;padding:14px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-size:15px;font-weight:600;border-radius:12px;margin-top:8px;transition:transform .15s,box-shadow .15s}
.auth-btn:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(99,102,241,.4)}
.auth-btn:disabled{opacity:.6;cursor:not-allowed}
.auth-msg{text-align:center;color:#ef4444;font-size:13px;margin-top:12px;min-height:18px}
.auth-link{display:block;text-align:center;font-size:13px;color:#71717a;margin-top:20px}
.app-container{display:grid;grid-template-columns:400px 1fr;height:100vh;background:var(--bg-secondary)}
.sidebar{background:var(--bg-primary);border-left:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.sidebar-header{padding:16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border)}
.sidebar-logo{display:flex;align-items:center;gap:10px;font-weight:700;font-size:17px}
.sidebar-logo .logo-icon{width:36px;height:36px;background:linear-gradient(135deg,#6366f1,#8b5cf6);border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:18px}
.sidebar-actions{display:flex;gap:4px}
.icon-btn{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;color:var(--text-secondary);transition:all .2s}
.icon-btn:hover{background:var(--bg-tertiary);color:var(--text-primary)}
.sidebar-search{padding:12px 16px;border-bottom:1px solid var(--border)}
.search-box{display:flex;align-items:center;gap:8px;background:var(--bg-secondary);border-radius:20px;padding:8px 14px;color:var(--text-secondary);font-size:13px}
.search-box input{flex:1;font-size:13px}
.sidebar-tabs{display:flex;border-bottom:1px solid var(--border);padding:0 6px;overflow-x:auto}
.sidebar-tab{flex:0 0 auto;padding:12px 10px;text-align:center;font-size:12px;font-weight:500;color:var(--text-secondary);border-bottom:2px solid transparent;transition:all .2s;white-space:nowrap}
.sidebar-tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.sidebar-list{flex:1;overflow-y:auto;padding:4px 0}
.sidebar-list::-webkit-scrollbar{width:6px}.sidebar-list::-webkit-scrollbar-thumb{background:var(--bg-tertiary);border-radius:3px}
.chat-item{display:flex;align-items:center;gap:12px;padding:10px 16px;cursor:pointer;transition:background .15s;position:relative}
.chat-item:hover{background:var(--bg-secondary)}
.chat-item.active{background:var(--accent-soft)}
.chat-item.active::before{content:'';position:absolute;right:0;top:8px;bottom:8px;width:3px;background:var(--accent);border-radius:2px}
.avatar{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:18px;flex-shrink:0;position:relative}
.avatar.small{width:36px;height:36px;font-size:14px}
.avatar .status-dot{position:absolute;bottom:2px;left:2px;width:12px;height:12px;border-radius:50%;background:var(--success);border:2px solid var(--bg-primary)}
.avatar .status-dot.offline{background:var(--text-muted)}
.chat-info{flex:1;min-width:0}
.chat-name-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:2px}
.chat-name{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chat-preview{font-size:12px;color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:flex;align-items:center;gap:6px}
.unread-badge{background:var(--accent);color:#fff;font-size:11px;font-weight:600;padding:2px 7px;border-radius:10px;margin-right:auto}
.empty-list{padding:40px 20px;text-align:center;color:var(--text-muted);font-size:13px}
.main-area{display:flex;flex-direction:column;background:var(--chat-bg);overflow:hidden;position:relative}
.empty-state{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--text-secondary);gap:12px;padding:40px;text-align:center}
.empty-state .icon{width:80px;height:80px;background:var(--bg-tertiary);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:36px;opacity:.5}
.empty-state h3{font-size:16px;font-weight:600}.empty-state p{font-size:13px}
.chat-header{background:var(--bg-primary);padding:10px 20px;display:flex;align-items:center;gap:14px;border-bottom:1px solid var(--border);z-index:5}
.chat-header-info{flex:1}
.chat-header-name{font-weight:600;font-size:15px}
.chat-header-status{font-size:12px;color:var(--success)}
.chat-header-status.offline{color:var(--text-muted)}
.messages-area{flex:1;overflow-y:auto;padding:20px 40px;display:flex;flex-direction:column;gap:2px;background:var(--chat-bg)}
.messages-area::-webkit-scrollbar{width:8px}.messages-area::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px}
.msg-row{display:flex;margin-bottom:4px;animation:msgIn .25s ease-out;align-items:flex-end;gap:8px}
@keyframes msgIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.msg-row.mine{justify-content:flex-start;flex-direction:row-reverse}
.msg-row.other{justify-content:flex-end}
.msg-bubble{max-width:65%;padding:8px 12px 6px;border-radius:14px;word-wrap:break-word;box-shadow:0 1px 1px rgba(0,0,0,.06)}
.msg-row.mine .msg-bubble{background:var(--msg-out);border-bottom-right-radius:4px}
.msg-row.other .msg-bubble{background:var(--msg-in);border-bottom-left-radius:4px}
.msg-author{font-size:11px;font-weight:600;color:var(--accent);margin-bottom:2px}
.msg-text{font-size:14px;line-height:1.5;white-space:pre-wrap}
.msg-meta{font-size:10px;color:var(--text-muted);margin-top:2px;display:flex;align-items:center;gap:4px;justify-content:flex-end}
.msg-check{color:var(--success);font-size:12px}
.msg-bubble audio{width:260px;height:40px;margin:4px 0}
.msg-bubble video{max-width:300px;border-radius:10px;margin:4px 0}
.msg-bubble img.msg-image{max-width:280px;border-radius:10px;margin:4px 0;cursor:pointer}
.msg-file{display:flex;align-items:center;gap:10px;padding:10px;background:rgba(255,255,255,.6);border-radius:10px;margin:4px 0;cursor:pointer}
[data-theme="dark"] .msg-file{background:rgba(0,0,0,.2)}
.msg-file .fi{font-size:28px}
.msg-file .fname{font-size:12px;word-break:break-all}
.typing-indicator{display:flex;align-items:center;gap:6px;padding:8px 16px;font-size:12px;color:var(--text-secondary)}
.typing-dots{display:flex;gap:3px}
.typing-dots span{width:6px;height:6px;border-radius:50%;background:var(--text-secondary);animation:typing 1.4s infinite}
.typing-dots span:nth-child(2){animation-delay:.2s}.typing-dots span:nth-child(3){animation-delay:.4s}
@keyframes typing{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-4px);opacity:1}}
.chat-input-area{background:var(--bg-primary);padding:10px 20px;display:flex;align-items:center;gap:8px;border-top:1px solid var(--border)}
.chat-input{flex:1;background:var(--bg-secondary);border-radius:22px;padding:10px 18px;font-size:14px;min-height:42px;max-height:120px;resize:none;line-height:1.4}
.chat-input::placeholder{color:var(--text-muted)}
.send-btn{width:42px;height:42px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;font-size:18px;display:flex;align-items:center;justify-content:center;transition:transform .15s;flex-shrink:0}
.send-btn:hover{transform:scale(1.05)}.send-btn:active{transform:scale(.95)}
.rec-btn{background:var(--danger)}
.rec-btn.recording{animation:pulse 1s infinite;background:#dc2626}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,.7)}50%{box-shadow:0 0 0 12px rgba(239,68,68,0)}}
.rec-status{position:absolute;bottom:70px;left:50%;transform:translateX(-50%);background:var(--danger);color:#fff;padding:8px 16px;border-radius:20px;font-size:13px;display:none;z-index:20}
.rec-status.show{display:block}
.page-view{height:100%;overflow-y:auto;background:var(--bg-secondary);padding:24px}
.page-card{max-width:900px;margin:0 auto;background:var(--bg-primary);padding:24px;border-radius:20px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.05)}
.page-card h2{font-size:20px;margin-bottom:16px}
.files-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin-top:16px}
.file-card{background:var(--bg-primary);border:1px solid var(--border);border-radius:14px;padding:16px;cursor:pointer;transition:all .2s;text-align:center}
.file-card:hover{transform:translateY(-3px);box-shadow:0 8px 20px rgba(99,102,241,.15);border-color:var(--accent)}
.file-icon{font-size:40px;margin-bottom:8px}
.file-title{font-size:13px;font-weight:600;word-break:break-word}
.file-meta{font-size:11px;color:var(--text-muted);margin-top:4px}
.calc-container{max-width:400px;margin:0 auto}
.calc-display{background:var(--bg-primary);padding:20px;border-radius:14px;text-align:left;font-size:28px;font-weight:700;margin-bottom:12px;min-height:80px;word-wrap:break-word;border:1px solid var(--border);direction:ltr;font-family:monospace}
.calc-history{font-size:13px;color:var(--text-muted);direction:ltr;text-align:left;min-height:20px}
.calc-buttons{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.calc-btn{background:var(--bg-primary);color:var(--text-primary);padding:18px;border-radius:12px;font-size:18px;font-weight:600;border:1px solid var(--border);transition:all .15s}
.calc-btn:hover{background:var(--bg-secondary);transform:scale(1.02)}
.calc-btn.op{background:var(--accent-soft);color:var(--accent)}
.calc-btn.eq{background:var(--accent);color:#fff;grid-column:span 2}
.calc-btn.clr{background:var(--danger);color:#fff}
.exam-timer{position:sticky;top:0;background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff;padding:14px;border-radius:var(--radius);text-align:center;font-weight:700;font-size:18px;margin-bottom:16px;z-index:10}
.question-block{background:var(--bg-primary);padding:20px;border-radius:var(--radius-lg);margin-bottom:14px}
.question-text{font-size:15px;font-weight:600;margin-bottom:14px;line-height:1.6}
.option-label{display:flex;align-items:center;padding:12px 16px;border-radius:10px;margin-bottom:8px;cursor:pointer;background:var(--bg-secondary);border:2px solid transparent;transition:all .15s}
.option-label:hover{background:var(--accent-soft)}
.option-label input{display:none}
.option-label.selected{background:var(--accent-soft);border-color:var(--accent)}
.option-key{width:28px;height:28px;border-radius:50%;background:var(--bg-tertiary);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;margin-left:12px;flex-shrink:0}
.option-label.selected .option-key{background:var(--accent);color:#fff}
.option-text{font-size:14px;flex:1}
.lb-row{display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:10px;background:var(--bg-secondary);margin-bottom:8px}
.lb-row.gold{background:linear-gradient(90deg,#fef3c7,#fde68a)}
.lb-row.silver{background:linear-gradient(90deg,#e5e7eb,#d1d5db)}
.lb-row.bronze{background:linear-gradient(90deg,#fed7aa,#fdba74)}
.admin-container{display:grid;grid-template-columns:260px 1fr;height:100vh;background:var(--bg-secondary)}
.admin-sidebar{background:var(--bg-primary);border-left:1px solid var(--border);padding:20px 12px;overflow-y:auto;position:relative}
.admin-nav-item{display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:10px;font-size:14px;font-weight:500;color:var(--text-secondary);margin-bottom:4px;cursor:pointer;transition:all .15s}
.admin-nav-item:hover{background:var(--bg-secondary);color:var(--text-primary)}
.admin-nav-item.active{background:var(--accent-soft);color:var(--accent)}
.admin-main{overflow-y:auto;padding:24px}
.admin-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
.admin-header h1{font-size:24px;font-weight:700}
.admin-card{background:var(--bg-primary);padding:20px;border-radius:var(--radius-lg);margin-bottom:16px}
.form-input{width:100%;padding:12px 16px;border-radius:10px;background:var(--bg-secondary);font-size:14px;margin-bottom:10px;border:2px solid transparent;transition:border .2s}
.form-input:focus{border-color:var(--accent);background:var(--bg-primary)}
textarea.form-input{min-height:80px;resize:vertical}
.btn{padding:12px 20px;border-radius:10px;font-size:14px;font-weight:600;transition:all .15s}
.btn-primary{background:var(--accent);color:#fff}.btn-primary:hover{background:var(--accent-hover)}
.btn-danger{background:var(--danger);color:#fff}
.btn-success{background:var(--success);color:#fff}
.btn-warning{background:var(--warning);color:#fff}
.btn-sm{padding:6px 12px;font-size:12px}
.user-item{display:flex;align-items:center;gap:12px;padding:12px;border-radius:10px;background:var(--bg-secondary);margin-bottom:8px}
.user-info{flex:1}
.user-name{font-weight:600;font-size:14px}
.user-phone{font-size:12px;color:var(--text-secondary)}
.user-pass{font-size:11px;color:var(--danger);font-family:monospace;margin-top:2px}
.status-badge{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;background:var(--bg-tertiary);color:var(--text-secondary)}
.status-badge.online{background:rgba(16,185,129,.15);color:var(--success)}
.status-badge.support{background:rgba(245,179,53,.2);color:#9a5b00}
.ads-banner-container{background:var(--bg-primary);border-bottom:1px solid var(--border);padding:10px 16px;position:relative;overflow:hidden}
.ads-banner-inner{position:relative;border-radius:14px;overflow:hidden;cursor:pointer;transition:transform .2s}
.ads-banner-inner:hover{transform:scale(1.005)}
.ads-slide{display:none;position:relative}
.ads-slide.active{display:block;animation:adFade .5s}
@keyframes adFade{from{opacity:0}to{opacity:1}}
.ads-slide img{width:100%;max-height:180px;object-fit:cover;display:block;border-radius:14px}
.ads-slide-info{position:absolute;bottom:0;left:0;right:0;background:linear-gradient(transparent,rgba(0,0,0,.75));color:#fff;padding:20px 16px 12px}
.ads-slide-title{font-weight:700;font-size:15px;margin-bottom:2px}
.ads-slide-desc{font-size:12px;opacity:.9}
.ads-dots{position:absolute;bottom:8px;left:50%;transform:translateX(-50%);display:flex;gap:6px;z-index:2}
.ads-dot{width:8px;height:8px;border-radius:50%;background:rgba(255,255,255,.5);cursor:pointer;transition:all .2s}
.ads-dot.active{background:#fff;width:20px;border-radius:4px}
.ads-close{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.4);color:#fff;width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;cursor:pointer;z-index:2}
.ads-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;margin-top:12px}
.ad-card{background:var(--bg-secondary);border-radius:14px;overflow:hidden;transition:all .2s}
.ad-card:hover{transform:translateY(-3px);box-shadow:0 8px 20px rgba(99,102,241,.15)}
.ad-card img{width:100%;height:160px;object-fit:cover;display:block}
.ad-card-body{padding:12px}
.ad-card-title{font-weight:600;font-size:14px;margin-bottom:4px}
.ad-card-desc{font-size:12px;color:var(--text-secondary);margin-bottom:6px}
.ad-card-link{font-size:12px;color:var(--accent)}
.theme-toggle{position:fixed;bottom:20px;left:20px;width:50px;height:50px;border-radius:50%;background:var(--bg-primary);box-shadow:0 10px 30px rgba(0,0,0,.12);display:flex;align-items:center;justify-content:center;font-size:22px;cursor:pointer;z-index:100;transition:transform .2s}
.theme-toggle:hover{transform:scale(1.1) rotate(15deg)}
.hidden{display:none!important}
.fade-in{animation:fadeIn .3s ease-out}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.toast{position:fixed;bottom:90px;left:50%;transform:translateX(-50%);background:var(--text-primary);color:var(--bg-primary);padding:12px 24px;border-radius:24px;font-size:13px;font-weight:500;z-index:200;animation:toastIn .3s ease-out}
@keyframes toastIn{from{opacity:0;transform:translate(-50%,20px)}to{opacity:1;transform:translate(-50%,0)}}
@media (max-width:768px){
  .app-container{grid-template-columns:1fr}
  .sidebar{display:none}
  .sidebar.mobile-show{display:flex;position:absolute;inset:0;z-index:50}
  .messages-area{padding:12px}
  .msg-bubble{max-width:85%}
  .admin-container{grid-template-columns:1fr}
  .admin-sidebar{display:none}
  .back-btn{display:flex!important}
  .page-view{padding:12px}
  .ads-slide img{max-height:120px}
  .ads-grid{grid-template-columns:1fr 1fr;gap:8px}
  .ad-card img{height:100px}
}
.back-btn{display:none;width:36px;height:36px;align-items:center;justify-content:center;font-size:20px;border-radius:50%;cursor:pointer}
.back-btn:hover{background:var(--bg-tertiary)}
"""

# ═══════════ HTML — ورود ═══════════
LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>ورود — __SITE__</title><style>__CSS__</style></head>
<body>
<div class="auth-page"><div class="auth-card">
<div class="auth-logo">📚</div>
<h1 class="auth-title">__SITE__</h1>
<p class="auth-subtitle">پیام‌رسان آموزشی هوشمند</p>
<div class="auth-field"><input id="fn" placeholder="نام"></div>
<div class="auth-field"><input id="ln" placeholder="نام خانوادگی"></div>
<div class="auth-field"><input id="ph" placeholder="شماره موبایل" inputmode="numeric"></div>
<div class="auth-field"><input id="pw" type="password" placeholder="رمز عبور"></div>
<button class="auth-btn" onclick="doLogin()">ورود به سایت</button>
<p class="auth-msg" id="msg"></p>
<a href="/admin" class="auth-link">🔐 ورود ادمین</a>
</div></div>
<script>
async function doLogin(){
  const btn=document.querySelector('.auth-btn');
  const m=document.getElementById('msg');
  const body={first_name:fn.value.trim(),last_name:ln.value.trim(),phone:ph.value.trim(),password:pw.value.trim()};
  if(!body.first_name||!body.last_name||!body.phone||!body.password){m.textContent='همه فیلدها را پر کنید';return;}
  btn.disabled=true;btn.textContent='در حال ورود...';
  try{
    const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const txt=await r.text();
    let d;
    try{d=JSON.parse(txt);}catch(e){m.textContent='خطای سرور: '+txt.slice(0,200);btn.disabled=false;btn.textContent='ورود به سایت';return;}
    if(d.ok)location.href='/';
    else{m.textContent=d.msg||'خطا';btn.disabled=false;btn.textContent='ورود به سایت';}
  }catch(e){m.textContent='خطای شبکه: '+e.message;btn.disabled=false;btn.textContent='ورود به سایت';}
}
[fn,ln,ph,pw].forEach(i=>i.addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();}));
</script>
</body></html>"""

# ═══════════ HTML — اپ ═══════════
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>__SITE__</title><style>__CSS__</style></head>
<body>
<div class="app-container">
<aside class="sidebar" id="sidebar">
<div class="sidebar-header">
<div class="sidebar-logo"><div class="logo-icon">📚</div><span>__SITE__</span></div>
<div class="sidebar-actions">
<button class="icon-btn" onclick="showAdsPage()" title="تبلیغات">📢</button>
<button class="icon-btn" onclick="doLogout()" title="خروج">🚪</button>
</div>
</div>
<div class="sidebar-search"><div class="search-box"><span>🔍</span><input id="searchInput" placeholder="جستجو..." oninput="renderSidebar()"></div></div>
<div class="sidebar-tabs">
<button class="sidebar-tab active" onclick="switchSidebarTab('chats',this)">💬 خصوصی</button>
<button class="sidebar-tab" onclick="switchSidebarTab('groups',this)">👥 گروه‌ها</button>
<button class="sidebar-tab" onclick="switchSidebarTab('classes',this)">🎓 کلاس</button>
<button class="sidebar-tab" onclick="switchSidebarTab('videos',this)">🎬 ویدیو</button>
<button class="sidebar-tab" onclick="switchSidebarTab('exams',this)">📝 آزمون</button>
<button class="sidebar-tab" onclick="switchSidebarTab('files',this)">📁 فایل‌ها</button>
<button class="sidebar-tab" onclick="switchSidebarTab('calc',this)">🧮 محاسبه</button>
</div>
<div class="sidebar-list" id="sidebarList"></div>
</aside>
<main class="main-area" id="mainArea">
<div id="adsBanner" class="ads-banner-container hidden"></div>
<div class="empty-state" id="emptyState">
<div class="icon">💬</div>
<h3>به __SITE__ خوش آمدی</h3>
<p>یک گزینه از سایدبار انتخاب کن</p>
</div>
<div id="chatView" class="hidden" style="display:flex;flex-direction:column;height:100%">
<div class="chat-header">
<button class="back-btn" onclick="backToSidebar()">←</button>
<div class="avatar small" id="chatAvatar"></div>
<div class="chat-header-info">
<div class="chat-header-name" id="chatName"></div>
<div class="chat-header-status" id="chatStatus"></div>
</div>
</div>
<div class="messages-area" id="messagesArea"></div>
<div class="typing-indicator hidden" id="typingIndicator">
<div class="typing-dots"><span></span><span></span><span></span></div>
<span>در حال نوشتن...</span>
</div>
<div class="chat-input-area">
<button class="send-btn" onclick="document.getElementById('fileInput').click()" style="background:#8b5cf6" title="فایل">📎</button>
<input type="file" id="fileInput" accept="image/*,video/*,audio/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.txt" style="display:none" onchange="sendMedia(this)">
<button class="send-btn rec-btn" id="recBtn" onclick="toggleRecord()" title="صدا">🎤</button>
<textarea class="chat-input" id="msgInput" placeholder="پیام..." rows="1"></textarea>
<button class="send-btn" onclick="sendText()">➤</button>
</div>
<div class="rec-status" id="recStatus">🔴 در حال ضبط...</div>
</div>
<div id="pageView" class="hidden page-view"><div id="pageContent"></div></div>
</main>
</div>
<button class="theme-toggle" onclick="toggleTheme()">🌙</button>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<script>__JS__</script>
</body></html>"""

# ═══════════ HTML — ادمین ═══════════
ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>پنل ادمین — __SITE__</title><style>__CSS__</style></head>
<body>
<div class="auth-page" id="adminLogin">
<div class="auth-card">
<div class="auth-logo">🔐</div>
<h1 class="auth-title">__SITE__</h1>
<p class="auth-subtitle">پنل مدیریت</p>
<div class="auth-field"><input id="aUser" placeholder="نام کاربری"></div>
<div class="auth-field"><input id="aPass" type="password" placeholder="رمز"></div>
<button class="auth-btn" onclick="adminLogin()">ورود</button>
<p class="auth-msg" id="aMsg"></p>
<a href="/login" class="auth-link">بازگشت به سایت</a>
</div></div>
<div class="admin-container hidden" id="adminPanel">
<aside class="admin-sidebar">
<div class="sidebar-logo" style="margin-bottom:24px;padding:0 8px"><div class="logo-icon">📚</div><span>__SITE__</span></div>
<div class="admin-nav-item active" onclick="adminTab('dashboard',this)"><span>📊</span> داشبورد</div>
<div class="admin-nav-item" onclick="adminTab('students',this)"><span>👤</span> مدیریت دانش‌آموزان</div>
<div class="admin-nav-item" onclick="adminTab('classes',this)"><span>🎓</span> کلاس‌ها</div>
<div class="admin-nav-item" onclick="adminTab('videos',this)"><span>🎬</span> ویدیوها</div>
<div class="admin-nav-item" onclick="adminTab('exams',this)"><span>📝</span> آزمون‌ها</div>
<div class="admin-nav-item" onclick="adminTab('ads',this)"><span>📢</span> تبلیغات</div>
<div class="admin-nav-item" onclick="adminTab('users',this)"><span>👥</span> کاربران</div>
<div class="admin-nav-item" onclick="adminTab('groups',this)"><span>👥</span> گروه‌ها</div>
<div class="admin-nav-item" onclick="adminTab('chats',this)"><span>💬</span> چت‌های خصوصی</div>
<div class="admin-nav-item" onclick="adminTab('group_chats',this)"><span>👥</span> چت گروهی</div>
<div class="admin-nav-item" onclick="adminTab('files',this)"><span>📁</span> فایل‌ها</div>
<div style="position:absolute;bottom:20px;left:12px;right:12px"><button class="btn btn-danger btn-sm" style="width:100%" onclick="adminLogout()">خروج</button></div>
</aside>
<main class="admin-main">
<div class="admin-header"><h1 id="adminTitle">داشبورد</h1></div>
<div id="adminContent"></div>
</main>
</div>
<button class="theme-toggle" onclick="toggleTheme()">🌙</button>
<script>__JS__</script>
</body></html>"""

# ═══════════ JS — اپ ═══════════
APP_JS = r"""
const socket = io();
let me = null;
let currentChatWith = null;
let currentGroupId = null;
let usersCache = [];
let groupsCache = [];
let adsCache = [];
let adsIndex = 0;
let adsTimer = null;
let mediaRecorder = null;
let audioChunks = [];
let currentSidebarTab = 'chats';
let sidebarData = { classes: [], videos: [], exams: [], files: [] };
let examTimer = null;
let currentAttempt = null;

function applyTheme(){
  const t = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', t);
  const btn = document.querySelector('.theme-toggle');
  if(btn) btn.textContent = t === 'dark' ? '☀️' : '🌙';
}
function toggleTheme(){
  const t = localStorage.getItem('theme') === 'dark' ? 'light' : 'dark';
  localStorage.setItem('theme', t);
  applyTheme();
}
applyTheme();

function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function initials(fn,ln){return ((fn||' ')[0]+(ln||' ')[0]).trim()||'?';}
function fmtTime(iso){if(!iso)return '';return new Date(iso).toLocaleTimeString('fa-IR',{hour:'2-digit',minute:'2-digit'});}
function toast(msg){const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),3000);}
function fileIcon(name){
  const ext = (name||'').split('.').pop().toLowerCase();
  const map = {pdf:'📄',doc:'📝',docx:'📝',xls:'📊',xlsx:'📊',ppt:'📽️',pptx:'📽️',
               zip:'📦',rar:'📦',txt:'📃',html:'🌐',htm:'🌐',
               jpg:'🖼️',jpeg:'🖼️',png:'🖼️',gif:'🖼️',webp:'🖼️',svg:'🖼️',
               mp3:'🎵',wav:'🎵',ogg:'🎵',m4a:'🎵',
               mp4:'🎬',webm:'🎬',mov:'🎬',avi:'🎬'};
  return map[ext] || '📎';
}
function avatarHTML(name,color,size='',online=null){
  const parts=(name||' ').split(' ');
  const ini=((parts[0]||' ')[0]+(parts[1]||' ')[0]).trim();
  const dot=online===null?'':`<span class="status-dot ${online?'':'offline'}"></span>`;
  return `<div class="avatar ${size}" style="background:${color||'#6366f1'}">${ini}${dot}</div>`;
}

async function loadAds(){
  try {
    const r = await fetch('/api/ads');
    adsCache = await r.json();
    renderAdsBanner();
  } catch(e) { console.log('ads error', e); }
}
function renderAdsBanner(){
  const banner = document.getElementById('adsBanner');
  if(!adsCache.length || sessionStorage.getItem('adsHidden') === '1'){
    banner.classList.add('hidden');
    return;
  }
  banner.classList.remove('hidden');
  adsIndex = 0;
  banner.innerHTML = `
    <div class="ads-banner-inner">
      <button class="ads-close" onclick="hideAds()">✕</button>
      <div id="adsSlides"></div>
      <div class="ads-dots" id="adsDots"></div>
    </div>`;
  renderAdsSlides();
  clearInterval(adsTimer);
  if(adsCache.length > 1){
    adsTimer = setInterval(() => {
      adsIndex = (adsIndex + 1) % adsCache.length;
      renderAdsSlides();
    }, 5000);
  }
}
function renderAdsSlides(){
  const slides = document.getElementById('adsSlides');
  const dots = document.getElementById('adsDots');
  if(!slides || !dots) return;
  slides.innerHTML = adsCache.map((a, i) => `
    <div class="ads-slide ${i === adsIndex ? 'active' : ''}">
      <img src="/ads/${esc(a.image_filename)}" alt="${esc(a.title)}" onclick="openAd('${esc(a.link||'')}')">
      ${(a.title || a.description) ? `<div class="ads-slide-info" onclick="openAd('${esc(a.link||'')}')">
        ${a.title?`<div class="ads-slide-title">${esc(a.title)}</div>`:''}
        ${a.description?`<div class="ads-slide-desc">${esc(a.description)}</div>`:''}
      </div>`:''}
    </div>`).join('');
  dots.innerHTML = adsCache.map((a, i) => `<div class="ads-dot ${i === adsIndex ? 'active' : ''}" onclick="setAdSlide(${i})"></div>`).join('');
}
window.setAdSlide = (i) => { adsIndex = i; renderAdsSlides(); };
window.openAd = (link) => { if(link) window.open(link, '_blank'); };
window.hideAds = () => {
  sessionStorage.setItem('adsHidden', '1');
  document.getElementById('adsBanner').classList.add('hidden');
  clearInterval(adsTimer);
};
window.showAdsPage = () => {
  if(!adsCache.length){ toast('هنوز تبلیغی نیست'); return; }
  showPage(`<div class="page-card fade-in">
    <h2>📢 تبلیغات</h2>
    <div class="ads-grid">
      ${adsCache.map(a=>`<div class="ad-card">
        <img src="/ads/${esc(a.image_filename)}" alt="${esc(a.title)}">
        <div class="ad-card-body">
          ${a.title?`<div class="ad-card-title">${esc(a.title)}</div>`:''}
          ${a.description?`<div class="ad-card-desc">${esc(a.description)}</div>`:''}
          ${a.link?`<a href="${esc(a.link)}" target="_blank" class="ad-card-link">🔗 مشاهده</a>`:''}
        </div>
      </div>`).join('')}
    </div>
  </div>`);
};

async function init(){
  const r = await fetch('/api/me');
  if(!r.ok){location.href='/login';return;}
  me = await r.json();
  await loadUsers();
  await loadStatic();
  await loadGroups();
  await loadAds();
  renderSidebar();
  socket.on('new_message', onMessage);
  socket.on('new_group_message', onGroupMessage);
  socket.on('typing', d => {
    if(currentChatWith && d.from === currentChatWith){
      const t = document.getElementById('typingIndicator');
      t.classList.remove('hidden');
      clearTimeout(t._to);
      t._to = setTimeout(()=>t.classList.add('hidden'), 2000);
    }
  });
}

async function loadUsers(){
  const r = await fetch('/api/users');
  usersCache = await r.json();
}
async function loadGroups(){
  const r = await fetch('/api/groups');
  groupsCache = await r.json();
}
async function loadStatic(){
  const [c,v,e,f] = await Promise.all([
    fetch('/api/classes').then(r=>r.json()),
    fetch('/api/videos').then(r=>r.json()),
    fetch('/api/exams').then(r=>r.json()),
    fetch('/api/files').then(r=>r.json())
  ]);
  sidebarData = {classes:c, videos:v, exams:e, files:f};
}

window.doLogout = async () => {await fetch('/api/logout',{method:'POST'});location.href='/login';};

window.switchSidebarTab = (tab, el) => {
  currentSidebarTab = tab;
  document.querySelectorAll('.sidebar-tab').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  renderSidebar();
};

window.renderSidebar = () => {
  const box = document.getElementById('sidebarList');
  const q = (document.getElementById('searchInput').value||'').trim();
  let html = '';
  if(currentSidebarTab === 'chats'){
    const list = usersCache.filter(u=>!q || (u.first_name+' '+u.last_name).includes(q) || u.phone.includes(q));
    if(!list.length) html = '<div class="empty-list">مخاطبی نیست</div>';
    list.forEach(u=>{
      const active = currentChatWith === u.id && !currentGroupId ? 'active' : '';
      const preview = u.unread > 0 ? `<span class="unread-badge">${u.unread}</span>` : '';
      html += `<div class="chat-item ${active}" onclick="openChat(${u.id})">
        ${avatarHTML(u.first_name+' '+u.last_name, u.avatar_color, '', u.is_online)}
        <div class="chat-info">
          <div class="chat-name-row"><span class="chat-name">${esc(u.first_name)} ${esc(u.last_name)}</span></div>
          <div class="chat-preview"><span>${u.is_online?'🟢 آنلاین':'⚪ آفلاین'}</span>${preview}</div>
        </div></div>`;
    });
  } else if(currentSidebarTab === 'groups'){
    if(!groupsCache.length) html = '<div class="empty-list">گروهی نیست</div>';
    groupsCache.filter(g=>!q||g.name.includes(q)).forEach(g=>{
      const active = currentGroupId === g.id ? 'active' : '';
      const isSup = g.is_support;
      const icon = isSup ? '🛟' : '👥';
      const badge = g.unread > 0 ? `<span class="unread-badge">${g.unread}</span>` : '';
      const preview = g.last_msg ? (g.last_msg.type==='text'?esc(g.last_msg.content):'📎 فایل') : 'بدون پیام';
      html += `<div class="chat-item ${active}" onclick="openGroup(${g.id})">
        <div class="avatar" style="background:linear-gradient(135deg,${isSup?'#f59e0b,#d97706':'#10b981,#059669'})">${icon}</div>
        <div class="chat-info">
          <div class="chat-name-row">
            <span class="chat-name">${esc(g.name)}</span>
            ${isSup?'<span class="status-badge support">پشتیبانی</span>':''}
          </div>
          <div class="chat-preview"><span>${esc(preview).slice(0,30)}</span>${badge}</div>
        </div></div>`;
    });
  } else if(currentSidebarTab === 'classes'){
    if(!sidebarData.classes.length) html = '<div class="empty-list">کلاسی نیست</div>';
    sidebarData.classes.filter(c=>!q||c.name.includes(q)).forEach(c=>{
      html += `<div class="chat-item" onclick="openClass(${c.id})">
        <div class="avatar" style="background:linear-gradient(135deg,#6366f1,#8b5cf6)">🎓</div>
        <div class="chat-info"><div class="chat-name">${esc(c.name)}</div>
        <div class="chat-preview">${esc(c.teacher||'کلاس مجازی')}</div></div></div>`;
    });
  } else if(currentSidebarTab === 'videos'){
    if(!sidebarData.videos.length) html = '<div class="empty-list">ویدیویی نیست</div>';
    sidebarData.videos.forEach(v=>{
      html += `<div class="chat-item" onclick="openVideo('${esc(v.url)}','${esc(v.title).replace(/'/g,'')}')">
        <div class="avatar" style="background:linear-gradient(135deg,#ec4899,#f43f5e)">🎬</div>
        <div class="chat-info"><div class="chat-name">${esc(v.title)}</div>
        <div class="chat-preview">تماشا</div></div></div>`;
    });
  } else if(currentSidebarTab === 'exams'){
    if(!sidebarData.exams.length) html = '<div class="empty-list">آزمونی نیست</div>';
    sidebarData.exams.forEach(e=>{
      const done = e.my_attempt;
      html += `<div class="chat-item" onclick="openExam(${e.id})">
        <div class="avatar" style="background:linear-gradient(135deg,${done?'#10b981,#059669':'#f59e0b,#d97706'})">📝</div>
        <div class="chat-info"><div class="chat-name">${esc(e.title)}</div>
        <div class="chat-preview">${done?`✅ نمره: ${done.score}/${done.total}`:`⏱️ ${e.duration_minutes} دقیقه • ${e.q_count} سوال`}</div></div></div>`;
    });
  } else if(currentSidebarTab === 'files'){
    if(!sidebarData.files.length) html = '<div class="empty-list">فایلی آپلود نشده</div>';
    sidebarData.files.filter(f=>!q||(f.title||'').includes(q)).forEach(f=>{
      html += `<div class="chat-item" onclick="openFile(${f.id})">
        <div class="avatar" style="background:#6366f1;font-size:22px">${fileIcon(f.original_name)}</div>
        <div class="chat-info"><div class="chat-name">${esc(f.title)}</div>
        <div class="chat-preview">${f.file_type.toUpperCase()} • ${(f.size/1024).toFixed(0)} KB</div></div></div>`;
    });
  } else if(currentSidebarTab === 'calc'){
    html = `<div class="chat-item" onclick="openCalc()">
      <div class="avatar" style="background:linear-gradient(135deg,#10b981,#059669)">🧮</div>
      <div class="chat-info"><div class="chat-name">ماشین‌حساب علمی</div>
      <div class="chat-preview">محاسبات پیشرفته</div></div></div>`;
  }
  box.innerHTML = html;
};

window.openChat = async (uid) => {
  currentChatWith = uid;
  currentGroupId = null;
  const u = usersCache.find(x=>x.id === uid);
  if(!u) return;
  document.getElementById('emptyState').classList.add('hidden');
  document.getElementById('pageView').classList.add('hidden');
  const cv = document.getElementById('chatView');
  cv.classList.remove('hidden'); cv.style.display = 'flex';
  const av = document.getElementById('chatAvatar');
  av.style.background = u.avatar_color;
  av.innerHTML = initials(u.first_name, u.last_name);
  document.getElementById('chatName').textContent = `${u.first_name} ${u.last_name}`;
  const st = document.getElementById('chatStatus');
  st.textContent = u.is_online ? '🟢 آنلاین' : '⚪ آفلاین';
  st.className = 'chat-header-status' + (u.is_online ? '' : ' offline');
  u.unread = 0;
  renderSidebar();
  await loadMessages();
  document.getElementById('msgInput').focus();
  if(window.innerWidth < 768) document.getElementById('sidebar').classList.remove('mobile-show');
};

async function loadMessages(){
  const r = await fetch(`/api/messages/${currentChatWith}`);
  const msgs = await r.json();
  const box = document.getElementById('messagesArea');
  box.innerHTML = '';
  msgs.forEach(m=>appendMessage(m,false));
  box.scrollTop = box.scrollHeight;
}

function appendMessage(m, scroll=true){
  const box = document.getElementById('messagesArea');
  const mine = m.sender_id === me.user_id;
  const row = document.createElement('div');
  row.className = `msg-row ${mine?'mine':'other'}`;
  let content = '';
  if(m.type === 'text') content = `<div class="msg-text">${esc(m.content)}</div>`;
  else if(m.type === 'audio') content = `<audio controls src="${m.content}"></audio>`;
  else if(m.type === 'video') content = `<video controls src="${m.content}"></video>`;
  else if(m.type === 'image') content = `<img class="msg-image" src="${m.content}" onclick="window.open('${m.content}')">`;
  else {
    const name = m.content.split('/').pop();
    content = `<div class="msg-file" onclick="window.open('${m.content}')">
      <div class="fi">${fileIcon(name)}</div>
      <div><div class="fname">${esc(name)}</div><div style="font-size:11px;color:#64748b">دانلود</div></div></div>`;
  }
  const check = mine ? '<span class="msg-check">✓✓</span>' : '';
  row.innerHTML = `<div class="msg-bubble">${content}<div class="msg-meta">${fmtTime(m.created_at)} ${check}</div></div>`;
  box.appendChild(row);
  if(scroll) box.scrollTop = box.scrollHeight;
}

function onMessage(m){
  if(currentChatWith && !currentGroupId && (m.sender_id === currentChatWith || m.receiver_id === currentChatWith)){
    appendMessage(m);
    if(m.sender_id === currentChatWith) fetch(`/api/messages/${currentChatWith}`);
  } else if(m.sender_id !== me.user_id){
    const u = usersCache.find(x=>x.id === m.sender_id);
    if(u){u.unread = (u.unread||0)+1;renderSidebar();}
    toast('پیام جدید');
  }
}

window.openGroup = async (gid) => {
  currentGroupId = gid;
  currentChatWith = null;
  const g = groupsCache.find(x=>x.id === gid);
  if(!g) return;
  document.getElementById('emptyState').classList.add('hidden');
  document.getElementById('pageView').classList.add('hidden');
  const cv = document.getElementById('chatView');
  cv.classList.remove('hidden'); cv.style.display = 'flex';
  const av = document.getElementById('chatAvatar');
  av.style.background = g.is_support ? 'linear-gradient(135deg,#f59e0b,#d97706)' : 'linear-gradient(135deg,#10b981,#059669)';
  av.textContent = g.is_support ? '🛟' : '👥';
  document.getElementById('chatName').textContent = g.name;
  document.getElementById('chatStatus').textContent = `${g.member_count || 0} عضو`;
  g.unread = 0;
  renderSidebar();
  const r = await fetch(`/api/group/${gid}/messages`);
  const msgs = await r.json();
  const box = document.getElementById('messagesArea');
  box.innerHTML = '';
  msgs.forEach(m=>appendGroupMessage(m,false));
  box.scrollTop = box.scrollHeight;
  document.getElementById('msgInput').focus();
  if(window.innerWidth < 768) document.getElementById('sidebar').classList.remove('mobile-show');
};

function appendGroupMessage(m, scroll=true){
  const box = document.getElementById('messagesArea');
  const mine = m.sender_id === me.user_id;
  const row = document.createElement('div');
  row.className = `msg-row ${mine?'mine':'other'}`;
  let content = '';
  if(m.type === 'text') content = `<div class="msg-text">${esc(m.content)}</div>`;
  else if(m.type === 'audio') content = `<audio controls src="${m.content}"></audio>`;
  else if(m.type === 'video') content = `<video controls src="${m.content}"></video>`;
  else if(m.type === 'image') content = `<img class="msg-image" src="${m.content}" onclick="window.open('${m.content}')">`;
  else {
    const name = m.content.split('/').pop();
    content = `<div class="msg-file" onclick="window.open('${m.content}')">
      <div class="fi">${fileIcon(name)}</div>
      <div><div class="fname">${esc(name)}</div><div style="font-size:11px;color:#64748b">دانلود</div></div></div>`;
  }
  const author = !mine && m.first_name ? `<div class="msg-author">${esc(m.first_name)} ${esc(m.last_name||'')}</div>` : '';
  const check = mine ? '<span class="msg-check">✓✓</span>' : '';
  const avatar = !mine && m.first_name ? avatarHTML(m.first_name+' '+(m.last_name||''), m.avatar_color||'#6366f1', 'small') : '';
  row.innerHTML = `${avatar}<div class="msg-bubble">${author}${content}<div class="msg-meta">${fmtTime(m.created_at)} ${check}</div></div>`;
  box.appendChild(row);
  if(scroll) box.scrollTop = box.scrollHeight;
}

function onGroupMessage(m){
  if(currentGroupId === m.group_id){
    appendGroupMessage(m);
  } else if(m.sender_id !== me.user_id){
    const g = groupsCache.find(x=>x.id === m.group_id);
    if(g){g.unread = (g.unread||0)+1;renderSidebar();}
    toast('پیام جدید در ' + (g ? g.name : 'گروه'));
  }
}

window.sendText = async () => {
  const input = document.getElementById('msgInput');
  const text = input.value.trim();
  if(!text) return;
  if(currentChatWith && !currentGroupId){
    input.value = ''; input.style.height = 'auto';
    await fetch('/api/send_text',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_id:currentChatWith,text})});
  } else if(currentGroupId){
    input.value = ''; input.style.height = 'auto';
    await fetch('/api/group/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group_id:currentGroupId,text})});
  }
};

const mi = document.getElementById('msgInput');
if(mi){
  mi.addEventListener('keydown', e => {if(e.key === 'Enter' && !e.shiftKey){e.preventDefault();sendText();}});
  mi.addEventListener('input', () => {
    mi.style.height = 'auto';
    mi.style.height = Math.min(mi.scrollHeight, 120)+'px';
    if(currentChatWith && !currentGroupId) fetch('/api/typing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to:currentChatWith})});
  });
}

window.toggleRecord = async () => {
  const btn = document.getElementById('recBtn');
  const status = document.getElementById('recStatus');
  if(mediaRecorder && mediaRecorder.state === 'recording'){mediaRecorder.stop();return;}
  if(!currentChatWith && !currentGroupId) return toast('اول یک چت انتخاب کن');
  try{
    const stream = await navigator.mediaDevices.getUserMedia({audio:true});
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.ondataavailable = e=>audioChunks.push(e.data);
    mediaRecorder.onstop = async () => {
      btn.classList.remove('recording');
      status.classList.remove('show');
      const blob = new Blob(audioChunks,{type:'audio/webm'});
      const fd = new FormData();
      if(currentGroupId){
        fd.append('group_id',currentGroupId);
        fd.append('type','audio');
        fd.append('file',blob,'voice.webm');
        await fetch('/api/group/send_file',{method:'POST',body:fd});
      } else {
        fd.append('to_id',currentChatWith);
        fd.append('type','audio');
        fd.append('file',blob,'voice.webm');
        await fetch('/api/send_file',{method:'POST',body:fd});
      }
      stream.getTracks().forEach(t=>t.stop());
    };
    mediaRecorder.start();
    btn.classList.add('recording');
    status.classList.add('show');
  }catch(e){toast('میکروفون در دسترس نیست');}
};

window.sendMedia = async (inp) => {
  const f = inp.files[0];
  if(!f || (!currentChatWith && !currentGroupId)) return;
  let type = 'file';
  if(f.type.startsWith('image/')) type = 'image';
  else if(f.type.startsWith('video/')) type = 'video';
  else if(f.type.startsWith('audio/')) type = 'audio';
  const fd = new FormData();
  fd.append('type',type);
  fd.append('file',f);
  if(currentGroupId){
    fd.append('group_id',currentGroupId);
    await fetch('/api/group/send_file',{method:'POST',body:fd});
  } else {
    fd.append('to_id',currentChatWith);
    await fetch('/api/send_file',{method:'POST',body:fd});
  }
  inp.value = '';
};

function showPage(html){
  document.getElementById('emptyState').classList.add('hidden');
  document.getElementById('chatView').classList.add('hidden');
  const pv = document.getElementById('pageView');
  pv.classList.remove('hidden');
  document.getElementById('pageContent').innerHTML = html;
}

window.openClass = (id) => {
  const c = sidebarData.classes.find(x=>x.id === id);
  if(!c) return;
  showPage(`<div class="page-card fade-in">
    <h2>🎓 ${esc(c.name)}</h2>
    <p style="color:var(--text-secondary);margin:16px 0">${esc(c.description||'')}</p>
    ${c.teacher?`<p>👨‍🏫 ${esc(c.teacher)}</p>`:''}
    ${c.schedule?`<p>🕐 ${esc(c.schedule)}</p>`:''}
    ${c.meet_link?`<a href="${esc(c.meet_link)}" target="_blank" class="btn btn-primary" style="display:inline-block;margin-top:16px">🔗 ورود به جلسه</a>`:'<p style="color:var(--text-muted);margin-top:16px">لینک تنظیم نشده</p>'}
  </div>`);
};

window.openVideo = (url, title) => {
  showPage(`<div class="page-card fade-in">
    <h2>🎬 ${esc(title)}</h2>
    <a href="${esc(url)}" target="_blank" class="btn btn-primary" style="display:inline-block;margin-top:16px">▶️ تماشا</a>
  </div>`);
};

window.openFile = (fid) => {
  const f = sidebarData.files.find(x=>x.id === fid);
  if(!f) return;
  const ext = f.file_type.toLowerCase();
  let preview = '';
  if(f.site_folder){
    preview = `<iframe src="/view/${fid}" style="width:100%;height:70vh;border:1px solid var(--border);border-radius:12px;margin-top:16px"></iframe>`;
  } else if(['png','jpg','jpeg','gif','webp','svg'].includes(ext)){
    preview = `<img src="/uploads/${f.filename}" style="max-width:100%;border-radius:12px;margin-top:16px">`;
  } else if(['mp4','webm','mov'].includes(ext)){
    preview = `<video controls src="/uploads/${f.filename}" style="width:100%;border-radius:12px;margin-top:16px"></video>`;
  } else if(['mp3','wav','ogg','m4a'].includes(ext)){
    preview = `<audio controls src="/uploads/${f.filename}" style="width:100%;margin-top:16px"></audio>`;
  } else if(['html','htm','pdf'].includes(ext)){
    preview = `<iframe src="/uploads/${f.filename}" style="width:100%;height:70vh;border:1px solid var(--border);border-radius:12px;margin-top:16px"></iframe>`;
  } else {
    preview = `<p style="color:var(--text-muted);margin-top:16px">این نوع فایل قابل پیش‌نمایش نیست</p>`;
  }
  showPage(`<div class="page-card fade-in">
    <h2>${fileIcon(f.original_name)} ${esc(f.title)}</h2>
    <p style="color:var(--text-secondary);font-size:13px;margin-top:8px">
      📦 ${f.file_type.toUpperCase()} • 📏 ${(f.size/1024).toFixed(1)} KB • 📤 ${esc(f.original_name)}
    </p>
    <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap">
      <a href="/api/file/${fid}/download" class="btn btn-primary">⬇️ دانلود</a>
      ${(f.site_folder||['html','htm'].includes(ext))?`<a href="/view/${fid}" target="_blank" class="btn btn-success">🌐 باز کردن در تب جدید</a>`:''}
    </div>
    ${preview}
  </div>`);
};

window.openCalc = () => {
  showPage(`<div class="page-card fade-in" style="max-width:450px">
    <h2>🧮 ماشین‌حساب علمی</h2>
    <div class="calc-container">
      <div class="calc-display">
        <div class="calc-history" id="calcHistory"></div>
        <div id="calcDisplay">0</div>
      </div>
      <div class="calc-buttons">
        <button class="calc-btn clr" onclick="calcClear()">C</button>
        <button class="calc-btn op" onclick="calcFn('sqrt')">√</button>
        <button class="calc-btn op" onclick="calcFn('pow')">x²</button>
        <button class="calc-btn op" onclick="calcOp('/')">÷</button>
        <button class="calc-btn" onclick="calcNum('7')">7</button>
        <button class="calc-btn" onclick="calcNum('8')">8</button>
        <button class="calc-btn" onclick="calcNum('9')">9</button>
        <button class="calc-btn op" onclick="calcOp('*')">×</button>
        <button class="calc-btn" onclick="calcNum('4')">4</button>
        <button class="calc-btn" onclick="calcNum('5')">5</button>
        <button class="calc-btn" onclick="calcNum('6')">6</button>
        <button class="calc-btn op" onclick="calcOp('-')">−</button>
        <button class="calc-btn" onclick="calcNum('1')">1</button>
        <button class="calc-btn" onclick="calcNum('2')">2</button>
        <button class="calc-btn" onclick="calcNum('3')">3</button>
        <button class="calc-btn op" onclick="calcOp('+')">+</button>
        <button class="calc-btn op" onclick="calcFn('sin')">sin</button>
        <button class="calc-btn" onclick="calcNum('0')">0</button>
        <button class="calc-btn" onclick="calcNum('.')">.</button>
        <button class="calc-btn eq" onclick="calcEq()">=</button>
      </div>
    </div>
  </div>`);
};
let calcExpr = '0';
function renderCalc(){document.getElementById('calcDisplay').textContent = calcExpr || '0';}
window.calcNum = (n) => {if(calcExpr === '0' || calcExpr === '') calcExpr = n; else calcExpr += n; renderCalc();};
window.calcOp = (op) => {const last = calcExpr.slice(-1); if('+-*/'.includes(last)) calcExpr = calcExpr.slice(0,-1); calcExpr += op; renderCalc();};
window.calcFn = (fn) => {
  try {
    const num = parseFloat(calcExpr);
    let val = num;
    if(fn === 'sqrt') val = Math.sqrt(num);
    else if(fn === 'pow') val = num * num;
    else if(fn === 'sin') val = Math.sin(num * Math.PI / 180);
    document.getElementById('calcHistory').textContent = `${fn}(${num})`;
    calcExpr = String(val);
    renderCalc();
  } catch(e) { toast('خطا'); }
};
window.calcClear = () => {calcExpr = '0'; document.getElementById('calcHistory').textContent = ''; renderCalc();};
window.calcEq = () => {
  try {
    document.getElementById('calcHistory').textContent = calcExpr + ' =';
    calcExpr = String(eval(calcExpr));
    renderCalc();
  } catch(e) { toast('خطا در محاسبه'); calcExpr = '0'; renderCalc(); }
};

window.openExam = async (eid) => {
  const e = sidebarData.exams.find(x=>x.id === eid);
  if(!e) return;
  if(e.my_attempt){
    const lb = await fetch(`/api/exam/${eid}/leaderboard`).then(r=>r.json());
    showPage(`<div class="page-card fade-in">
      <h2>📝 ${esc(e.title)}</h2>
      <p style="color:var(--success);margin:12px 0;font-weight:600">✅ نمره شما: ${e.my_attempt.score}/${e.my_attempt.total}</p>
      <h3 style="margin:16px 0 10px">🏆 نفرات برتر</h3>
      ${renderLeaderboard(lb)}</div>`);
    return;
  }
  showPage(`<div class="page-card fade-in">
    <h2>📝 ${esc(e.title)}</h2>
    <p style="color:var(--text-secondary);margin:8px 0">${esc(e.description||'')}</p>
    <p style="margin:12px 0">⏱️ ${e.duration_minutes} دقیقه • ❓ ${e.q_count} سوال</p>
    <p style="color:var(--warning);font-size:13px;margin-bottom:16px">⚠️ یک بار شرکت</p>
    <button class="btn btn-success" onclick="startExam(${eid})">🚀 شروع آزمون</button></div>`);
};

window.startExam = async (eid) => {
  if(!confirm('آماده‌ای؟')) return;
  const r = await fetch(`/api/exam/${eid}/start`,{method:'POST'});
  const d = await r.json();
  if(!d.ok) return toast(d.msg||'خطا');
  currentAttempt = d.attempt_id;
  showPage(`<div class="exam-timer" id="examTimer">⏱️ 00:00</div>
    <div class="page-card"><h2 style="margin-bottom:16px">${esc(d.title)}</h2>
    <div id="questionList"></div>
    <button class="btn btn-success" style="width:100%;margin-top:20px" onclick="submitExam()">✅ ارسال</button></div>`);
  const ql = document.getElementById('questionList');
  d.questions.forEach((q,i)=>{
    const div = document.createElement('div');
    div.className = 'question-block';
    div.innerHTML = `<div class="question-text">${i+1}. ${esc(q.text)}</div>
      ${['A','B','C','D'].map(k=>`<label class="option-label" onclick="selectOption(this)">
        <span class="option-key">${k}</span>
        <input type="radio" name="q_${q.id}" value="${k}">
        <span class="option-text">${esc(q['option_'+k.toLowerCase()])}</span></label>`).join('')}`;
    ql.appendChild(div);
  });
  startExamTimer(d.duration);
};

function selectOption(label){
  label.parentElement.querySelectorAll('.option-label').forEach(l=>l.classList.remove('selected'));
  label.classList.add('selected');
  label.querySelector('input').checked = true;
}
function startExamTimer(seconds){
  let left = seconds;
  const el = document.getElementById('examTimer');
  clearInterval(examTimer);
  const tick = () => {
    const m = Math.floor(left/60), s = left%60;
    el.textContent = `⏱️ ${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    if(left <= 0){clearInterval(examTimer);toast('زمان تمام!');submitExam();return;}
    left--;
  };
  tick();
  examTimer = setInterval(tick, 1000);
}
window.submitExam = async () => {
  clearInterval(examTimer);
  const answers = {};
  document.querySelectorAll('#questionList input:checked').forEach(inp=>{answers[inp.name.replace('q_','')] = inp.value;});
  const r = await fetch(`/api/attempt/${currentAttempt}/submit`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answers})});
  const d = await r.json();
  if(d.ok){toast(`نمره: ${d.score}/${d.total}`);location.reload();}
  else toast(d.msg||'خطا');
};
function renderLeaderboard(list){
  if(!list.length) return '<p style="color:var(--text-muted)">هنوز کسی نیست</p>';
  return list.map((r,i)=>{
    const cls = i===0?'gold':i===1?'silver':i===2?'bronze':'';
    const medal = i===0?'🥇':i===1?'🥈':i===2?'🥉':(i+1)+'.';
    return `<div class="lb-row ${cls}">${avatarHTML(r.first_name+' '+r.last_name, r.avatar_color, 'small')}
      <div style="flex:1"><div style="font-weight:600">${medal} ${esc(r.first_name)} ${esc(r.last_name)}</div></div>
      <span style="font-weight:700">${r.score}/${r.total}</span></div>`;
  }).join('');
}

window.backToSidebar = () => {document.getElementById('sidebar').classList.add('mobile-show');};

init();
"""

# ═══════════ JS — ادمین ═══════════
ADMIN_JS = r"""
function applyTheme(){
  const t = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', t);
  const btn = document.querySelector('.theme-toggle');
  if(btn) btn.textContent = t === 'dark' ? '☀️' : '🌙';
}
function toggleTheme(){
  const t = localStorage.getItem('theme') === 'dark' ? 'light' : 'dark';
  localStorage.setItem('theme', t);
  applyTheme();
}
applyTheme();

function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function toast(msg){const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),3000);}
function fileIcon(name){
  const ext = (name||'').split('.').pop().toLowerCase();
  const map = {pdf:'📄',doc:'📝',docx:'📝',xls:'📊',xlsx:'📊',ppt:'📽️',pptx:'📽️',
               zip:'📦',rar:'📦',txt:'📃',html:'🌐',htm:'🌐',
               jpg:'🖼️',jpeg:'🖼️',png:'🖼️',gif:'🖼️',webp:'🖼️',svg:'🖼️',
               mp3:'🎵',wav:'🎵',ogg:'🎵',m4a:'🎵',
               mp4:'🎬',webm:'🎬',mov:'🎬',avi:'🎬'};
  return map[ext] || '📎';
}

async function adminLogin(){
  const r = await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:aUser.value.trim(),password:aPass.value.trim()})});
  const d = await r.json();
  if(d.ok) showPanel();
  else aMsg.textContent = d.msg || 'خطا';
}

async function adminLogout(){
  await fetch('/api/admin/logout',{method:'POST'});
  location.reload();
}

function showPanel(){
  document.getElementById('adminLogin').classList.add('hidden');
  document.getElementById('adminPanel').classList.remove('hidden');
  loadTab('dashboard');
}

window.adminTab = (tab, el) => {
  document.querySelectorAll('.admin-nav-item').forEach(i=>i.classList.remove('active'));
  el.classList.add('active');
  loadTab(tab);
};

function loadTab(tab){
  const titles = {dashboard:'داشبورد',students:'مدیریت دانش‌آموزان',classes:'کلاس‌ها',videos:'ویدیوها',exams:'آزمون‌ها',ads:'تبلیغات',users:'کاربران',groups:'گروه‌ها',chats:'چت‌های خصوصی',group_chats:'چت گروهی',files:'فایل‌ها'};
  document.getElementById('adminTitle').textContent = titles[tab];
  document.getElementById('adminContent').innerHTML = '<p style="color:var(--text-muted)">بارگذاری...</p>';
  if(tab === 'dashboard') renderDashboard();
  else if(tab === 'students') renderStudents();
  else if(tab === 'classes') renderClasses();
  else if(tab === 'videos') renderVideos();
  else if(tab === 'exams') renderExams();
  else if(tab === 'ads') renderAds();
  else if(tab === 'users') renderUsers();
  else if(tab === 'groups') renderGroups();
  else if(tab === 'chats') renderChats();
  else if(tab === 'group_chats') renderGroupChats();
  else if(tab === 'files') renderFiles();
}

async function renderDashboard(){
  const [u,e,c,f,g,a] = await Promise.all([
    fetch('/api/admin/users').then(r=>r.json()),
    fetch('/api/admin/exams').then(r=>r.json()),
    fetch('/api/admin/classes').then(r=>r.json()),
    fetch('/api/admin/files').then(r=>r.json()),
    fetch('/api/admin/groups').then(r=>r.json()),
    fetch('/api/admin/ads').then(r=>r.json())
  ]);
  const online = u.filter(x=>x.is_online).length;
  document.getElementById('adminContent').innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px">
      <div class="admin-card"><div style="font-size:32px">👥</div>
        <div style="font-size:28px;font-weight:700">${u.length}</div>
        <div style="color:var(--text-secondary);font-size:13px">کل کاربران</div>
        <div style="color:var(--success);font-size:12px">🟢 ${online} آنلاین</div></div>
      <div class="admin-card"><div style="font-size:32px">📝</div>
        <div style="font-size:28px;font-weight:700">${e.length}</div>
        <div style="color:var(--text-secondary);font-size:13px">آزمون‌ها</div></div>
      <div class="admin-card"><div style="font-size:32px">🎓</div>
        <div style="font-size:28px;font-weight:700">${c.length}</div>
        <div style="color:var(--text-secondary);font-size:13px">کلاس‌ها</div></div>
      <div class="admin-card"><div style="font-size:32px">👥</div>
        <div style="font-size:28px;font-weight:700">${g.length}</div>
        <div style="color:var(--text-secondary);font-size:13px">گروه‌ها</div></div>
      <div class="admin-card"><div style="font-size:32px">📢</div>
        <div style="font-size:28px;font-weight:700">${a.length}</div>
        <div style="color:var(--text-secondary);font-size:13px">تبلیغات</div></div>
      <div class="admin-card"><div style="font-size:32px">📁</div>
        <div style="font-size:28px;font-weight:700">${f.length}</div>
        <div style="color:var(--text-secondary);font-size:13px">فایل‌ها</div></div>
    </div>`;
}

// ═══════════ دانش‌آموزان ═══════════
async function renderStudents(){
  const data = await fetch('/api/admin/students').then(r=>r.json());
  document.getElementById('adminContent').innerHTML = `
    <div class="admin-card">
      <h3 style="margin-bottom:12px">➕ افزودن / ویرایش دانش‌آموز</h3>
      <p style="color:var(--text-secondary);font-size:13px;margin-bottom:12px">
        فقط دانش‌آموزانی که اینجا تعریف می‌کنید می‌توانند وارد سایت شوند.
      </p>
      <input class="form-input" id="sFn" placeholder="نام">
      <input class="form-input" id="sLn" placeholder="نام خانوادگی">
      <input class="form-input" id="sPh" placeholder="شماره موبایل (نام کاربری)">
      <input class="form-input" id="sPw" type="text" placeholder="رمز عبور">
      <button class="btn btn-primary" onclick="saveStudent()">ذخیره دانش‌آموز</button>
    </div>
    <div class="admin-card">
      <h3 style="margin-bottom:12px">📋 لیست دانش‌آموزان (${data.length})</h3>
      ${data.map(u=>`<div class="user-item">
        <div class="avatar" style="background:#6366f1">${(u.first_name[0]||'')+(u.last_name[0]||'')}</div>
        <div class="user-info">
          <div class="user-name">${esc(u.first_name)} ${esc(u.last_name)}</div>
          <div class="user-phone">📱 ${esc(u.phone)}</div>
        </div>
        <span class="status-badge ${u.is_online?'online':''}">${u.is_online?'آنلاین':'آفلاین'}</span>
        <button class="btn btn-danger btn-sm" onclick="delStudent(${u.id})">حذف</button>
      </div>`).join('')||'<p style="color:var(--text-muted)">دانش‌آموزی تعریف نشده</p>'}
    </div>`;
}
window.saveStudent = async () => {
  const fn = document.getElementById('sFn').value.trim();
  const ln = document.getElementById('sLn').value.trim();
  const ph = document.getElementById('sPh').value.trim();
  const pw = document.getElementById('sPw').value.trim();
  if(!fn || !ln || !ph || !pw) return toast('همه فیلدها الزامی است');
  const r = await fetch('/api/admin/students', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({first_name: fn, last_name: ln, phone: ph, password: pw})
  });
  const d = await r.json();
  if(d.ok){toast('✅ ذخیره شد'); renderStudents();}
  else toast(d.msg || 'خطا');
};
window.delStudent = async (id) => {
  if(!confirm('دانش‌آموز و تمام پیام‌هایش حذف شود؟')) return;
  await fetch(`/api/admin/students/${id}`, {method: 'DELETE'});
  toast('حذف شد');
  renderStudents();
};

// ═══════════ تبلیغات ═══════════
async function renderAds(){
  const data = await fetch('/api/admin/ads').then(r=>r.json());
  document.getElementById('adminContent').innerHTML = `
    <div class="admin-card">
      <h3 style="margin-bottom:12px">📢 آپلود تبلیغ جدید</h3>
      <input class="form-input" id="adTitle" placeholder="عنوان تبلیغ (اختیاری)">
      <textarea class="form-input" id="adDesc" placeholder="توضیحات (اختیاری)"></textarea>
      <input class="form-input" id="adLink" placeholder="لینک (اختیاری)">
      <input class="form-input" type="file" id="adImage" accept="image/*">
      <button class="btn btn-primary" onclick="uploadAd()">⬆️ آپلود تبلیغ</button>
      <p id="adUpStatus" style="margin-top:10px;color:var(--accent)"></p>
    </div>
    <div class="admin-card">
      <h3 style="margin-bottom:12px">📋 تبلیغات (${data.length})</h3>
      <div class="ads-grid">
        ${data.map(a=>`
          <div class="ad-card">
            <img src="/ads/${esc(a.image_filename)}" alt="${esc(a.title)}">
            <div class="ad-card-body">
              <div class="ad-card-title">${esc(a.title||'بدون عنوان')}</div>
              ${a.description?`<div class="ad-card-desc">${esc(a.description)}</div>`:''}
              ${a.link?`<div class="ad-card-link" style="word-break:break-all">${esc(a.link)}</div>`:''}
              <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
                <span class="status-badge ${a.is_active?'online':''}">${a.is_active?'فعال':'غیرفعال'}</span>
                <button class="btn ${a.is_active?'btn-warning':'btn-success'} btn-sm" onclick="toggleAd(${a.id},${a.is_active?0:1})">${a.is_active?'غیرفعال':'فعال'}</button>
                <button class="btn btn-danger btn-sm" onclick="delAd(${a.id})">حذف</button>
              </div>
            </div>
          </div>`).join('')||'<p style="color:var(--text-muted)">تبلیغی نیست</p>'}
      </div>
    </div>`;
}
window.uploadAd = async () => {
  const f = document.getElementById('adImage').files[0];
  if(!f) return toast('عکس انتخاب کن');
  const fd = new FormData();
  fd.append('image', f);
  fd.append('title', document.getElementById('adTitle').value.trim());
  fd.append('description', document.getElementById('adDesc').value.trim());
  fd.append('link', document.getElementById('adLink').value.trim());
  document.getElementById('adUpStatus').textContent = '⏳ در حال آپلود...';
  try {
    const r = await fetch('/api/admin/ads', {method:'POST', body: fd});
    const d = await r.json();
    if(d.ok){toast('✅ تبلیغ اضافه شد');document.getElementById('adUpStatus').textContent = '';renderAds();}
    else {toast(d.msg||'خطا');document.getElementById('adUpStatus').textContent = '';}
  } catch(e) {
    toast('خطای شبکه');document.getElementById('adUpStatus').textContent = '';
  }
};
window.toggleAd = async (id, active) => {
  await fetch(`/api/admin/ads/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({is_active:!!active})});
  renderAds();
};
window.delAd = async (id) => {
  if(!confirm('تبلیغ حذف شود؟')) return;
  await fetch(`/api/admin/ads/${id}`,{method:'DELETE'});
  toast('حذف شد');
  renderAds();
};

// ═══════════ گروه‌ها ═══════════
async function renderGroups(){
  const data = await fetch('/api/admin/groups').then(r=>r.json());
  document.getElementById('adminContent').innerHTML = `
    <div class="admin-card">
      <h3 style="margin-bottom:12px">➕ ایجاد گروه جدید</h3>
      <input class="form-input" id="gName" placeholder="نام گروه">
      <textarea class="form-input" id="gDesc" placeholder="توضیحات"></textarea>
      <button class="btn btn-primary" onclick="createGroup()">ایجاد گروه</button>
    </div>
    <div class="admin-card">
      <h3 style="margin-bottom:12px">📋 گروه‌ها (${data.length})</h3>
      ${data.map(g=>`<div class="user-item">
        <div class="avatar" style="background:linear-gradient(135deg,${g.is_support?'#f59e0b,#d97706':'#10b981,#059669'})">${g.is_support?'🛟':'👥'}</div>
        <div class="user-info">
          <div class="user-name">${esc(g.name)} ${g.is_support?'<span class="status-badge support">پشتیبانی</span>':''}</div>
          <div class="user-phone">👥 ${g.member_count} عضو • 💬 ${g.msg_count} پیام</div>
        </div>
        ${g.is_support?'':`<button class="btn btn-danger btn-sm" onclick="delGroup(${g.id})">حذف</button>`}
      </div>`).join('')||'<p style="color:var(--text-muted)">گروهی نیست</p>'}
    </div>`;
}
window.createGroup = async () => {
  const name = gName.value.trim();
  if(!name) return toast('نام الزامی');
  await fetch('/api/admin/groups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,description:gDesc.value.trim()})});
  toast('گروه ایجاد شد');
  renderGroups();
};
window.delGroup = async (id) => {
  if(!confirm('گروه و پیام‌هایش حذف شود؟')) return;
  const r = await fetch(`/api/admin/groups/${id}`,{method:'DELETE'});
  const d = await r.json();
  if(d.ok){toast('حذف شد');renderGroups();}
  else toast(d.msg||'خطا');
};

async function renderGroupChats(){
  const data = await fetch('/api/admin/all_group_chats').then(r=>r.json());
  if(!data.length){document.getElementById('adminContent').innerHTML = '<div class="admin-card"><p style="color:var(--text-muted)">گروهی نیست</p></div>';return;}
  document.getElementById('adminContent').innerHTML = data.map(g=>`
    <div class="admin-card">
      <h3 style="margin-bottom:12px">${g.is_support?'🛟':'👥'} ${esc(g.name)} <span style="font-size:12px;color:var(--text-muted);font-weight:normal">(${g.messages.length} پیام)</span></h3>
      <div style="max-height:400px;overflow-y:auto;background:var(--bg-secondary);padding:12px;border-radius:10px">
        ${g.messages.map(m=>`<div style="margin-bottom:8px;padding:8px;background:var(--bg-primary);border-radius:8px">
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">${esc(m.sender_name)} • ${esc(m.created_at)}</div>
          ${m.type==='text'?`<div style="font-size:13px">${esc(m.content)}</div>`:
            m.type==='audio'?`<audio controls src="${m.content}"></audio>`:
            m.type==='video'?`<video controls src="${m.content}" style="max-width:100%;max-height:200px"></video>`:
            m.type==='image'?`<img src="${m.content}" style="max-width:200px;border-radius:8px">`:
            `<a href="${m.content}" target="_blank" style="color:var(--accent)">📎 ${esc(m.content.split('/').pop())}</a>`}</div>`).join('')||'<p style="color:var(--text-muted)">پیامی نیست</p>'}
      </div>
    </div>`).join('');
}

// ═══════════ کلاس‌ها ═══════════
async function renderClasses(){
  const data = await fetch('/api/classes').then(r=>r.json());
  document.getElementById('adminContent').innerHTML = `
    <div class="admin-card"><h3 style="margin-bottom:12px">➕ کلاس جدید</h3>
      <input class="form-input" id="cName" placeholder="نام کلاس">
      <input class="form-input" id="cTeacher" placeholder="مدرس">
      <input class="form-input" id="cSchedule" placeholder="زمان">
      <input class="form-input" id="cMeet" placeholder="لینک Meet">
      <textarea class="form-input" id="cDesc" placeholder="توضیحات"></textarea>
      <button class="btn btn-primary" onclick="addClass()">افزودن</button></div>
    <div class="admin-card"><h3 style="margin-bottom:12px">📋 کلاس‌ها (${data.length})</h3>
      <div>${data.map(c=>`<div class="user-item">
        <div class="avatar" style="background:linear-gradient(135deg,#6366f1,#8b5cf6)">🎓</div>
        <div class="user-info"><div class="user-name">${esc(c.name)}</div>
        <div class="user-phone">${c.teacher?'👨‍🏫 '+esc(c.teacher):''} ${c.schedule?'• 🕐 '+esc(c.schedule):''}</div></div>
        <button class="btn btn-danger btn-sm" onclick="delClass(${c.id})">حذف</button></div>`).join('')||'<p style="color:var(--text-muted)">کلاسی نیست</p>'}</div></div>`;
}
window.addClass = async () => {
  const name = cName.value.trim();
  if(!name) return toast('نام الزامی');
  await fetch('/api/admin/classes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,teacher:cTeacher.value.trim(),schedule:cSchedule.value.trim(),meet_link:cMeet.value.trim(),description:cDesc.value.trim()})});
  toast('اضافه شد');
  renderClasses();
};
window.delClass = async (id) => {if(!confirm('حذف؟'))return;await fetch(`/api/admin/classes/${id}`,{method:'DELETE'});renderClasses();};

// ═══════════ ویدیوها ═══════════
async function renderVideos(){
  const data = await fetch('/api/videos').then(r=>r.json());
  document.getElementById('adminContent').innerHTML = `
    <div class="admin-card"><h3 style="margin-bottom:12px">➕ ویدیو</h3>
      <input class="form-input" id="vTitle" placeholder="عنوان">
      <input class="form-input" id="vUrl" placeholder="لینک">
      <textarea class="form-input" id="vDesc" placeholder="توضیحات"></textarea>
      <button class="btn btn-primary" onclick="addVideo()">افزودن</button></div>
    <div class="admin-card"><h3 style="margin-bottom:12px">📋 ویدیوها (${data.length})</h3>
      ${data.map(v=>`<div class="user-item">
        <div class="avatar" style="background:linear-gradient(135deg,#ec4899,#f43f5e)">🎬</div>
        <div class="user-info"><div class="user-name">${esc(v.title)}</div>
        <div class="user-phone" style="word-break:break-all">${esc(v.url)}</div></div>
        <button class="btn btn-danger btn-sm" onclick="delVideo(${v.id})">حذف</button></div>`).join('')||'<p style="color:var(--text-muted)">ویدیویی نیست</p>'}</div>`;
}
window.addVideo = async () => {
  const title = vTitle.value.trim(), url = vUrl.value.trim();
  if(!title||!url) return toast('عنوان و لینک الزامی');
  await fetch('/api/admin/videos',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,url,description:vDesc.value.trim()})});
  toast('اضافه شد');
  renderVideos();
};
window.delVideo = async (id) => {if(!confirm('حذف؟'))return;await fetch(`/api/admin/videos/${id}`,{method:'DELETE'});renderVideos();};

// ═══════════ آزمون‌ها ═══════════
async function renderExams(){
  const data = await fetch('/api/admin/exams').then(r=>r.json());
  document.getElementById('adminContent').innerHTML = `
    <div class="admin-card"><h3 style="margin-bottom:12px">➕ آزمون جدید</h3>
      <input class="form-input" id="eTitle" placeholder="عنوان">
      <input class="form-input" id="eDuration" type="number" value="10" placeholder="مدت (دقیقه)">
      <textarea class="form-input" id="eDesc" placeholder="توضیحات"></textarea>
      <button class="btn btn-primary" onclick="createExam()">ایجاد</button></div>
    <div id="examList">${data.map(e=>`
      <div class="admin-card">
        <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px">
          <div><h3>📝 ${esc(e.title)} <span class="status-badge ${e.is_active?'online':''}">${e.is_active?'فعال':'غیرفعال'}</span></h3>
          <p style="color:var(--text-secondary);font-size:13px;margin-top:6px">⏱️ ${e.duration_minutes} دقیقه • ❓ ${e.q_count} سوال • 👥 ${e.a_count} شرکت‌کننده</p></div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <button class="btn btn-primary btn-sm" onclick="openEditor(${e.id})">سوالات</button>
            <button class="btn ${e.is_active?'btn-warning':'btn-success'} btn-sm" onclick="toggleExam(${e.id},${e.is_active?0:1})">${e.is_active?'غیرفعال':'فعال'}</button>
            <button class="btn btn-success btn-sm" onclick="showResults(${e.id})">نتایج</button>
            <button class="btn btn-danger btn-sm" onclick="delExam(${e.id})">حذف</button></div></div>
        <div id="results-${e.id}" style="margin-top:12px"></div></div>
      <div id="editor-${e.id}" style="display:none" class="admin-card">
        <h3 style="margin-bottom:12px">✏️ سوالات</h3>
        <input class="form-input" id="qText-${e.id}" placeholder="متن سوال">
        <input class="form-input" id="qA-${e.id}" placeholder="گزینه A">
        <input class="form-input" id="qB-${e.id}" placeholder="گزینه B">
        <input class="form-input" id="qC-${e.id}" placeholder="گزینه C">
        <input class="form-input" id="qD-${e.id}" placeholder="گزینه D">
        <select class="form-input" id="qCorrect-${e.id}"><option value="A">پاسخ A</option><option value="B">پاسخ B</option><option value="C">پاسخ C</option><option value="D">پاسخ D</option></select>
        <button class="btn btn-success" onclick="addQuestion(${e.id})">افزودن سوال</button>
        <div id="qList-${e.id}" style="margin-top:12px"></div></div>
    `).join('')||'<p style="color:var(--text-muted)">آزمونی نیست</p>'}</div>`;
}
window.createExam = async () => {
  const title = eTitle.value.trim(), dur = parseInt(eDuration.value)||10;
  if(!title) return toast('عنوان الزامی');
  await fetch('/api/admin/exams',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,duration_minutes:dur,description:eDesc.value.trim()})});
  toast('ایجاد شد');
  renderExams();
};
window.toggleExam = async (id, active) => {
  await fetch(`/api/admin/exams/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({is_active:!!active})});
  renderExams();
};
window.delExam = async (id) => {if(!confirm('حذف آزمون؟'))return;await fetch(`/api/admin/exams/${id}`,{method:'DELETE'});renderExams();};
window.openEditor = async (eid) => {
  const box = document.getElementById(`editor-${eid}`);
  if(box.style.display === 'block'){box.style.display = 'none';return;}
  document.querySelectorAll('[id^="editor-"]').forEach(el=>el.style.display = 'none');
  box.style.display = 'block';
  await loadQuestions(eid);
};
async function loadQuestions(eid){
  const data = await fetch(`/api/admin/exams/${eid}/questions`).then(r=>r.json());
  document.getElementById(`qList-${eid}`).innerHTML = data.map((q,i)=>`
    <div class="user-item"><div style="flex:1">
      <div style="font-weight:600;margin-bottom:4px">${i+1}. ${esc(q.text)}</div>
      <div style="font-size:12px;color:var(--text-secondary)">A) ${esc(q.option_a)} • B) ${esc(q.option_b)} • C) ${esc(q.option_c)} • D) ${esc(q.option_d)}</div>
      <span class="status-badge online" style="margin-top:4px">✓ ${q.correct}</span></div>
      <button class="btn btn-danger btn-sm" onclick="delQuestion(${q.id},${eid})">حذف</button></div>`).join('')||'<p style="color:var(--text-muted)">سوالی نیست</p>';
}
window.addQuestion = async (eid) => {
  const text = document.getElementById(`qText-${eid}`).value.trim();
  if(!text) return toast('متن الزامی');
  await fetch(`/api/admin/exams/${eid}/questions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
    text,
    option_a: document.getElementById(`qA-${eid}`).value.trim(),
    option_b: document.getElementById(`qB-${eid}`).value.trim(),
    option_c: document.getElementById(`qC-${eid}`).value.trim(),
    option_d: document.getElementById(`qD-${eid}`).value.trim(),
    correct: document.getElementById(`qCorrect-${eid}`).value
  })});
  toast('اضافه شد');
  ['qText','qA','qB','qC','qD'].forEach(id=>document.getElementById(`${id}-${eid}`).value = '');
  await loadQuestions(eid);
  renderExams();
};
window.delQuestion = async (qid, eid) => {if(!confirm('حذف؟'))return;await fetch(`/api/admin/questions/${qid}`,{method:'DELETE'});await loadQuestions(eid);};
window.showResults = async (eid) => {
  const box = document.getElementById(`results-${eid}`);
  if(box.innerHTML){box.innerHTML = '';return;}
  const data = await fetch(`/api/admin/exams/${eid}/results`).then(r=>r.json());
  if(!data.length){box.innerHTML = '<p style="color:var(--text-muted)">هنوز کسی نیست</p>';return;}
  box.innerHTML = '<h4 style="margin-bottom:10px">🏆 نتایج</h4>' + data.map((r,i)=>{
    const cls = i===0?'gold':i===1?'silver':i===2?'bronze':'';
    const medal = i===0?'🥇':i===1?'🥈':i===2?'🥉':(i+1)+'.';
    return `<div class="lb-row ${cls}"><div style="flex:1"><b>${medal} ${esc(r.first_name)} ${esc(r.last_name)}</b>
      <div style="font-size:11px;color:var(--text-muted)">${esc(r.phone)}</div></div>
      <span style="font-weight:700">${r.score}/${r.total}</span></div>`;
  }).join('');
};

// ═══════════ کاربران ═══════════
async function renderUsers(){
  const data = await fetch('/api/admin/users').then(r=>r.json());
  document.getElementById('adminContent').innerHTML = `<div class="admin-card">
    <h3 style="margin-bottom:12px">👥 کاربران (${data.length})</h3>
    ${data.map(u=>`<div class="user-item">
      <div class="avatar" style="background:${u.avatar_color}">${(u.first_name[0]||'')+(u.last_name[0]||'')}</div>
      <div class="user-info"><div class="user-name">${esc(u.first_name)} ${esc(u.last_name)}</div>
      <div class="user-phone">📱 ${esc(u.phone)}</div></div>
      <span class="status-badge ${u.is_online?'online':''}">${u.is_online?'آنلاین':'آفلاین'}</span></div>`).join('')||'<p style="color:var(--text-muted)">کاربری نیست</p>'}</div>`;
}

// ═══════════ چت‌ها ═══════════
async function renderChats(){
  const data = await fetch('/api/admin/all_chats').then(r=>r.json());
  if(!data.length){document.getElementById('adminContent').innerHTML = '<div class="admin-card"><p style="color:var(--text-muted)">هنوز چتی نیست</p></div>';return;}
  document.getElementById('adminContent').innerHTML = data.map(chat=>{
    const first = chat.messages[0];
    return `<div class="admin-card">
      <h3 style="margin-bottom:12px">💬 ${esc(first.sender_name)} ↔ ${esc(first.receiver_name)} <span style="font-size:12px;color:var(--text-muted);font-weight:normal">(${chat.messages.length})</span></h3>
      <div style="max-height:400px;overflow-y:auto;background:var(--bg-secondary);padding:12px;border-radius:10px">
        ${chat.messages.map(m=>`<div style="margin-bottom:8px;padding:8px;background:var(--bg-primary);border-radius:8px">
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">${esc(m.sender_name)}</div>
          ${m.type==='text'?`<div style="font-size:13px">${esc(m.content)}</div>`:
            m.type==='audio'?`<audio controls src="${m.content}"></audio>`:
            m.type==='video'?`<video controls src="${m.content}" style="max-width:100%;max-height:200px"></video>`:
            m.type==='image'?`<img src="${m.content}" style="max-width:200px;border-radius:8px">`:
            `<a href="${m.content}" target="_blank" style="color:var(--accent)">📎 ${esc(m.content.split('/').pop())}</a>`}</div>`).join('')}
      </div></div>`;
  }).join('');
}

// ═══════════ فایل‌ها ═══════════
async function renderFiles(){
  const data = await fetch('/api/admin/files').then(r=>r.json());
  document.getElementById('adminContent').innerHTML = `
    <div class="admin-card">
      <h3 style="margin-bottom:12px">📤 آپلود فایل جدید</h3>
      <p style="color:var(--text-secondary);font-size:13px;margin-bottom:12px">
        PDF، Word، PowerPoint، Excel، ZIP، HTML، عکس، ویدیو و...
      </p>
      <input class="form-input" id="fTitle" placeholder="عنوان فایل (اختیاری)">
      <input class="form-input" type="file" id="fFile">
      <button class="btn btn-primary" onclick="uploadFile()">⬆️ آپلود</button>
      <p id="upStatus" style="margin-top:10px;color:var(--accent)"></p>
    </div>
    <div class="admin-card">
      <h3 style="margin-bottom:12px">📁 فایل‌ها (${data.length})</h3>
      <div class="files-grid">${data.map(f=>`
        <div class="file-card">
          <div class="file-icon">${fileIcon(f.original_name)}</div>
          <div class="file-title">${esc(f.title)}</div>
          <div class="file-meta">${f.file_type.toUpperCase()} • ${(f.size/1024).toFixed(0)} KB</div>
          <div style="display:flex;gap:4px;margin-top:8px;justify-content:center">
            <a href="/api/file/${f.id}/download" class="btn btn-primary btn-sm" style="text-decoration:none">⬇️</a>
            ${f.site_folder?`<a href="/view/${f.id}" target="_blank" class="btn btn-success btn-sm" style="text-decoration:none">🌐</a>`:''}
            <button class="btn btn-danger btn-sm" onclick="delFile(${f.id})">🗑️</button>
          </div>
        </div>`).join('')||'<p style="color:var(--text-muted)">فایلی نیست</p>'}</div>
    </div>`;
}
window.uploadFile = async () => {
  const f = document.getElementById('fFile').files[0];
  if(!f) return toast('فایل انتخاب کن');
  const title = document.getElementById('fTitle').value.trim();
  const fd = new FormData();
  fd.append('file', f);
  fd.append('title', title);
  document.getElementById('upStatus').textContent = '⏳ در حال آپلود...';
  try {
    const r = await fetch('/api/upload', {method:'POST', body: fd});
    const d = await r.json();
    if(d.ok){toast('✅ آپلود شد');document.getElementById('upStatus').textContent = '';renderFiles();}
    else {toast(d.msg||'خطا');document.getElementById('upStatus').textContent = '';}
  } catch(e) {
    toast('خطای شبکه');document.getElementById('upStatus').textContent = '';
  }
};
window.delFile = async (fid) => {
  if(!confirm('فایل حذف شود؟')) return;
  await fetch(`/api/file/${fid}/delete`, {method:'POST'});
  toast('حذف شد');
  renderFiles();
};

fetch('/api/admin/check').then(r=>r.json()).then(d=>{if(d.ok) showPanel();});
"""

# ═══════════ Routes ═══════════
@app.route('/')
def route_index():
    if 'user_id' not in session:
        return redirect('/login')
    return INDEX_HTML.replace('__CSS__', CSS).replace('__JS__', APP_JS).replace('__SITE__', SITE_NAME)

@app.route('/login')
def route_login():
    return LOGIN_HTML.replace('__CSS__', CSS).replace('__SITE__', SITE_NAME)

@app.route('/admin')
def route_admin():
    return ADMIN_HTML.replace('__CSS__', CSS).replace('__JS__', ADMIN_JS).replace('__SITE__', SITE_NAME)

# ═══════════ اجرا ═══════════
if __name__ == '__main__':
    print("=" * 50)
    print("  Halzon v5.0 آماده است")
    print("=" * 50)
    print("  http://localhost:5000/login")
    print("  http://localhost:5000/admin  (admin/1234)")
    print("=" * 50)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
