import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO

st.set_page_config(page_title="여행 공동경비 정산", layout="wide")

# -------------------------------
# Session State
# -------------------------------
if "participants" not in st.session_state:
    st.session_state.participants = []

if "expenses" not in st.session_state:
    st.session_state.expenses = []

if "trip_name" not in st.session_state:
    st.session_state.trip_name = "여행_정산"

rates = {"KRW": 1, "JPY": 9.2, "USD": 1350, "EUR": 1450}
categories = ["숙박", "식사", "카페", "교통", "쇼핑", "액티비티", "기타"]

# -------------------------------
# Excel
# -------------------------------
def make_excel(expenses, summary_df):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(expenses).to_excel(writer, index=False, sheet_name="지출내역")
        summary_df.to_excel(writer, index=False, sheet_name="정산결과")
    buf.seek(0)
    return buf

# -------------------------------
# Title (모바일 한 줄 최적화)
# -------------------------------
st.markdown(
    """
    <h1 style="font-size:28px; margin-bottom:0.3em;">
        ✈️ 여행 공동경비 정산
    </h1>
    """,
    unsafe_allow_html=True
)

st.text_input("여행 이름", key="trip_name")

# -------------------------------
# Participants
# -------------------------------
st.subheader("👥 참여자")

with st.form("add_participant", clear_on_submit=True):
    name = st.text_input("이름 입력 후 Enter")
    submitted = st.form_submit_button("추가")
    if submitted and name:
        if name not in st.session_state.participants:
            st.session_state.participants.append(name)
        st.rerun()

if st.session_state.participants:
    st.write("현재 참여자:", ", ".join(st.session_state.participants))
else:
    st.info("참여자를 먼저 추가해 주세요.")
    st.stop()

# -------------------------------
# Expense Input
# -------------------------------
st.subheader("🧾 지출 입력")

with st.form("expense_form", clear_on_submit=True):

    c1, c2, c3 = st.columns(3)

    with c1:
        e_date = st.date_input("날짜", value=date.today())
        category = st.selectbox("항목", categories)

    with c2:
        payer = st.selectbox("결제자", st.session_state.participants)
        currency = st.selectbox("통화", list(rates.keys()))

    with c3:
        amount = st.number_input("금액 (Enter로 저장)", min_value=0, step=1000)
        memo = st.text_input("메모")

    participants_selected = st.multiselect(
        "참여자 (이 지출에 포함되는 사람)",
        st.session_state.participants,
        default=st.session_state.participants
    )

    save = st.form_submit_button("저장")

    if save:
        st.session_state.expenses.append({
            "date": str(e_date),
            "category": category,
            "payer": payer,
            "currency": currency,
            "amount": amount,
            "amount_krw": int(amount * rates[currency]),
            "participants": participants_selected,
            "memo": memo,
            "created_at": datetime.now().isoformat()
        })
        st.rerun()

# -------------------------------
# Expense List
# -------------------------------
st.subheader("📋 지출 내역")

st.session_state.expenses.sort(
    key=lambda x: (x["date"], x["created_at"]),
    reverse=True
)

delete_flags = []

for i, e in enumerate(st.session_state.expenses):
    c1, c2, c3, c4 = st.columns([0.5, 2.5, 2.5, 1.5])

    with c1:
        delete_flags.append(
            st.checkbox("삭제", key=f"del_{i}", label_visibility="collapsed")
        )
    with c2:
        st.write(f"{e['date']} | {e['category']}")
    with c3:
        st.write(f"{e['payer']} → {', '.join(e['participants'])}")
    with c4:
        st.write(f"{e['amount_krw']:,} 원")

if any(delete_flags):
    if st.button("🗑️ 선택 지출 삭제"):
        st.session_state.expenses = [
            e for i, e in enumerate(st.session_state.expenses)
            if not delete_flags[i]
        ]
        st.rerun()

# -------------------------------
# Settlement
# -------------------------------
st.subheader("📊 정산 결과")

balances = {p: 0 for p in st.session_state.participants}

for e in st.session_state.expenses:
    share = e["amount_krw"] / len(e["participants"])
    for p in e["participants"]:
        balances[p] -= share
    balances[e["payer"]] += e["amount_krw"]

df = pd.DataFrame(
    [{"이름": k, "정산금액": int(v)} for k, v in balances.items()]
)

st.dataframe(df, use_container_width=True)

# -------------------------------
# Transfer Guide
# -------------------------------
st.subheader("💸 누가 누구에게 보내면 될까요?")

senders = {k: -v for k, v in balances.items() if v < 0}
receivers = {k: v for k, v in balances.items() if v > 0}

for s, s_amt in senders.items():
    for r, r_amt in receivers.items():
        if s_amt == 0:
            break
        send = min(s_amt, r_amt)
        if send > 0:
            st.write(f"{s} ➜ {r} : {int(send):,}원")
            senders[s] -= send
            receivers[r] -= send

# -------------------------------
# Download
# -------------------------------
st.download_button(
    "📊 엑셀 다운로드",
    make_excel(st.session_state.expenses, df),
    file_name=f"{st.session_state.trip_name}.xlsx"
)
