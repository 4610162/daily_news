import google.generativeai as genai

# 본인의 API 키를 입력하세요
GEMINI_API_KEY = "AIzaSyB_pB07tGS5yNlrHCG7-DdbP4SgiPFNtVY"
genai.configure(api_key=GEMINI_API_KEY)

print("--- 사용 가능한 모델 목록 ---")

# 사용 가능한 모든 모델 리스트 가져오기
for m in genai.list_models():
    # 'generateContent' 메서드를 지원하는 모델만 필터링해서 보기
    if 'generateContent' in m.supported_generation_methods:
        print(f"모델 이름: {m.name}")
        print(f"표시 이름: {m.display_name}")
        print(f"설명: {m.description}")
        print("-" * 30)