import os
import requests
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# API 키 설정 (Railway 환경변수에서 관리 권장)
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# 1. 네이버 도서 정보 조회 함수
def get_book_info(isbn):
    url = f"https://openapi.naver.com/v1/search/book.json?query={isbn}&display=1"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    response = requests.get(url, headers=headers)
    data = response.json()
    
    if data.get('items'):
        return data['items'][0]
    return None

# 2. GPT 기반 콘텐츠 생성 함수
def generate_content(book_info, target):
    prompt = f"""
    도서 정보를 바탕으로 {target}용 마케팅 콘텐츠를 작성해줘.
    도서명: {book_info['title']}
    저자: {book_info['author']}
    출판사: {book_info['publisher']}
    소개: {book_info['description']}
    
    형식: 독자 중심의 부드럽고 설득력 있는 문체로 작성해줘.
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/fetch_book', methods=['POST'])
def fetch_book():
    isbn = request.json.get('isbn')
    book_info = get_book_info(isbn)
    if book_info:
        return jsonify({"success": True, "data": book_info})
    return jsonify({"success": False, "message": "도서 정보를 찾을 수 없습니다."})

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    book_info = data.get('book_info')
    target = data.get('target') # 'smartstore', 'blog', 'cafe' 등
    
    content = generate_content(book_info, target)
    return jsonify({"success": True, "content": content})

if __name__ == '__main__':
    app.run(debug=True)
