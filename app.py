import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date

st.set_page_config(page_title="여행 공동경비 정산", layout="wide")
st.title("✈️ 여행 공동경비 정산")

# ========================
# 참여자
# ========================
st.header("👥 참여자")
participants_input = st.text_input("참여자 이름 (쉼표 구분, 최대 8명)", "A,B,C")
participants = [p.strip() for p in participants_input.split(",") if p.strip()]

if not participants:
    st.stop()

if len(participants) > 8:
    st.error("참여자는 최대 8명까지 가능합니다.")
    st.stop()

# ========================
# 환율
# ========================
st.header("💱 환율")
rates_input = st.text_input("통화:환율 (예: KRW:1, USD:1350)", "KRW:1,USD:1350")

exchange_rates = {}
try:
    for r in rates_input.split(","):
        k, v = r.split(":")
        exchange_rates[k.strip()] = float(v)
except:
    st.error("환율 입력 형식 오류")
    st.stop()

# ========================
# 항목
# ========================
DEFAULT_CATEGORIES = ["숙소", "식당", "교통", "액티비티", "쇼핑", "준비물", "기타"]
if "categories" not in st.session_state:
    st.session_state.categories = DEFAULT_CATEGORIES.copy()

# ========================
# 지출 저장소
# ========================
if "expenses" not in st.session_state:
    st.session_state.expenses = []

# ========================
# 지출 입력
# ========================
st.header("💳 지출 입력")

with st.form("expense_form", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    exp_date = col1.date_input("날짜", date.today())
    category = col2.selectbox("항목", st.session_state.categories)
    new_category = col3.text_input("새 항목 추가")

    col4, col5, col6 = st.columns(3)
    payer = col4.selectbox("결제자", participants)
    currency = col5.selectbox("통화", list(exchange_rates.keys()))
    amount = col6.number_input("금액", min_value=0.0)

    memo = st.text_input("메모")

    st.markdown("**참여자 선택**")
    ps = [p for p in participants if st.checkbox(p, value=True, key=f"ps_{p}")]

    submitted = st.form_submit_button("➕ 추가")

    if submitted and ps:
        if new_category and new_category not in st.session_state.categories:
            st.session_state.categories.append(new_category)
            category = new_category

        st.session_state.expenses.append({
            "date": exp_date.strftime("%Y-%m-%d"),
            "category": category,
            "payer": payer,
            "currency": currency,
            "amount": amount,
            "participants": ps,
            "memo": memo
        })

# ========================
# 지출 목록 + 삭제
# ========================
if st.session_state.expenses:
    st.subheader("📋 지출 목록")

    delete_flags = []

    for idx, e in enumerate(st.session_state.expenses):
        c1, c2, c3, c4, c5, c6 = st.columns([0.5, 1.5, 1, 1, 2, 2])

        delete_flags.append(
            c1.checkbox(
                "삭제 선택",
                key=f"del_{idx}",
                label_visibility="collapsed"
            )
        )
        c2.write(e["date"])
        c3.write(e["category"])
        c4.write(f'{e["amount"]} {e["currency"]}')
        c5.write(e["payer"])
        c6.write(", ".join(e["participants"]))

    col_a, col_b = st.columns(2)

    if col_a.button("🗑️ 선택 삭제"):
        st.session_state.expenses = [
            e for i, e in enumerate(st.session_state.expenses)
            if not delete_flags[i]
        ]
        st.rerun()

    if col_b.button("🗑️ 전체 삭제"):
        st.session_state.expenses = []
        st.rerun()

# ========================
# 정산
# ========================
st.divider()

if st.button("🧮 정산 계산") and st.session_state.expenses:
    paid = {p: 0 for p in participants}
    owed = {p: 0 for p in participants}

    for e in st.session_state.expenses:
        krw = e["amount"] * exchange_rates[e["currency"]]
        share = krw / len(e["participants"])
        paid[e["payer"]] += krw
        for p in e["participants"]:
            owed[p] += share

    df = pd.DataFrame([
        {
            "이름": p,
            "낸 돈": round(paid[p]),
            "부담금": round(owed[p]),
            "차액": round(paid[p] - owed[p])
        } for p in participants
    ])

    st.subheader("📊 정산 결과")
    st.dataframe(df, use_container_width=True)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)

    st.download_button(
        "⬇️ 엑셀 다운로드",
        output.getvalue(),
        "여행_정산.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
