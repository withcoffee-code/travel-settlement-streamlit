import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="여행 공동경비 정산", layout="wide")

st.title("✈️ 여행 공동경비 정산 (Streamlit)")

# ------------------------
# 참여자 입력
# ------------------------
st.header("👥 참여자")
participants = st.text_input(
    "참여자 이름 (쉼표로 구분, 최대 8명)",
    "A,B,C"
).split(",")

participants = [p.strip() for p in participants if p.strip()]

# ------------------------
# 환율 입력
# ------------------------
st.header("💱 환율")
rates_input = st.text_input(
    "통화:환율 형식 (예: KRW:1,USD:1350,JPY:9.1)",
    "KRW:1,USD:1350"
)

exchange_rates = {}
for r in rates_input.split(","):
    k, v = r.split(":")
    exchange_rates[k.strip()] = float(v)

# ------------------------
# 지출 입력
# ------------------------
st.header("💳 지출 내역")

st.markdown(
"""
형식:  
`날짜 | 항목 | 결제자 | 통화 | 금액 | 참여자(|로 구분) | 메모`
"""
)

raw_expenses = st.text_area(
    "지출 입력",
    value="2026-03-01 | 식당 | A | USD | 120 | A|B | 저녁식사",
    height=150
)

expenses = []
if raw_expenses:
    for line in raw_expenses.split("\n"):
        date, cat, payer, cur, amt, ps, memo = [x.strip() for x in line.split("|")]
        expenses.append({
            "date": date,
            "category": cat,
            "payer": payer,
            "currency": cur,
            "amount": float(amt),
            "participants": ps.split("|"),
            "memo": memo
        })

# ------------------------
# 정산 계산
# ------------------------
if st.button("🧮 정산 계산"):
    paid = {p: 0 for p in participants}
    owed = {p: 0 for p in participants}

    expense_rows = []

    for e in expenses:
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

    summary = []
    for p in participants:
        summary.append({
            "이름": p,
            "낸 돈": round(paid[p]),
            "부담금": round(owed[p]),
            "차액": round(paid[p] - owed[p])
        })

    summary_df = pd.DataFrame(summary)

    st.subheader("📊 정산 요약")
    st.dataframe(summary_df)

    # ------------------------
    # 송금 계산
    # ------------------------
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
    st.dataframe(pd.DataFrame(transfers))

    # ------------------------
    # 엑셀 다운로드
    # ------------------------
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(expense_rows).to_excel(writer, index=False, sheet_name="지출내역")
        summary_df.to_excel(writer, index=False, sheet_name="정산요약")
        pd.DataFrame(transfers).to_excel(writer, index=False, sheet_name="송금안내")

    st.download_button(
        "⬇️ 엑셀 다운로드",
        data=output.getvalue(),
        file_name="여행_공동경비_정산.xlsx"
    )
