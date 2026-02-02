import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import date

# ========================
# 기본 설정
# ========================
st.set_page_config(
    page_title="여행 공동경비 정산",
    layout="wide"
)

st.title("✈️ 여행 공동경비 정산 (Streamlit)")

# ========================
# 참여자 입력
# ========================
st.header("👥 참여자")

participants_input = st.text_input(
    "참여자 이름 (쉼표로 구분, 최대 8명)",
    "A,B,C"
)

participants = [p.strip() for p in participants_input.split(",") if p.strip()]

if not participants:
    st.warning("참여자를 1명 이상 입력하세요.")
    st.stop()

if len(participants) > 8:
    st.error("참여자는 최대 8명까지 가능합니다.")
    st.stop()

# ========================
# 환율 입력
# ========================
st.header("💱 환율")

rates_input = st.text_input(
    "통화:환율 형식 (예: KRW:1, USD:1350, JPY:9.1)",
    "KRW:1,USD:1350"
)

exchange_rates = {}
try:
    for r in rates_input.split(","):
        k, v = r.split(":")
        exchange_rates[k.strip()] = float(v)
except Exception:
    st.error("환율 입력 형식이 잘못되었습니다.")
    st.stop()

# ========================
# 지출 입력 (폼 UI)
# ========================
st.header("💳 지출 내역 입력")

if "expenses" not in st.session_state:
    st.session_state.expenses = []

with st.form("expense_form", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    exp_date = col1.date_input("날짜", value=date.today())
    category = col2.text_input("항목 (예: 숙소, 식당)")
    payer = col3.selectbox("결제자", participants)

    col4, col5, col6 = st.columns(3)
    currency = col4.selectbox("통화", list(exchange_rates.keys()))
    amount = col5.number_input("금액", min_value=0.0, step=1.0)
    memo = col6.text_input("메모 (선택)")

    st.markdown("**참여자 선택**")
    participant_checks = {
        p: st.checkbox(p, value=True)
        for p in participants
    }

    submitted = st.form_submit_button("➕ 지출 추가")

    if submitted:
        selected_participants = [p for p, v in participant_checks.items() if v]

        if not category:
            st.warning("항목을 입력하세요.")
        elif not selected_participants:
            st.warning("참여자를 최소 1명 선택하세요.")
        else:
            st.session_state.expenses.append({
                "date": exp_date.strftime("%Y-%m-%d"),
                "category": category,
                "payer": payer,
                "currency": currency,
                "amount": amount,
                "participants": selected_participants,
                "memo": memo
            })

# ========================
# 입력된 지출 목록 표시
# ========================
if st.session_state.expenses:
    st.subheader("📋 입력된 지출 내역")

    df_preview = pd.DataFrame([
        {
            "날짜": e["date"],
            "항목": e["category"],
            "결제자": e["payer"],
            "금액": f'{e["amount"]} {e["currency"]}',
            "참여자": ", ".join(e["participants"]),
            "메모": e["memo"]
        }
        for e in st.session_state.expenses
    ])

    st.dataframe(df_preview, use_container_width=True)

    if st.button("🗑️ 지출 전체 삭제"):
        st.session_state.expenses = []
        st.experimental_rerun()

# ========================
# 정산 계산
# ========================
st.divider()

if st.button("🧮 정산 계산"):
    if not st.session_state.expenses:
        st.warning("지출 내역을 먼저 입력하세요.")
        st.stop()

    paid = {p: 0 for p in participants}
    owed = {p: 0 for p in participants}
    expense_rows = []

    for e in st.session_state.expenses:
        krw = e["amount"] * exchange_rates[e["currency"]]
        share = krw / len(e["participants"])

        paid[e["payer"]] += krw
        for p in e["participants"]:
            owed[p] += share

        expense_rows.append({
            "날짜": e["date"],
            "항목": e["category"],
            "내용": e["memo"],
            "결제자": e["payer"],
            "통화": e["currency"],
            "외화금액": e["amount"],
            "원화금액": round(krw),
            "참여자": ", ".join(e["participants"])
        })

    summary_rows = []
    for p in participants:
        summary_rows.append({
            "이름": p,
            "낸 돈": round(paid[p]),
            "부담금": round(owed[p]),
            "차액": round(paid[p] - owed[p])
        })

    summary_df = pd.DataFrame(summary_rows)

    st.subheader("📊 정산 요약")
    st.dataframe(summary_df, use_container_width=True)

    # ========================
    # 송금 계산
    # ========================
    transfers = []

    givers = [(p, -(paid[p] - owed[p])) for p in participants if paid[p] - owed[p] < 0]
    takers = [(p, paid[p] - owed[p]) for p in participants if paid[p] - owed[p] > 0]

    gi = ti = 0
    while gi < len(givers) and ti < len(takers):
        g_name, g_amt = givers[gi]
        t_name, t_amt = takers[ti]

        amt = min(g_amt, t_amt)

        transfers.append({
            "보내는 사람": g_name,
            "받는 사람": t_name,
            "금액": round(amt)
        })

        givers[gi] = (g_name, g_amt - amt)
        takers[ti] = (t_name, t_amt - amt)

        if givers[gi][1] == 0:
            gi += 1
        if takers[ti][1] == 0:
            ti += 1

    st.subheader("💸 송금 안내")
    if transfers:
        st.dataframe(pd.DataFrame(transfers), use_container_width=True)
    else:
        st.info("송금할 내역이 없습니다.")

    # ========================
    # 엑셀 다운로드
    # ========================
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(expense_rows).to_excel(writer, index=False, sheet_name="지출내역")
        summary_df.to_excel(writer, index=False, sheet_name="정산요약")
        pd.DataFrame(transfers).to_excel(writer, index=False, sheet_name="송금안내")

    st.download_button(
        "⬇️ 엑셀 다운로드",
        data=output.getvalue(),
        file_name="여행_공동경비_정산.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
