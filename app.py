import streamlit as st
from datetime import date, datetime
import json
from io import BytesIO
from collections import defaultdict
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# --------------------------------------------------
# 기본 설정
# --------------------------------------------------
st.set_page_config(
    page_title="여행 정산",
    page_icon="💸",
    layout="centered"
)

st.markdown("""
<style>
header {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------
# Session State
# --------------------------------------------------
st.session_state.setdefault("expenses", [])
st.session_state.setdefault("trip_name", "새 여행")
st.session_state.setdefault("family_profile", None)

# --------------------------------------------------
# 유틸 함수
# --------------------------------------------------
def save_json(data):
    buf = BytesIO()
    buf.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    buf.seek(0)
    return buf

def calculate_settlement(expenses, participants):
    paid = defaultdict(int)
    owed = defaultdict(int)

    for e in expenses:
        share = e["amount_krw"] // len(e["participants"])
        paid[e["payer"]] += e["amount_krw"]
        for p in e["participants"]:
            owed[p] += share

    balance = {p: paid[p] - owed[p] for p in participants}

    senders = []
    receivers = []

    for p, b in balance.items():
        if b < 0:
            senders.append([p, -b])
        elif b > 0:
            receivers.append([p, b])

    transfers = []
    i = j = 0
    while i < len(senders) and j < len(receivers):
        amt = min(senders[i][1], receivers[j][1])
        transfers.append({
            "from": senders[i][0],
            "to": receivers[j][0],
            "amount": amt
        })
        senders[i][1] -= amt
        receivers[j][1] -= amt
        if senders[i][1] == 0: i += 1
        if receivers[j][1] == 0: j += 1

    return transfers

def generate_pdf(trip_name, expenses, transfers):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 40

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, trip_name)
    y -= 25

    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    y -= 30

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "지출 내역")
    y -= 15

    c.setFont("Helvetica", 10)
    for e in expenses:
        line = f"{e['date']} | {e['category']} | {e['payer']} | {e['amount_krw']:,}원"
        c.drawString(45, y, line)
        y -= 14
        if y < 50:
            c.showPage()
            y = h - 40

    y -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "정산 결과")
    y -= 15

    c.setFont("Helvetica", 10)
    for t in transfers:
        line = f"{t['from']} → {t['to']} : {t['amount']:,}원"
        c.drawString(45, y, line)
        y -= 14

    c.save()
    buf.seek(0)
    return buf

# --------------------------------------------------
# 가족 구성 저장 / 불러오기
# --------------------------------------------------
st.subheader("👨‍👩‍👧‍👦 가족 구성")

col1, col2 = st.columns(2)

with col1:
    fname = st.text_input("가족 이름", "우리 가족")
    adults = st.multiselect("성인", ["아빠","엄마","할아버지","할머니"], ["아빠","엄마"])
    kids = st.multiselect("아이", ["아이1","아이2","아이3"], [])
    default_payer = st.selectbox("기본 결제자", adults)

    if st.button("💾 가족 구성 저장"):
        profile = {
            "profile_name": fname,
            "adults": adults,
            "kids": kids,
            "default_payer": default_payer
        }
        st.download_button(
            "📥 가족 구성 파일 다운로드",
            data=save_json(profile),
            file_name=f"{fname}_family.json",
            mime="application/json"
        )

with col2:
    uploaded_family = st.file_uploader("📂 가족 구성 불러오기", type=["json"])
    if uploaded_family:
        st.session_state.family_profile = json.load(uploaded_family)
        st.success("가족 구성 적용 완료")

# --------------------------------------------------
# 여행 프리셋
# --------------------------------------------------
st.subheader("🧳 여행 설정")

preset = st.radio(
    "여행 유형",
    ["👨‍👩‍👧‍👦 가족여행", "💑 커플여행", "🧑‍🤝‍🧑 자유 설정"],
    horizontal=True
)

if preset == "👨‍👩‍👧‍👦 가족여행" and st.session_state.family_profile:
    adults = st.session_state.family_profile["adults"]
    kids = st.session_state.family_profile["kids"]
    participants = adults + kids

    def default_participants(cat):
        return adults if cat in ["식사","숙박"] else participants

elif preset == "💑 커플여행":
    participants = ["A","B"]
    def default_participants(cat):
        return participants

else:
    participants = st.multiselect(
        "참여자",
        ["A","B","C","D","E","F","G","H"],
        ["A","B"]
    )
    def default_participants(cat):
        return participants

# --------------------------------------------------
# 환율
# --------------------------------------------------
st.subheader("💱 환율")
rates = {
    "KRW": 1.0,
    "USD": st.number_input("USD → KRW", 1000.0, value=1350.0),
    "JPY": st.number_input("JPY → KRW", 1.0, value=9.0)
}

# --------------------------------------------------
# 지출 입력 (초간단)
# --------------------------------------------------
st.subheader("⚡ 지출 입력")

category = st.selectbox("항목", ["식사","숙박","교통","카페","쇼핑","기타"])
currency = st.selectbox("통화", list(rates.keys()))
amount = st.number_input("금액", min_value=0)
payer = st.selectbox("결제자", participants)

if st.button("➕ 추가"):
    st.session_state.expenses.append({
        "date": str(date.today()),
        "category": category,
        "payer": payer,
        "currency": currency,
        "amount": amount,
        "amount_krw": int(amount * rates[currency]),
        "participants": default_participants(category)
    })
    st.rerun()

# --------------------------------------------------
# 지출 리스트 & 삭제
# --------------------------------------------------
st.subheader("📋 지출 내역")

delete_idx = []
for i, e in enumerate(st.session_state.expenses):
    c1, c2 = st.columns([1,9])
    with c1:
        chk = st.checkbox("삭제", key=f"del{i}")
    with c2:
        st.write(f"{e['date']} | {e['category']} | {e['payer']} | {e['amount_krw']:,}원")
    if chk:
        delete_idx.append(i)

if st.button("🗑️ 선택 삭제"):
    st.session_state.expenses = [
        e for i, e in enumerate(st.session_state.expenses) if i not in delete_idx
    ]
    st.rerun()

# --------------------------------------------------
# 여행 저장 / 불러오기
# --------------------------------------------------
st.subheader("💾 여행 저장 / 불러오기")

st.session_state.trip_name = st.text_input("여행 이름", st.session_state.trip_name)

st.download_button(
    "📥 여행 저장",
    data=save_json({
        "trip_name": st.session_state.trip_name,
        "expenses": st.session_state.expenses
    }),
    file_name=f"{st.session_state.trip_name}_trip.json",
    mime="application/json"
)

uploaded_trip = st.file_uploader("📂 여행 불러오기", type=["json"], key="trip")
if uploaded_trip:
    data = json.load(uploaded_trip)
    st.session_state.trip_name = data["trip_name"]
    st.session_state.expenses = data["expenses"]
    st.success("여행 불러오기 완료")

# --------------------------------------------------
# 정산 결과
# --------------------------------------------------
st.subheader("💸 정산 결과")

transfers = calculate_settlement(
    st.session_state.expenses,
    participants
)

for t in transfers:
    st.write(f"👉 {t['from']} → {t['to']} : {t['amount']:,}원")

# --------------------------------------------------
# PDF
# --------------------------------------------------
st.subheader("📄 PDF 리포트")

pdf = generate_pdf(
    st.session_state.trip_name,
    st.session_state.expenses,
    transfers
)

st.download_button(
    "📥 PDF 다운로드",
    data=pdf,
    file_name="travel_settlement.pdf",
    mime="application/pdf"
)
