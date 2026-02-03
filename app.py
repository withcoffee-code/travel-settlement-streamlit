import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO

# -------------------------------
# 기본 세팅
# -------------------------------
st.set_page_config(page_title="여행 공동경비 정산", layout="wide")

if "participants" not in st.session_state:
    st.session_state.participants = []

if "expenses" not in st.session_state:
    st.session_state.expenses = []

if "edit_index" not in st.session_state:
    st.session_state.edit_index = None

if "focus_amount" not in st.session_state:
    st.session_state.focus_amount = False

if "trip_name" not in st.session_state:
    st.session_state.trip_name = "여행_정산"

rates = {
    "KRW": 1,
    "JPY": 9.2,
    "USD": 1350,
    "EUR": 1450
}

categories = ["숙박", "식사", "카페", "교통", "쇼핑", "액티비티", "기타"]

# -------------------------------
# 엑셀 생성
# -------------------------------
def make_excel(expenses, summary_df):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(expenses).to_excel(writer, index=False, sheet_name="지출내역")
        summary_df.to_excel(writer, index=False, sheet_name="정산결과")
    buf.seek(0)
    return buf

# -------------------------------
# 제목
# -------------------------------
st.title("✈️ 여행 공동경비 정산")

st.text_input("여행 이름", key="trip_name")

# -------------------------------
# 참여자 관리
# -------------------------------
st.subheader("👥 참여자")

with st.form("add_participant", clear_on_submit=True):
    new_name = st.text_input("이름 입력 후 Enter", placeholder="예: 엄마, 아빠, 민수")
    add_p = st.form_submit_button("추가")

    if add_p and new_name:
        if new_name not in st.session_state.participants:
            st.session_state.participants.append(new_name)
        st.rerun()

if st.session_state.participants:
    st.write("현재 참여자:", ", ".join(st.session_state.participants))

# -------------------------------
# 지출 입력
# -------------------------------
st.subheader("🧾 지출 입력")

if not st.session_state.participants:
    st.info("참여자를 먼저 추가해 주세요.")
    st.stop()

editing = st.session_state.edit_index
base = st.session_state.expenses[editing] if editing is not None else {}

with st.form("expense_form", clear_on_submit=True):

    c1, c2, c3 = st.columns(3)

    with c1:
        e_date = st.date_input(
            "날짜",
            value=date.fromisoformat(base.get("date", str(date.today())))
        )
        category = st.selectbox(
            "항목",
            categories,
            index=categories.index(base.get("category", "숙박")),
            on_change=lambda: setattr(st.session_state, "focus_amount", True)
        )

    with c2:
        payer = st.selectbox(
            "결제자",
            st.session_state.participants,
            index=st.session_state.participants.index(base["payer"])
            if base.get("payer") in st.session_state.participants else 0
        )
        currency = st.selectbox(
            "통화",
            list(rates.keys()),
            index=list(rates.keys()).index(base.get("currency", "KRW"))
        )

    with c3:
        amount = st.number_input(
            "금액 (Enter로 저장)",
            min_value=0,
            step=1000,
            value=int(base.get("amount", 0)),
            autofocus=st.session_state.focus_amount
        )
        memo = st.text_input("메모", base.get("memo", ""))

    participants_selected = st.multiselect(
        "참여자 (이 지출에 포함되는 사람)",
        st.session_state.participants,
        default=base.get("participants", st.session_state.participants)
    )

    submit = st.form_submit_button("저장")

    if submit:
        data = {
            "date": str(e_date),
            "category": category,
            "payer": payer,
            "currency": currency,
            "amount": amount,
            "amount_krw": int(amount * rates[currency]),
            "participants": participants_selected,
            "memo": memo,
            "created_at": datetime.now().isoformat()
        }

        if editing is None:
            st.session_state.expenses.append(data)
        else:
            st.session_state.expenses[editing] = data
            st.session_state.edit_index = None

        st.session_state.focus_amount = False
        st.rerun()

# -------------------------------
# 지출 리스트 (최신순)
# -------------------------------
st.subheader("📋 지출 내역")

st.session_state.expenses.sort(
    key=lambda x: (x["date"], x["created_at"]),
    reverse=True
)

delete_flags = []

for idx, e in enumerate(st.session_state.expenses):
    col1, col2, col3, col4, col5 = st.columns([0.6, 2, 2, 1.5, 1])

    with col1:
        delete_flags.append(
            st.checkbox(
                "삭제",
                key=f"del_{idx}",
                label_visibility="collapsed"
            )
        )

    with col2:
        st.write(f"📅 {e['date']} | {e['category']}")

    with col3:
        st.write(f"{e['payer']} → {', '.join(e['participants'])}")

    with col4:
        st.write(f"{e['amount_krw']:,} 원")

    with col5:
        if st.button("✏️", key=f"edit_{idx}"):
            st.session_state.edit_index = idx
            st.rerun()

if any(delete_flags):
    if st.button("🗑️ 선택 지출 삭제"):
        st.session_state.expenses = [
            e for i, e in enumerate(st.session_state.expenses)
            if not delete_flags[i]
        ]
        st.rerun()

# -------------------------------
# 정산 계산
# -------------------------------
st.subheader("📊 정산 결과")

balances = {p: 0 for p in st.session_state.participants}

for e in st.session_state.expenses:
    share = e["amount_krw"] / len(e["participants"])
    for p in e["participants"]:
        balances[p] -= share
    balances[e["payer"]] += e["amount_krw"]

df_summary = pd.DataFrame(
    [{"이름": k, "정산금액": int(v)} for k, v in balances.items()]
)

st.dataframe(df_summary, use_container_width=True)

# -------------------------------
# 송금 가이드
# -------------------------------
st.subheader("💸 누가 누구에게 보내면 될까요?")

senders = {k: -v for k, v in balances.items() if v < 0}
receivers = {k: v for k, v in balances.items() if v > 0}

result = []

for s, s_amt in senders.items():
    for r, r_amt in receivers.items():
        if s_amt == 0:
            break
        send = min(s_amt, r_amt)
        if send > 0:
            result.append(f"{s} ➜ {r} : {int(send):,}원")
            senders[s] -= send
            receivers[r] -= send

if result:
    for r in result:
        st.write(r)
else:
    st.success("이미 정산 완료되었습니다 🎉")

# -------------------------------
# 엑셀 다운로드
# -------------------------------
st.download_button(
    "📊 엑셀 다운로드",
    make_excel(st.session_state.expenses, df_summary),
    file_name=f"{st.session_state.trip_name}.xlsx"
)
