import streamlit as st
import pandas as pd
from datetime import date, datetime
import json
import uuid
from collections import defaultdict
from io import BytesIO
import re

# ===============================
# 기본 설정
# ===============================
st.set_page_config(page_title="여행 공동경비 정산", layout="wide")

# ===============================
# Session State 초기화
# ===============================
def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default

ss("trip_name", "여행 공동경비 정산")
ss("participants", [])
ss("expenses", [])
ss("editing_id", None)
ss("rates", {"KRW": 1.0, "USD": 1350.0})

# 입력폼 상태
ss("ui_payer", "")
ss("ui_payer_only", False)
ss("ui_payer_not_owed", False)
ss("ui_beneficiary", "")

# ===============================
# 유틸
# ===============================
def parse_amount(txt):
    if not txt:
        raise ValueError("금액 입력 필요")
    txt = txt.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", txt):
        raise ValueError("숫자만 입력")
    v = float(txt)
    if v <= 0:
        raise ValueError("0보다 커야 함")
    return v

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
    return pd.DataFrame(rows)

# ===============================
# 사이드바 (설정)
# ===============================
with st.sidebar:
    st.header("⚙️ 설정")

    st.subheader("여행 파일")
    up = st.file_uploader("불러오기", type="json")
    if up:
        data = json.load(up)
        st.session_state.trip_name = data["trip_name"]
        st.session_state.participants = data["participants"]
        st.session_state.expenses = data["expenses"]
        ensure_ids()
        st.rerun()

    save_data = {
        "trip_name": st.session_state.trip_name,
        "participants": st.session_state.participants,
        "expenses": st.session_state.expenses
    }
    st.download_button(
        "저장",
        data=json.dumps(save_data, ensure_ascii=False, indent=2),
        file_name=f"{st.session_state.trip_name}.json",
        mime="application/json"
    )

    st.subheader("참여자")
    new_p = st.text_input("이름 추가")
    if st.button("추가") and new_p:
        if new_p not in st.session_state.participants:
            st.session_state.participants.append(new_p)
            st.rerun()

    st.write(", ".join(st.session_state.participants))

# ===============================
# 메인
# ===============================
st.markdown(
    "<h1 style='color:#C97A2B;'>여행 공동경비 정산</h1>",
    unsafe_allow_html=True
)

st.text_input("여행 이름", key="trip_name")

if not st.session_state.participants:
    st.info("사이드바에서 참여자를 추가하세요")
    st.stop()

ensure_ids()

# ===============================
# 지출 입력 / 수정
# ===============================
st.subheader("🧾 지출 입력")

editing = st.session_state.editing_id is not None
if editing:
    target = next(e for e in st.session_state.expenses if e["id"] == st.session_state.editing_id)
else:
    target = None

payer = st.selectbox(
    "결제자",
    st.session_state.participants,
    index=st.session_state.participants.index(target["payer"]) if editing else 0
)

payer_only = st.checkbox(
    "결제자 전액 부담",
    value=target.get("payer_only", False) if editing else False
)

payer_not_owed = st.checkbox(
    "결제자는 부담 안 함 (대신 내줌)",
    value=bool(target.get("beneficiary")) if editing else False
)

beneficiary = ""
if payer_not_owed:
    candidates = [p for p in st.session_state.participants if p != payer]
    beneficiary = st.selectbox(
        "전액 부담자",
        candidates,
        index=candidates.index(target["beneficiary"]) if editing and target.get("beneficiary") in candidates else 0
    )

col1, col2 = st.columns(2)
with col1:
    e_date = st.date_input("날짜", value=date.fromisoformat(target["date"]) if editing else date.today())
with col2:
    category = st.text_input("항목", value=target["category"] if editing else "")

amount_txt = st.text_input(
    "금액",
    value=str(target["amount"]) if editing else ""
)

participants_sel = st.multiselect(
    "참여자",
    st.session_state.participants,
    default=target["participants"] if editing else st.session_state.participants
)

if st.button("수정 저장" if editing else "추가"):
    try:
        amt = parse_amount(amount_txt)
    except Exception as e:
        st.error(str(e))
        st.stop()

    data = {
        "id": target["id"] if editing else uuid.uuid4().hex,
        "date": str(e_date),
        "category": category,
        "payer": payer,
        "amount": amt,
        "currency": "KRW",
        "amount_krw": int(amt),
        "participants": participants_sel,
        "payer_only": payer_only,
        "beneficiary": beneficiary if payer_not_owed else ""
    }

    if editing:
        idx = next(i for i,e in enumerate(st.session_state.expenses) if e["id"] == target["id"])
        st.session_state.expenses[idx] = data
        st.session_state.editing_id = None
    else:
        st.session_state.expenses.append(data)

    st.rerun()

# ===============================
# 지출 내역
# ===============================
st.subheader("📋 지출 내역")

if st.session_state.expenses:
    rows = []
    for e in st.session_state.expenses:
        rows.append({
            "선택": False,
            "날짜": e["date"],
            "항목": e["category"],
            "금액": f"{e['amount_krw']:,}",
            "결제자": e["payer"],
            "참여자": ", ".join(e["participants"]),
            "비고": "대신부담" if e.get("beneficiary") else ("전액부담" if e.get("payer_only") else "")
        })

    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df,
        hide_index=True,
        column_config={"선택": st.column_config.CheckboxColumn()}
    )

    selected = [i for i,r in enumerate(edited.to_dict("records")) if r["선택"]]

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✏️ 수정"):
            if len(selected) != 1:
                st.warning("하나만 선택")
            else:
                st.session_state.editing_id = st.session_state.expenses[selected[0]]["id"]
                st.rerun()

    with col2:
        if st.button("🗑️ 삭제"):
            if not selected:
                st.warning("선택 필요")
            else:
                for i in sorted(selected, reverse=True):
                    del st.session_state.expenses[i]
                st.rerun()

# ===============================
# 정산
# ===============================
st.subheader("📊 정산 결과")
st.dataframe(compute_settlement(), use_container_width=True)
