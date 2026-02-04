# ⚠️ 이 버전은 “지출내역 먼저” 요청 시점으로 복구한 안정판입니다
# 다른 UI 실험(접기/하이라이트/그래프)은 전부 제거했습니다

import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO
import json
from collections import defaultdict
import re
import uuid

st.set_page_config(page_title="여행 공동경비 정산", layout="wide")

# ===============================
# Session State
# ===============================
def ss(k, v):
    if k not in st.session_state:
        st.session_state[k] = v

ss("trip_name", "여행_정산")
ss("participants", [])
ss("expenses", [])
ss("editing_id", None)
ss("rates", {"KRW": 1.0, "USD": 1350.0})

# ===============================
# Utils
# ===============================
def parse_amount(txt):
    txt = txt.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", txt):
        raise ValueError("금액은 숫자만 입력하세요")
    return float(txt)

def ensure_ids():
    for e in st.session_state.expenses:
        if "id" not in e:
            e["id"] = uuid.uuid4().hex

def compute_settlement():
    paid = defaultdict(int)
    owed = defaultdict(int)

    for e in st.session_state.expenses:
        amt = e["amount_krw"]
        payer = e["payer"]

        if e.get("beneficiary"):
            targets = [e["beneficiary"]]
        elif e.get("payer_only"):
            targets = [payer]
        else:
            targets = e["participants"]

        paid[payer] += amt
        share = amt // len(targets)
        for t in targets:
            owed[t] += share

    rows = []
    for p in st.session_state.participants:
        rows.append({
            "이름": p,
            "낸 금액": paid[p],
            "부담금": owed[p],
            "차액": paid[p] - owed[p]
        })

    df = pd.DataFrame(rows)

    senders, receivers = [], []
    for _, r in df.iterrows():
        if r["차액"] < 0:
            senders.append([r["이름"], -r["차액"]])
        elif r["차액"] > 0:
            receivers.append([r["이름"], r["차액"]])

    transfers = []
    i = j = 0
    while i < len(senders) and j < len(receivers):
        amt = min(senders[i][1], receivers[j][1])
        transfers.append({
            "보내는 사람": senders[i][0],
            "받는 사람": receivers[j][0],
            "금액(원)": amt
        })
        senders[i][1] -= amt
        receivers[j][1] -= amt
        if senders[i][1] == 0: i += 1
        if receivers[j][1] == 0: j += 1

    return df, pd.DataFrame(transfers)

# ===============================
# Sidebar
# ===============================
with st.sidebar:
    st.header("⚙️ 설정")

    uploaded = st.file_uploader("여행 파일 불러오기 (JSON)", type="json")
    if uploaded:
        data = json.load(uploaded)
        st.session_state.trip_name = data["trip_name"]
        st.session_state.participants = data["participants"]
        st.session_state.expenses = data["expenses"]
        ensure_ids()
        st.rerun()

    payload = {
        "trip_name": st.session_state.trip_name,
        "participants": st.session_state.participants,
        "expenses": st.session_state.expenses
    }
    st.download_button(
        "💾 여행 파일 저장",
        json.dumps(payload, ensure_ascii=False, indent=2),
        file_name=f"{st.session_state.trip_name}.json",
        mime="application/json"
    )

    st.divider()
    st.subheader("참여자")
    name = st.text_input("이름 추가")
    if st.button("추가") and name:
        if name not in st.session_state.participants:
            st.session_state.participants.append(name)
            st.rerun()

# ===============================
# Main
# ===============================
st.title("여행 공동경비 정산")
st.text_input("여행 이름", key="trip_name")

if not st.session_state.participants:
    st.info("사이드바에서 참여자를 추가하거나 파일을 불러오세요")
    st.stop()

ensure_ids()

# =================================================
# 📋 지출 내역 (⬆️ 먼저 보임)
# =================================================
st.subheader("📋 지출 내역")

if st.session_state.expenses:
    rows = []
    for e in st.session_state.expenses:
        rows.append({
            "날짜": e["date"],
            "항목": e["category"],
            "금액(원)": f"{e['amount_krw']:,}",
            "결제자": e["payer"],
            "참여자": ", ".join(e["participants"])
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True)
else:
    st.info("지출 내역이 없습니다")

# =================================================
# 🧾 지출 입력 (⬇️ 아래)
# =================================================
st.subheader("🧾 지출 입력")

payer = st.selectbox("결제자", st.session_state.participants)
date_val = st.date_input("날짜", value=date.today())
category = st.selectbox("항목", ["숙박", "식사", "교통", "쇼핑", "기타"])
amount_txt = st.text_input("금액")
participants_sel = st.multiselect(
    "참여자",
    st.session_state.participants,
    default=st.session_state.participants
)

if st.button("추가"):
    try:
        amt = parse_amount(amount_txt)
    except Exception as e:
        st.error(str(e))
        st.stop()

    st.session_state.expenses.append({
        "id": uuid.uuid4().hex,
        "date": str(date_val),
        "category": category,
        "payer": payer,
        "amount": amt,
        "currency": "KRW",
        "amount_krw": int(amt),
        "participants": participants_sel,
        "payer_only": False,
        "beneficiary": ""
    })
    st.rerun()

# =================================================
# 📊 정산 결과
# =================================================
st.subheader("📊 정산 결과")
summary_df, transfer_df = compute_settlement()

show = summary_df.copy()
for c in ["낸 금액", "부담금", "차액"]:
    show[c] = show[c].apply(lambda x: f"{int(x):,}")
st.dataframe(show, use_container_width=True)

st.subheader("💸 송금 안내")
if transfer_df.empty:
    st.success("송금할 내역이 없습니다 🎉")
else:
    transfer_df["금액(원)"] = transfer_df["금액(원)"].apply(lambda x: f"{int(x):,}")
    st.dataframe(transfer_df, use_container_width=True)
