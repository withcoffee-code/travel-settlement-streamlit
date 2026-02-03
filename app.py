import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO
import json
from collections import defaultdict
import hashlib
import re
import zipfile

# -------------------------------
# Excel 엔진 가용성 체크
# -------------------------------
try:
    import openpyxl  # noqa
    OPENPYXL_OK = True
except Exception:
    OPENPYXL_OK = False

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
st.session_state.setdefault("toast_msg", None)

st.session_state.setdefault("last_saved_filename", None)
st.session_state.setdefault("save_filename_ui", None)
st.session_state.setdefault("save_filename_touched", False)

st.session_state.setdefault("rates", {"KRW": 1.0, "USD": 1350.0, "JPY": 9.2, "EUR": 1450.0})

# ✅ 지출 입력 UI 상태 (폼 밖: 실시간 갱신 영역)
st.session_state.setdefault("ui_payer_only", False)
st.session_state.setdefault("ui_payer_not_owed", False)
st.session_state.setdefault("ui_payer", "")
st.session_state.setdefault("ui_beneficiary", "")

# ✅ 저장 후 UI 리셋 플래그 (위젯 키를 "렌더 후에" 직접 수정하지 않기 위함)
st.session_state.setdefault("_reset_expense_ui", False)

# -------------------------------
# 토스트 유틸
# -------------------------------
def queue_toast(msg: str):
    st.session_state.toast_msg = msg

def flush_toast():
    if st.session_state.toast_msg:
        try:
            st.toast(st.session_state.toast_msg)
        except Exception:
            pass
        st.session_state.toast_msg = None

