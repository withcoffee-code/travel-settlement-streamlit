import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO
import json
from collections import defaultdict
import hashlib
import re

# -------------------------------
# 기본 설정
# -------------------------------
st.set_page_config(page_title="여행 공동경비 정산", layout="wide")

# -------------------------------
# Session State 초기화
# -------------------------------
st.session_state.setdefault("trip_name_ui", "여행_정산")
st.session_state.setdefault("participants", [])
st.session_state.setdefault("expenses", [])
st.session_state.setdefault("last_loaded_sig", None)

# -------------------------------
# UI: 소제목 폰트 50% (bold 유지)
# -------------------------------
st.markdown(
    """
    <style>
      [data-testid="stMarkdownContainer"] h2 {
        font-size: 1.05rem !important;
        font-weight: 700 !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------------
# 유틸: JSON/Excel
# -------------------------------
def to_json_bytes(data: dict) -> BytesIO:
    buf = BytesIO()
    buf.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    buf.seek(0)
    return buf

def make_excel(expenses_df: pd.DataFrame, summary_df: pd.DataFrame, transfers_df: pd.DataFrame) -> BytesIO:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        expenses_df.to_excel(writer, index=False, sheet_name="지출내역")
        summary_df.to_excel(writer, index=False, sheet_name="정산결과")
        transfers_df.to_excel(writer, index=False, sheet_name="송금안내")
    buf.seek(0)
    return buf

# -------------------------------
# 정산 계산(원 단위 정확 분배)
# -------------------------------
def split_amount_exact(amount: int, people: list[str]) -> dict[str, int]:
    n = len(people)
    if n <= 0:
        return {}
    base = amount // n
    rem = amount % n
    shares = {p: base for p in people}
    for i in range(rem):
        shares[people[i]] += 1
    return shares

def compute_settlement(participants: list[str], expenses: list[dict]):
    paid = defaultdict(int)
    owed = defaultdict(int)

    for e in expenses:
        amt = int(e.get("amount_krw", 0))
        payer = e.get("payer", "")
        ps = e.get("participants", [])
        if not ps:
            continue

        paid[payer] += amt
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

    senders = []
    receivers = []
    for r in rows:
        diff = r["차액(낸-부담)"]
        if diff < 0:
            senders.append([r["이름"], -diff])
        elif diff > 0:
            receivers.append([r["이름"], diff])

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
    return summary_df, transfers_df

# -------------------------------
# 금액 입력 파서
# -------------------------------
def parse_amount_text(s: str) -> float:
    if s is None:
        return 0.0
    s = s.strip()
    if s == "":
        return 0.0
    s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise ValueError("금액은 숫자만 입력해 주세요. (예: 12,000 또는 12000)")
    return float(s)

# -------------------------------
# 타이틀(아이폰 한 줄)
# -------------------------------
st.markdown(
    '<h1 style="font-size:28px; margin-bottom:0.3em; font-weight:800;">✈️ 여행 공동경비 정산</h1>',
    unsafe_allow_html=True
)

# -------------------------------
# 파일 저장/불러오기
# -------------------------------
st.subheader("💾 여행 파일 저장/불러오기")

col_f1, col_f2 = st.columns([1, 1])

with col_f2:
    uploaded = st.file_uploader("📂 여행 파일 불러오기 (JSON)", type=["json"], key="trip_uploader")

    if uploaded is not None:
        raw = uploaded.getvalue()
        sig = hashlib.sha256(raw).hexdigest()

        if st.session_state.last_loaded_sig != sig:
            data = json.loads(raw.decode("utf-8"))

            st.session_state.trip_name_ui = data.get("trip_name", "불러온_여행")
            st.session_state.participants = data.get("participants", [])
            st.session_state.expenses = data.get("expenses", [])

            for e in st.session_state.expenses:
                e.setdefault("created_at", datetime.now().isoformat())

            st.session_state.last_loaded_sig = sig
            st.success("파일에 저장된 상태로 화면에 복원했습니다 ✅")

st.text_input("여행 이름", key="trip_name_ui")
trip_name = st.session_state.trip_name_ui

with col_f1:
    save_payload = {
        "trip_name": trip_name,
        "participants": st.session_state.participants,
        "expenses": st.session_state.expenses,
    }
    st.download_button(
        "📥 여행 파일 저장 (JSON)",
        data=to_json_bytes(save_payload),
        file_name=f"{trip_name}.json",
        mime="application/json",
        use_container_width=True
    )

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
    st.stop()

# -------------------------------
# 환율
# -------------------------------
st.subheader("💱 환율 (통화 → KRW)")
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.number_input("KRW", value=1.0, step=1.0, disabled=True)
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
# ✅ 수정 핵심: 저장 후 session_state.amount_text/memo_text 직접 변경 제거
#             clear_on_submit=True가 자동으로 비워줌
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
        amount_str = st.text_input(
            "금액 (Enter로 저장)  ※ KRW/USD는 1,234 입력 가능",
            placeholder="예: 12,000 또는 12000",
            key="amount_text"
        )
        memo = st.text_input("메모(선택)", key="memo_text")

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
            try:
                amt = parse_amount_text(amount_str)
            except ValueError as e:
                st.error(str(e))
                st.stop()

            amount_krw = int(round(float(amt) * rates[currency]))

            st.session_state.expenses.append({
                "date": str(e_date),
                "category": category,
                "payer": payer,
                "currency": currency,
                "amount": float(amt),
                "amount_krw": amount_krw,
                "participants": participants_selected,
                "memo": memo,
                "created_at": datetime.now().isoformat()
            })
            st.rerun()

# -------------------------------
# 지출 내역 (표 형식 + 체크 삭제 + 총액)
# -------------------------------
st.subheader("📋 지출 내역")

if st.session_state.expenses:
    # 최신 날짜 순 정렬
    expenses_sorted = sorted(
        st.session_state.expenses,
        key=lambda x: (x.get("date", ""), x.get("created_at", "")),
        reverse=True
    )

    # DataFrame 변환
    table_rows = []
    total_amount = 0

    for e in expenses_sorted:
        total_amount += int(e["amount_krw"])
        table_rows.append({
            "삭제": False,
            "날짜": e["date"],
            "항목": e["category"],
            "금액(원)": f"{int(e['amount_krw']):,}",
            "결제자": e["payer"],
            "참여자": ", ".join(e["participants"]),
        })

    df_table = pd.DataFrame(table_rows)

    # ✅ 표 + 체크박스
    edited_df = st.data_editor(
        df_table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "삭제": st.column_config.CheckboxColumn(
                "삭제",
                help="삭제할 지출을 선택하세요",
                default=False,
            )
        }
    )

    # 삭제 버튼
    if st.button("🗑️ 선택 지출 삭제"):
        keep = []
        for keep_row, edited_row in zip(expenses_sorted, edited_df.to_dict("records")):
            if not edited_row["삭제"]:
                keep.append(keep_row)
        st.session_state.expenses = keep
        st.rerun()

    # 총액 표시
    st.markdown(
        f"""
        <div style="text-align:right; font-weight:700; font-size:1.1rem; margin-top:0.5em;">
        💰 현재까지 총 지출: {total_amount:,} 원
        </div>
        """,
        unsafe_allow_html=True
    )

else:
    st.info("아직 입력된 지출이 없습니다.")

# -------------------------------
# 정산 결과 + 송금 안내
# -------------------------------
st.subheader("📊 정산 결과")

summary_df, transfers_df = compute_settlement(st.session_state.participants, st.session_state.expenses)

show_summary = summary_df.copy()
for col in ["낸 금액", "부담금", "차액(낸-부담)"]:
    show_summary[col] = show_summary[col].apply(lambda x: f"{int(x):,}")

st.dataframe(show_summary, use_container_width=True)

st.subheader("💸 누가 누구에게 보내면 될까요?")
if transfers_df.empty:
    st.success("송금할 내역이 없습니다 🎉")
else:
    show_trans = transfers_df.copy()
    show_trans["금액(원)"] = show_trans["금액(원)"].apply(lambda x: f"{int(x):,}")
    st.dataframe(show_trans, use_container_width=True)

# -------------------------------
# 다운로드
# -------------------------------
st.subheader("📥 다운로드")

expenses_df = pd.DataFrame(st.session_state.expenses)
if expenses_df.empty:
    expenses_df = pd.DataFrame(columns=["date","category","payer","currency","amount","amount_krw","participants","memo","created_at"])

st.download_button(
    "📊 엑셀 다운로드 (지출/정산/송금)",
    data=make_excel(expenses_df, summary_df, transfers_df),
    file_name=f"{trip_name}.xlsx",
    use_container_width=True
)
