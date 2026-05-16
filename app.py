import os
import sqlite3
import requests
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from functools import wraps
from openai import OpenAI
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super-secret-key-for-isbn-manager")

# 초기 기본 로그인 정보 (DB에 계정이 없을 때 최초 1회 생성용)
DEFAULT_ADMIN_ID = os.environ.get("ADMIN_ID", "admin")
DEFAULT_ADMIN_PW = os.environ.get("ADMIN_PW", "1234")

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DB_PATH = os.environ.get("DB_PATH", "database.db")

client = OpenAI(api_key=OPENAI_API_KEY)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 1. 생성 기록 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  isbn TEXT,
                  title TEXT,
                  target TEXT,
                  content TEXT,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(isbn, target))''')
    
    # 2. 관리자 계정 테이블 (비밀번호 변경 기능용)
    c.execute('''CREATE TABLE IF NOT EXISTS admin_users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  password TEXT)''')
    
    # 관리자 계정이 비어있다면 기본 계정 생성
    c.execute("SELECT * FROM admin_users WHERE username = ?", (DEFAULT_ADMIN_ID,))
    if not c.fetchone():
        c.execute("INSERT INTO admin_users (username, password) VALUES (?, ?)", (DEFAULT_ADMIN_ID, DEFAULT_ADMIN_PW))
        
    conn.commit()
    conn.close()

init_db()

def save_history(isbn, title, target, content):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO history (isbn, title, target, content) 
            VALUES (?, ?, ?, ?)
            ON CONFLICT(isbn, target) 
            DO UPDATE SET content=excluded.content, created_at=CURRENT_TIMESTAMP
        """, (isbn, title, target, content))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB 저장 오류 발생: {e}")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form.get('username')
        user_pw = request.form.get('password')
        
        # DB에서 계정 정보 확인
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT * FROM admin_users WHERE username = ? AND password = ?", (user_id, user_pw))
        admin = c.fetchone()
        conn.close()
        
        if admin:
            session['logged_in'] = True
            session['username'] = user_id
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="아이디 또는 비밀번호가 일치하지 않습니다.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html', username=session.get('username'))

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    data = request.json
    current_pw = data.get('current_pw')
    new_pw = data.get('new_pw')
    username = session.get('username')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM admin_users WHERE username = ? AND password = ?", (username, current_pw))
    admin = c.fetchone()

    if admin:
        c.execute("UPDATE admin_users SET password = ? WHERE username = ?", (new_pw, username))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "비밀번호가 성공적으로 변경되었습니다."})
    else:
        conn.close()
        return jsonify({"success": False, "message": "현재 비밀번호가 일치하지 않습니다."})

def get_book_info(isbn):
    url = f"https://openapi.naver.com/v1/search/book.json?query={isbn}&display=1"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data.get('items'):
            return data['items'][0]
    except Exception as e:
        print(f"도서 정보 조회 중 오류 발생: {e}")
    return None

def generate_content(book_info, target):
    prompts = {
        'smartstore': "스마트스토어 상세페이지용 HTML을 작성해줘. 표지, 도서정보, 핵심 포인트, 추천 대상, 목차, 배송 이미지가 포함되어야 해. 판매자 관점의 표현은 모두 제거하고, 철저히 독자 관점에서 작성해. 마크다운(```html) 기호 없이 한 번에 복사할 수 있는 순수 HTML 코드만 출력해.",
        'blog': "네이버 블로그에 올릴 정보 제공용 도서 소개글을 작성해줘. 본문 안에 책 제목은 2회 정도만 자연스럽게 포함해. 구성: 블로그 제목 추천 3개, 도서 정보, 책 소개, 구성 요약, 핵심 포인트, 이런 분께 추천, 한 줄 요약, 해시태그.",
        'cafe': "네이버 카페 커뮤니티에 정보 공유 목적으로 올릴 자연스러운 도서 추천글을 작성해줘. 구성: 카페 제목 추천 3개, 5~7줄의 짧은 소개글, 자연스러운 추천글, 댓글 답변용 문구."
    }
    
    target_prompt = prompts.get(target, "도서 홍보 문구를 작성해줘.")
    prompt = f"""
    아래 도서 정보를 바탕으로 {target_prompt}
    
    도서명: {book_info.get('title')}
    저자: {book_info.get('author')}
    출판사: {book_info.get('publisher')}
    소개: {book_info.get('description')}
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"콘텐츠 생성 중 오류가 발생했습니다: {str(e)}"

@app.route('/fetch_book', methods=['POST'])
@login_required
def fetch_book():
    isbn = request.json.get('isbn')
    book_info = get_book_info(isbn)
    if book_info:
        return jsonify({"success": True, "data": book_info})
    return jsonify({"success": False, "message": "도서 정보를 찾을 수 없습니다."})

@app.route('/generate', methods=['POST'])
@login_required
def generate():
    data = request.json
    book_info = data.get('book_info')
    target = data.get('target')
    
    content = generate_content(book_info, target)
    
    if book_info:
        save_history(book_info.get('isbn'), book_info.get('title'), target, content)
    
    return jsonify({"success": True, "content": content})

@app.route('/search_history', methods=['GET'])
@login_required
def search_history():
    isbn = request.args.get('isbn')
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT target, content FROM history WHERE isbn = ?", (isbn,))
        rows = c.fetchall()
        conn.close()
        
        if rows:
            data = {row['target']: row['content'] for row in rows}
            return jsonify({"success": True, "data": data})
        return jsonify({"success": False, "message": "해당 ISBN으로 생성된 기록이 없습니다."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/history_list', methods=['GET'])
@login_required
def history_list():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # ISBN을 기준으로 그룹화하여 최신 기록을 가져옵니다
        c.execute("""
            SELECT isbn, title, MAX(created_at) as last_date, GROUP_CONCAT(target) as targets 
            FROM history 
            GROUP BY isbn 
            ORDER BY last_date DESC
        """)
        rows = c.fetchall()
        conn.close()
        
        data = []
        for row in rows:
            data.append({
                "isbn": row['isbn'], 
                "title": row['title'], 
                "date": row['last_date'][:10],
                "targets": row['targets']
            })
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