# -------------------------------
# 스타일
# -------------------------------
TONED_ORANGE = "#C97A2B"
st.markdown(
    f"""
    <style>
      .main-title {{
        font-size: 28px;
        font-weight: 800;
        margin-bottom: 0.25em;
        color: {TONED_ORANGE};
      }}
      /* 소제목 폰트 반으로 줄이기(대략) */
      [data-testid="stMarkdownContainer"] h2 {{
        font-size: 1.05rem !important;
        font-weight: 700 !important;
      }}
      .hint {{
        font-size:0.85rem;
        color: rgba(0,0,0,0.55);
        margin-top: 4px;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------------
# 유틸
# -------------------------------
def to_json_bytes(data: dict) -> BytesIO:
    buf = BytesIO()
    buf.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    buf.seek(0)
    return buf

def make_excel(expenses_df: pd.DataFrame, summary_df: pd.DataFrame, transfers_df: pd.DataFrame) -> BytesIO:
    if not OPENPYXL_OK:
        raise ModuleNotFoundError("openpyxl")
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        expenses_df.to_excel(writer, index=False, sheet_name="지출내역")
        summary_df.to_excel(writer, index=False, sheet_name="정산결과")
        transfers_df.to_excel(writer, index=False, sheet_name="송금안내")
    buf.seek(0)
    return buf

def make_csv_zip(expenses_df: pd.DataFrame, summary_df: pd.DataFrame, transfers_df: pd.DataFrame) -> BytesIO:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("지출내역.csv", expenses_df.to_csv(index=False, encoding="utf-8-sig"))
        zf.writestr("정산결과.csv", summary_df.to_csv(index=False, encoding="utf-8-sig"))
        zf.writestr("송금안내.csv", transfers_df.to_csv(index=False, encoding="utf-8-sig"))
    buf.seek(0)
    return buf

def parse_amount_text(s: str) -> float:
    if s is None:
        raise ValueError("금액을 입력해 주세요.")
    s = s.strip()
    if s == "":
        raise ValueError("금액을 입력해 주세요.")
    s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise ValueError("금액은 숫자만 입력해 주세요. (예: 12,000 또는 12000)")
    v = float(s)
    if v <= 0:
        raise ValueError("금액은 0보다 커야 합니다.")
    return v

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
        display_ps = e.get("participants", [])
        payer_only = bool(e.get("payer_only", False))
        beneficiary = (e.get("beneficiary") or "").strip()

        # 계산 분배 대상 결정
        if beneficiary:
            split_ps = [beneficiary]      # 대신부담(전액)
        elif payer_only:
            split_ps = [payer]            # 결제자 전액부담
        else:
            split_ps = display_ps         # 일반 n분의1

        if not split_ps:
            continue

        paid[payer] += amt
        shares = split_amount_exact(amt, split_ps)
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

def total_spent_krw() -> int:
    return int(sum(int(e.get("amount_krw", 0)) for e in st.session_state.expenses))

# -------------------------------
# ✅ 저장 후 UI 리셋: "다음 rerun 시작 시" 안전하게 처리
# -------------------------------
if st.session_state._reset_expense_ui:
    st.session_state.ui_payer_only = False
    st.session_state.ui_payer_not_owed = False
    st.session_state.ui_beneficiary = ""
    st.session_state._reset_expense_ui = False

# -------------------------------
# 저장 파일명 동기화(사용자 편집 전까지)
# -------------------------------
def on_save_filename_change():
    st.session_state.save_filename_touched = True

if st.session_state.save_filename_ui is None:
    st.session_state.save_filename_ui = st.session_state.trip_name_ui
if not st.session_state.save_filename_touched:
    st.session_state.save_filename_ui = st.session_state.trip_name_ui

# -------------------------------
# 사이드바
# -------------------------------
with st.sidebar:
    st.markdown("## ⚙️ 설정")
    st.markdown(
        f"""
        <div style="padding:10px 12px; border-radius:12px; background:rgba(0,0,0,0.04);">
          <div style="font-size:0.9rem; font-weight:700;">💰 현재 총 지출</div>
          <div style="font-size:1.2rem; font-weight:800;">{total_spent_krw():,} 원</div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.write("")

    st.markdown("### 💾 여행 파일")
    uploaded = st.file_uploader("여행 파일 불러오기 (JSON)", type=["json"], key="trip_uploader_sidebar")
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
                e.setdefault("payer_only", False)
                e.setdefault("beneficiary", "")
            st.session_state.last_loaded_sig = sig
            if not st.session_state.save_filename_touched:
                st.session_state.save_filename_ui = st.session_state.trip_name_ui
            queue_toast("설정이 자동 반영되었습니다 ✅ (여행 파일 불러옴)")
            st.rerun()

    st.text_input("저장 파일명 (확장자 제외)", key="save_filename_ui", on_change=on_save_filename_change)

    current_save_name = (st.session_state.save_filename_ui or "").strip() or st.session_state.trip_name_ui
    same_as_last = (st.session_state.last_saved_filename == current_save_name)

    confirm_overwrite = True
    if same_as_last:
        confirm_overwrite = st.checkbox("⚠️ 이전 저장 파일명과 동일합니다. 계속 다운로드(덮어쓰기) 할까요?", value=False)

    can_download = (not same_as_last) or confirm_overwrite

    payload = {
        "trip_name": st.session_state.trip_name_ui,
        "participants": st.session_state.participants,
        "expenses": st.session_state.expenses,
    }

    if st.download_button(
        "📥 여행 파일 저장 (JSON)",
        data=to_json_bytes(payload),
        file_name=f"{current_save_name}.json",
        mime="application/json",
        use_container_width=True,
        disabled=not can_download
    ):
        st.session_state.last_saved_filename = current_save_name
        queue_toast("저장 파일 다운로드 준비 완료 ✅")

    st.divider()

    st.markdown("### 👥 참여자")
    with st.form("add_participant_sidebar", clear_on_submit=True):
        name = st.text_input("이름 추가", placeholder="예: 엄마, 아빠, 민수")
        add = st.form_submit_button("추가")
        if add and name:
            if name not in st.session_state.participants:
                if len(st.session_state.participants) < 8:
                    st.session_state.participants.append(name)
                    queue_toast("설정이 자동 반영되었습니다 ✅ (참여자 추가)")
                else:
                    st.warning("최대 8명까지 가능합니다.")
            st.rerun()

    if st.session_state.participants:
        st.caption("현재 참여자")
        st.write(", ".join(st.session_state.participants))
    else:
        st.caption("참여자를 추가해 주세요.")

    st.divider()

    st.markdown("### 💱 환율 (KRW 기준)")
    r_usd = st.number_input("USD", value=float(st.session_state.rates["USD"]), step=10.0, key="rate_usd")
    r_jpy = st.number_input("JPY", value=float(st.session_state.rates["JPY"]), step=0.1, key="rate_jpy")
    r_eur = st.number_input("EUR", value=float(st.session_state.rates["EUR"]), step=10.0, key="rate_eur")
    st.session_state.rates = {"KRW": 1.0, "USD": float(r_usd), "JPY": float(r_jpy), "EUR": float(r_eur)}

# -------------------------------
# 메인
# -------------------------------
flush_toast()
st.markdown('<div class="main-title">여행 공동경비 정산</div>', unsafe_allow_html=True)

st.subheader("🧳 여행 이름")
st.text_input("여행 이름 입력", key="trip_name_ui", label_visibility="collapsed")

if not st.session_state.participants:
    st.info("왼쪽 상단 >> 사이드 바 클릭하고 참여자를 먼저 추가하거나 기존 여행 파일을 열어 주세요")
    st.stop()

rates = st.session_state.rates
categories = ["숙박", "식사", "카페", "교통", "쇼핑", "액티비티", "기타"]

# ✅ 결제자 기본값 보정(참여자 변경/로드 후에도 안전하게)
if st.session_state.ui_payer not in st.session_state.participants:
    st.session_state.ui_payer = st.session_state.participants[0]

# -------------------------------
# ✅ 지출 입력 (실시간 영역 + 저장은 form_submit 1개)
#   핵심: payer/대신부담/부담자선택은 폼 밖 → 즉시 후보 갱신
# -------------------------------
st.subheader("🧾 지출 입력")

row1a, row1b, row1c = st.columns([1, 1, 1])
with row1a:
    st.selectbox("결제자", st.session_state.participants, key="ui_payer")
with row1b:
    st.checkbox("✅ 결제자가 전액 부담(나만 부담)", key="ui_payer_only")
with row1c:
    st.checkbox("🟣 결제자는 부담 안 함(다른 사람이 전액 부담)", key="ui_payer_not_owed")

# 충돌 경고(자동 해제는 위젯 렌더 이후 직접 수정 위험이 있어 경고+저장시 검증)
if st.session_state.ui_payer_only and st.session_state.ui_payer_not_owed:
    st.warning("전액부담 옵션 2개는 동시에 선택할 수 없어요. 하나만 선택해 주세요. (저장 시 검증됩니다)")

# ✅ 대신부담: 체크 즉시 후보가 payer 제외로 갱신됨(이게 이번 문제 해결 포인트)
beneficiary = ""
if st.session_state.ui_payer_not_owed:
    candidates = [p for p in st.session_state.participants if p != st.session_state.ui_payer]
    if candidates:
        # 기존 선택값이 후보에 없으면 첫 후보로 보정 (ui_beneficiary는 위젯 키가 아니라 안전)
        if st.session_state.ui_beneficiary not in candidates:
            st.session_state.ui_beneficiary = candidates[0]

        beneficiary = st.selectbox(
            "전액 부담자(대신 내는 사람) 선택",
            candidates,
            index=candidates.index(st.session_state.ui_beneficiary),
            key="beneficiary_selectbox_live",
        )
        st.session_state.ui_beneficiary = beneficiary
        st.markdown('<div class="hint">정산 분배 대상: 전액 부담자 1명</div>', unsafe_allow_html=True)
    else:
        st.warning("결제자 외에 다른 참여자가 없습니다. 대신 부담자를 선택할 수 없어요.")
        st.session_state.ui_beneficiary = ""
else:
    st.session_state.ui_beneficiary = ""

# -------------------------------
# ✅ 저장은 form_submit 1개 (자동/중복 저장 재발 방지)
# -------------------------------
with st.form("expense_form_clean", clear_on_submit=True):
    a, b, c = st.columns(3)
    with a:
        e_date = st.date_input("날짜", value=date.today())
        category = st.selectbox("항목", categories)
    with b:
        currency = st.selectbox("통화", list(rates.keys()))
    with c:
        amount_str = st.text_input("금액 (쉼표 가능)", placeholder="예: 12,000")
        memo = st.text_input("메모(선택)")

    ps_display = st.multiselect(
        "참여자 (표시용)  ※ 예외/전액부담이어도 표시용으로 남습니다",
        st.session_state.participants,
        default=list(st.session_state.participants),
    )

    submitted = st.form_submit_button("저장")

    if submitted:
        # 검증
        if st.session_state.ui_payer_only and st.session_state.ui_payer_not_owed:
            st.error("전액부담 옵션 2개는 동시에 선택할 수 없어요. 하나만 선택해 주세요.")
            st.stop()

        if not ps_display:
            st.error("참여자를 최소 1명 이상 선택하세요.")
            st.stop()

        if st.session_state.ui_payer_not_owed and not st.session_state.ui_beneficiary:
            st.error("대신 부담자를 선택해 주세요.")
            st.stop()

        try:
            amt = parse_amount_text(amount_str)
        except ValueError as e:
            st.error(str(e))
            st.stop()

        amount_krw = int(round(float(amt) * rates[currency]))

        st.session_state.expenses.append({
            "date": str(e_date),
            "category": category,
            "payer": st.session_state.ui_payer,
            "currency": currency,
            "amount": float(amt),
            "amount_krw": amount_krw,
            "participants": ps_display,  # 표시용
            "payer_only": bool(st.session_state.ui_payer_only),  # 계산용
            "beneficiary": st.session_state.ui_beneficiary if st.session_state.ui_payer_not_owed else "",  # 계산용
            "memo": memo,
            "created_at": datetime.now().isoformat()
        })

        queue_toast("지출이 추가되었습니다 ✅")

        # 저장 후 UI 토글/부담자 리셋(안전 플래그)
        st.session_state._reset_expense_ui = True

        st.rerun()

# -------------------------------
# 지출 내역 표
# -------------------------------
st.subheader("📋 지출 내역")

if st.session_state.expenses:
    expenses_sorted = sorted(
        st.session_state.expenses,
        key=lambda x: (x.get("date", ""), x.get("created_at", "")),
        reverse=True
    )

    rows = []
    total_amount = 0
    for e in expenses_sorted:
        total_amount += int(e.get("amount_krw", 0))
        note = ""
        if e.get("beneficiary"):
            note = f"대신부담: {e['beneficiary']}"
        elif e.get("payer_only", False):
            note = "전액부담"

        rows.append({
            "삭제": False,
            "날짜": e.get("date", ""),
            "항목": e.get("category", ""),
            "금액(원)": f"{int(e.get('amount_krw', 0)):,}",
            "결제자": e.get("payer", ""),
            "참여자": ", ".join(e.get("participants", [])),
            "비고": note,
        })

    df_table = pd.DataFrame(rows)

    edited_df = st.data_editor(
        df_table,
        hide_index=True,
        use_container_width=True,
        column_config={"삭제": st.column_config.CheckboxColumn("삭제", default=False)},
        disabled=["날짜", "항목", "금액(원)", "결제자", "참여자", "비고"]
    )

    col_del, col_sum = st.columns([1, 1])
    with col_del:
        if st.button("🗑️ 선택 지출 삭제"):
            keep = []
            edited_records = edited_df.to_dict("records")
            for original, edited in zip(expenses_sorted, edited_records):
                if not edited["삭제"]:
                    keep.append(original)
            st.session_state.expenses = keep
            st.rerun()

    with col_sum:
        st.markdown(
            f"""
            <div style="text-align:right; font-weight:800; font-size:1.1rem;">
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
    expenses_df = pd.DataFrame(columns=[
        "date","category","payer","currency","amount","amount_krw","participants",
        "payer_only","beneficiary","memo","created_at"
    ])

if OPENPYXL_OK:
    st.download_button(
        "📊 엑셀 다운로드 (지출/정산/송금)",
        data=make_excel(expenses_df, summary_df, transfers_df),
        file_name=f"{st.session_state.trip_name_ui}.xlsx",
        use_container_width=True
    )
else:
    st.warning("현재 서버에 openpyxl이 없어 엑셀 다운로드가 비활성입니다. 대신 CSV ZIP을 내려받을 수 있어요.")
    st.download_button(
        "📦 CSV ZIP 다운로드 (지출/정산/송금)",
        data=make_csv_zip(expenses_df, summary_df, transfers_df),
        file_name=f"{st.session_state.trip_name_ui}_csv.zip",
        use_container_width=True
    )
