# 💸 여행 정산 앱 (Streamlit)

가족여행 / 커플여행을 위한  
아이폰에서도 사용 가능한 여행 경비 정산 웹앱입니다.

## 주요 기능
- 가족 구성 저장 & 재사용
- 가족 / 커플 / 자유 여행 프리셋
- 외화 + 환율 적용
- 지출 저장 / 불러오기
- 누가 누구에게 얼마 보내야 하는지 계산
- PDF 정산 리포트 다운로드
- 아이폰 홈화면 앱처럼 사용 가능

## 실행 방법
```bash
pip install -r requirements.txt
streamlit run app.py

---

# 3️⃣ GitHub에 업로드

### 방법 A (가장 쉬움 – GitHub Desktop)
1. GitHub Desktop 설치
2. **Add local repository**
3. `travel-settlement-streamlit` 폴더 선택
4. Commit
5. Push

### 방법 B (터미널)

```bash
cd travel-settlement-streamlit
git init
git add .
git commit -m "Initial travel settlement app"
git branch -M main
git remote add origin https://github.com/본인아이디/travel-settlement-streamlit.git
git push -u origin main
