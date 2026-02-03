import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO
import json
from collections import defaultdict

# -------------------------------
# 기본 설정
# -------------------------------
st.set_page_config(page_title="여행 공동경비 정산", layout="wide")

# -------------------------------
# Session State
# -------------------------------
st.session_state.setdefault("trip_name", "여행_정산")
st.session_state.setdefault("participants", [])
st.session_state.setdefault("expenses", [])

# -------------------------------
# 유틸: JSON 저장/불러오기
# -------------------------------
def to_json_bytes(data: dict) -> BytesIO:
    buf = BytesIO()
    buf.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    buf.seek(0)
    return buf

def safe_load_json(uploaded_file) -> dict:
    return json.load(uploaded_file)

# -------------------------------
# 유틸: 엑셀 생성
# -------------------------------
def make_excel(expenses_df: pd.DataFrame, summary_df: pd.DataFrame, transfers_df: pd.DataFrame) -> BytesIO:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        expenses_df.to_excel(writer, index=False, sheet_name="지출내역")
        summary_df.to_excel(writer, index=False, sheet_name="정산결과")
        transfers_df.to_excel(writer, index=False, sheet_name="송금안내")
    buf.seek(0)
    return buf

# -------------------------------
# 정산 계산(정확한 원단위 분배)
# -------------------------------
def split_amount_exact(amount: int, people: list[str]) -> dict[str, int]:
    """
    amount를 people에게 원 단위로 정확히 분배.
    나머지는 people 순서대로 1원씩 더함.
    """
    n = len(people)
    if n <= 0:
        return {}
    base = amount // n
    rem = amount % n
    shares = {p: base for p in people}
    for i in range(rem):
        shares[people[i]] += 1
    return shares

def compute_settlement(participants: list[str], expenses: list[dict]) -> tuple[pd.DataFrame, list[dict], pd.DataFrame]:
    """
    return:
      - summary_df: 이름/낸 금액/부담금/차액
      - transfers(list of dict): from,to,amount
      - transfers_df
    """
    paid = defaultdict(int)   # 결제자가 낸 돈 합
    owed = defaultdict(int)   # 각자 부담금 합(정확한 분배)

    for e in expenses:
        amt = int(e.get("amount_krw", 0))
        payer = e.get("payer", "")
        ps = e.get("participants", [])
        # 방어: 참여자가 비어있으면 분배 불가 -> 스킵
        if not ps:
            continue

        paid[payer] += amt

        # 분배는 참여자 리스트 순서대로 나머지 1원 배분(정확)
        shares = split_amount_exact(amt, ps)
        for p, s in shares.items():
            owed[p] += s

    rows = []
    for p in participants:
        rows.append({
            "이름": p,
            "낸 금액": int(paid[p]),
            "부담금": int(owed[p]),
            "차액(낸-부담)": int(paid[p] - owed[p]),
        })
    summary_df = pd.DataFrame(rows)

    # 송금 안내(최소 송금 횟수에 가까운 greedy)
    senders = []
    receivers = []
    for r in rows:
        diff = r["차액(낸-부담)"]
        if diff < 0:
            senders.append([r["이름"], -diff])  # 보내야 함
        elif diff > 0:
            receivers.append([r["이름"], diff]) # 받아야 함

    transfers = []
    i = j = 0
    while i < len(senders) and j < len(receivers):
        s_name, s_amt = senders[i]
        r_name, r_amt = receivers[j]
        send = min(s_amt, r_amt)
        transfers.append({"보내는 사람": s_name, "받는 사람": r_name, "금액(원)": int(send)})
        senders[i][1] -= send
        receivers[j][1] -= send
        if senders[i][1] == 0:
            i += 1
        if receivers[j][1] == 0:
            j += 1

    transfers_df = pd.DataFrame(transfers) if transfers else pd.DataFrame(columns=["보내는 사람", "받는 사람", "금액(원)"])
    return summary_df, transfers, transfers_df

# -------------------------------
# 타이틀(아이폰 한 줄)
# -------------------------------
st.markdown(
    '<h1 style="font-size:28px; margin-bottom:0.3em;">✈️ 여행 공동경비 정산</h1>',
    unsafe_allow_html=True
)

st.text_input("여행 이름", key="trip_name")

# -------------------------------
# 파일 저장/불러오기 (복구)
# -------------------------------
st.subheader("💾 여행 파일 저장/불러오기")

col_f1, col_f2 = st.columns([1, 1])

with col_f1:
    save_payload = {
        "trip_name": st.session_state.trip_name,
        "participants": st.session_state.participants,
        "expenses": st.session_state.expenses,
    }
    st.download_button(
        "📥 여행 파일 저장 (JSON)",
        data=to_json_bytes(save_payload),
        file_name=f"{st.session_state.trip_name}.json",
        mime="application/json",
        use_container_width=True
    )

with col_f2:
    uploaded = st.file_uploader("📂 여행 파일 불러오기 (JSON)", type=["json"])
    if uploaded is not None:
        data = safe_load_json(uploaded)
        st.session_state.trip_name = data.get("trip_name", "불러온_여행")
        st.session_state.participants = data.get("participants", [])
        st.session_state.expenses = data.get("expenses", [])
        st.success("마지막 저장 상태로 복원했습니다. 계속 입력하세요 ✅")
        st.rerun()

