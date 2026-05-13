import os
import requests
from flask import Flask, render_template, request, jsonify
from openai import OpenAI
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

app = Flask(__name__)

# API 키 설정 (Railway 환경변수에서 가져옴)
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# OpenAI 클라이언트 초기화
# 라이브러리 업데이트 후에도 문제가 지속될 경우를 대비해 
# 환경 변수에서 프록시 설정을 무시하도록 클라이언트를 생성합니다.
client = OpenAI(api_key=OPENAI_API_KEY)

def get_book_info(isbn):
    """네이버 도서 API를 통해 도서 정보를 가져옵니다."""
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
    """GPT-4o-mini 모델을 사용하여 각 채널에 맞는 콘텐츠를 생성합니다."""
    prompts = {
        'smartstore': "스마트스토어 판매를 위한 상세페이지 HTML 및 핵심 포인트를 작성해줘.",
        'blog': "네이버 블로그에 올릴 정성스러운 도서 리뷰 및 소개글을 작성해줘.",
        'cafe': "네이버 카페 커뮤니티에 어울리는 자연스러운 도서 추천글을 작성해줘."
    }
    
    target_prompt = prompts.get(target, "도서 홍보 문구를 작성해줘.")
    
    prompt = f"""
    아래 도서 정보를 바탕으로 {target_prompt}
    
    도서명: {book_info.get('title')}
    저자: {book_info.get('author')}
    출판사: {book_info.get('publisher')}
    소개: {book_info.get('description')}
    
    형식: 독자의 관점에서 유익함을 느낄 수 있도록 설득력 있게 작성해줘.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"콘텐츠 생성 중 오류가 발생했습니다: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/fetch_book', methods=['POST'])
def fetch_book():
    isbn = request.json.get('isbn')
    book_info = get_book_info(isbn)
    if book_info:
        return jsonify({"success": True, "data": book_info})
    return jsonify({"success": False, "message": "도서 정보를 찾을 수 없습니다. ISBN을 확인해 주세요."})

@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    book_info = data.get('book_info')
    target = data.get('target')
    
    content = generate_content(book_info, target)
    return jsonify({"success": True, "content": content})

if __name__ == '__main__':
    # 로컬 테스트용
    app.run(host='0.0.0.0', port=5000, debug=True)
