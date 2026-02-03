import streamlit as st
from datetime import date
import json
from io import BytesIO
from collections import defaultdict
import pandas as pd

# --------------------------------------------------
# 기본 설정
# --------------------------------------------------
st.set_page_config(page_title="여행 경비 정산", page_icon="💸", layout="wide")

st.session_state.setdefault("trip_name", "새 여행")
st.session_state.setdefault("participants", [])
st.session_state.setdefault("expenses", [])
st.session_state.setdefault("edit_index", None)

# --------------------------------------------------
# 유틸 함수
# --------------------------------------------------
def save_json(data):
    buf = BytesIO()
    buf.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    buf.seek(0)
    return buf

def make_excel(expenses, summary_df):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        pd.DataFrame(expenses).to_excel(writer, index=False, sheet_name="지출내역")
        summary_df.to_excel(writer, index=False, sheet_name="정산결과")
    buf.seek(0)
    return buf

# --------------------------------------------------
# 타이틀
# --------------------------------------------------
st.title("💸 여행 경비 정산")
st.session_state.trip_name = st.text_input("여행 이름", st.session_state.trip_name)

# --------------------------------------------------
# 참여자 관리
# --------------------------------------------------
st.subheader("👥 여행 참여자")

col_p1, col_p2 = st.columns([3,1])
with col_p1:
    new_name = st.text_input("이름 입력 후 Enter", key="new_participant")
with col_p2:
    if st.button("추가") and new_name:
        if new_name not in st.session_state.participants:
            st.session_state.participants.append(new_name)
            st.session_state.new_participant = ""
            st.rerun()

if st.session_state.participants:
    st.write("참여자:", ", ".join(st.session_state.participants))

# --------------------------------------------------
# 환율
# --------------------------------------------------
st.subheader("💱 환율 (KRW 기준)")
rates = {
    "KRW": 1.0,
    "USD": st.number_input("USD → KRW", 1350.0),
    "JPY": st.number_input("JPY → KRW", 9.0),
    "EUR": st.number_input("EUR → KRW", 1450.0),
}

# --------------------------------------------------
# 지출 입력 / 수정
# --------------------------------------------------
st.subheader("🧾 지출 입력")

editing = st.session_state.edit_index
base = st.session_state.expenses[editing] if editing is not None else {}

col1, col2, col3 = st.columns(3)

with col1:
    e_date = st.date_input(
        "날짜",
        value=date.fromisoformat(base.get("date", str(date.today())))
    )
    category = st.selectbox(
        "항목",
        ["숙박", "식사", "카페", "교통", "쇼핑", "액티비티", "기타"],
        index=["숙박","식사","카페","교통","쇼핑","액티비티","기타"].index(
            base.get("category", "숙박")
        )
    )

with col2:
    payer = st.selectbox(
        "결제자",
        st.session_state.participants,
        index=st.session_state.participants.index(base["payer"])
        if editing is not None and base.get("payer") in st.session_state.participants else 0
    )
    currency = st.selectbox("통화", list(rates.keys()))

with col3:
    amount = st.number_input(
        "금액",
        min_value=0,
        value=int(base.get("amount", 0))
    )
    memo = st.text_input("메모", base.get("memo", ""))

participants_selected = st.multiselect(
    "참여자 (이 지출에 포함되는 사람)",
    st.session_state.participants,
    default=base.get("participants", st.session_state.participants)
)

if st.button("저장"):
    data = {
        "date": str(e_date),
        "category": category,
        "payer": payer,
        "currency": currency,
        "amount": amount,
        "amount_krw": int(amount * rates[currency]),
        "participants": participants_selected,
        "memo": memo
    }
    if editing is None:
        st.session_state.expenses.append(data)
    else:
        st.session_state.expenses[editing] = data
        st.session_state.edit_index = None
    st.rerun()

# --------------------------------------------------
# 지출 내역 리스트
# --------------------------------------------------
st.subheader("📋 지출 내역")

if not st.session_state.expenses:
    st.info("아직 지출이 없습니다.")
else:
    for i, e in enumerate(st.session_state.expenses):
        col_a, col_b, col_c, col_d = st.columns([2,4,3,1])
        col_a.write(e["date"])
        col_b.write(f"{e['category']} | {e['payer']}")
        col_c.write(f"{e['amount_krw']:,}원 ({e['currency']})")
        if col_d.button("✏️ 수정", key=f"edit_{i}"):
            st.session_state.edit_index = i
            st.rerun()

# --------------------------------------------------
# 정산 계산
# --------------------------------------------------
st.subheader("📊 정산 결과")

paid = defaultdict(int)
owed = defaultdict(int)

for e in st.session_state.expenses:
    paid[e["payer"]] += e["amount_krw"]
    if e["participants"]:
        share = e["amount_krw"] / len(e["participants"])
        for p in e["participants"]:
            owed[p] += share

summary = []
for p in st.session_state.participants:
    summary.append({
        "이름": p,
        "낸 금액": paid[p],
        "써야 할 금액": int(owed[p]),
        "차액": int(paid[p] - owed[p])
    })

df_summary = pd.DataFrame(summary)
st.dataframe(df_summary, use_container_width=True)

# --------------------------------------------------
# 송금 가이드
# --------------------------------------------------
st.subheader("💸 누가 누구에게 보내면 될까요")

senders = [[r["이름"], -r["차액"]] for r in summary if r["차액"] < 0]
receivers = [[r["이름"], r["차액"]] for r in summary if r["차액"] > 0]

i = j = 0
if not senders and not receivers:
    st.success("정산 완료! 송금할 내역이 없습니다 🎉")
else:
    while i < len(senders) and j < len(receivers):
        amt = min(senders[i][1], receivers[j][1])
        st.write(f"👉 {senders[i][0]} → {receivers[j][0]} : {amt:,.0f}원")
        senders[i][1] -= amt
        receivers[j][1] -= amt
        if senders[i][1] == 0:
            i += 1
        if receivers[j][1] == 0:
            j += 1

# --------------------------------------------------
# 항목별 차트
# --------------------------------------------------
st.subheader("📈 항목별 지출 합계")

df_exp = pd.DataFrame(st.session_state.expenses)
if not df_exp.empty:
    chart = df_exp.groupby("category")["amount_krw"].sum()
    st.bar_chart(chart)

# --------------------------------------------------
# 저장 / 불러오기 / 엑셀
# --------------------------------------------------
st.subheader("💾 저장 & 불러오기")

st.download_button(
    "📥 여행 상태 저장 (JSON)",
    save_json({
        "trip_name": st.session_state.trip_name,
        "participants": st.session_state.participants,
        "expenses": st.session_state.expenses
    }),
    file_name=f"{st.session_state.trip_name}.json"
)

st.download_button(
    "📊 엑셀 다운로드",
    make_excel(st.session_state.expenses, df_summary),
    file_name=f"{st.session_state.trip_name}.xlsx"
)

uploaded = st.file_uploader("📂 저장된 여행 불러오기", type="json")
if uploaded:
    data = json.load(uploaded)
    st.session_state.trip_name = data["trip_name"]
    st.session_state.participants = data["participants"]
    st.session_state.expenses = data["expenses"]
    st.session_state.edit_index = None
    st.rerun()