# -------------------------------
# 참여자
# -------------------------------
st.subheader("👥 참여자 (최대 8명)")

with st.form("add_participant_form", clear_on_submit=True):
    name = st.text_input("이름 입력 후 Enter", placeholder="예: 엄마, 아빠, 민수")
    submitted = st.form_submit_button("추가")
    if submitted and name:
        if name not in st.session_state.participants:
            if len(st.session_state.participants) >= 8:
                st.warning("최대 8명까지 가능합니다.")
            else:
                st.session_state.participants.append(name)
        st.rerun()

if st.session_state.participants:
    st.write("현재 참여자:", ", ".join(st.session_state.participants))
else:
    st.info("참여자를 먼저 추가해 주세요.")

# 참여자가 없으면 아래 입력/정산은 중단(모바일 로딩 안정)
if not st.session_state.participants:
    st.stop()

# -------------------------------
# 환율(지금은 간단 버전: 입력 가능)
# -------------------------------
st.subheader("💱 환율 (통화 → KRW)")
c1, c2, c3, c4 = st.columns(4)
with c1:
    rate_KRW = st.number_input("KRW", value=1.0, step=1.0, disabled=True)
with c2:
    rate_USD = st.number_input("USD", value=1350.0, step=10.0)
with c3:
    rate_JPY = st.number_input("JPY", value=9.2, step=0.1)
with c4:
    rate_EUR = st.number_input("EUR", value=1450.0, step=10.0)

rates = {"KRW": 1.0, "USD": float(rate_USD), "JPY": float(rate_JPY), "EUR": float(rate_EUR)}
categories = ["숙박", "식사", "카페", "교통", "쇼핑", "액티비티", "기타"]

# -------------------------------
# 지출 입력 (Enter로 저장)
# -------------------------------
st.subheader("🧾 지출 입력")

with st.form("expense_form", clear_on_submit=True):
    a, b, c = st.columns(3)

    with a:
        e_date = st.date_input("날짜", value=date.today())
        category = st.selectbox("항목", categories)

    with b:
        payer = st.selectbox("결제자", st.session_state.participants)
        currency = st.selectbox("통화", list(rates.keys()))

    with c:
        amount = st.number_input("금액 (Enter로 저장)", min_value=0, step=1000)
        memo = st.text_input("메모(선택)")

    participants_selected = st.multiselect(
        "참여자 (이 지출에 포함되는 사람)",
        st.session_state.participants,
        default=st.session_state.participants
    )

    save = st.form_submit_button("저장")

    if save:
        if not participants_selected:
            st.warning("참여자를 최소 1명 이상 선택하세요.")
        else:
            amount_krw = int(round(float(amount) * rates[currency]))
            st.session_state.expenses.append({
                "date": str(e_date),
                "category": category,
                "payer": payer,
                "currency": currency,
                "amount": float(amount),
                "amount_krw": amount_krw,
                "participants": participants_selected,
                "memo": memo,
                "created_at": datetime.now().isoformat()
            })
            st.rerun()

# -------------------------------
# 지출 내역 (최신 날짜순 + 체크 삭제)
# -------------------------------
st.subheader("📋 지출 내역 (최근 날짜 순)")

# 최신순 정렬
st.session_state.expenses.sort(key=lambda x: (x.get("date", ""), x.get("created_at", "")), reverse=True)

delete_flags = []
for i, e in enumerate(st.session_state.expenses):
    col1, col2, col3, col4 = st.columns([0.6, 2.4, 2.8, 1.4])

    with col1:
        delete_flags.append(st.checkbox("삭제", key=f"del_{i}", label_visibility="collapsed"))

    with col2:
        st.write(f"📅 {e['date']} | {e['category']}")

    with col3:
        st.write(f"{e['payer']} → {', '.join(e['participants'])}")

    with col4:
        st.write(f"{int(e['amount_krw']):,}원")

if any(delete_flags):
    if st.button("🗑️ 선택 지출 삭제"):
        st.session_state.expenses = [e for idx, e in enumerate(st.session_state.expenses) if not delete_flags[idx]]
        st.rerun()

# -------------------------------
# 정산 결과(복구: 낸금액/부담금/차액) + 송금 안내
# -------------------------------
st.subheader("📊 정산 결과")

summary_df, transfers, transfers_df = compute_settlement(st.session_state.participants, st.session_state.expenses)

st.dataframe(summary_df, use_container_width=True)

st.subheader("💸 누가 누구에게 보내면 될까요?")
if transfers_df.empty:
    st.success("송금할 내역이 없습니다 🎉")
else:
    st.dataframe(transfers_df, use_container_width=True)

# -------------------------------
# 엑셀 다운로드(지출/정산/송금)
# -------------------------------
st.subheader("📥 다운로드")

expenses_df = pd.DataFrame(st.session_state.expenses)
if expenses_df.empty:
    expenses_df = pd.DataFrame(columns=["date","category","payer","currency","amount","amount_krw","participants","memo","created_at"])

st.download_button(
    "📊 엑셀 다운로드 (지출/정산/송금)",
    data=make_excel(expenses_df, summary_df, transfers_df),
    file_name=f"{st.session_state.trip_name}.xlsx",
    use_container_width=True
)
