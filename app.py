import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO
import json
from collections import defaultdict
import hashlib
import re
import zipfile
import uuid

# -------------------------------
# Excel 엔진 가용성 체크 (xlsxwriter 말고 openpyxl)
# -------------------------------
try:
    import openpyxl  # noqa
    OPENPYXL_OK = True
except Exception:
    OPENPYXL_OK = False

# -------------------------------
# 페이지 설정
# -------------------------------
st.set_page_config(page_title="여행 공동경비 정산", layout="wide")

# -------------------------------
# 스타일
# -------------------------------
TONED_ORANGE = "#C97A2B"
TONED_PURPLE = "#821E50"
st.markdown(
    f"""
    <style>
      .main-title {{
        font-size: 30px;
        font-weight: 800;
        margin-bottom: 0.25em;
        color: {TONED_ORANGE};
      }}
      [data-testid="stMarkdownContainer"] h2 {{
        font-size: 1.02rem !important;
        font-weight: 700 !important;
      }}
      .hint {{
        font-size:0.85rem;
        color: rgba(0,0,0,0.55);
        margin-top: 4px;
      }}
      .edit-banner {{
        padding: 10px 12px;
        border-radius: 12px;
        background: rgba(201,122,43,0.12);
        border: 1px solid rgba(201,122,43,0.25);
        margin-bottom: 10px;
        font-weight: 700;
      }}
      .pill {{
        display:inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 700;
        background: rgba(210, 82, 140, 0.15);
        border: 1px solid rgba(210, 82, 140, 0.25);
        color: rgba(130, 30, 80, 0.95);
      }}
      .sidebar-title {{
        font-size: 1.7rem;
        font-weight: 600;
        margin: 0.2rem 0 0.6rem 0;
      }}
      .right-total {{
     #   text-align: right;
        font-weight: 700;
        font-size: 1.4rem;
         margin-top: 0.5rem;
    #    margin-right: 3rem;
        color: {TONED_PURPLE};
      }}
      .right-total small {{
        font-weight: 700;
        opacity: 0.75;
      }}
      .header-row {{
      display: flex;
      align-items: center;   /* 🔥 세로 중앙 정렬의 핵심 */
      height: 100%;
      }}
      .stat-total {{
      text-align:right; 
      font-weight:600; 
      font-size:1.2rem; 
      margin-top:1px; 
      color: {TONED_PURPLE};
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------------
# Session State 초기화
# -------------------------------
def ss_setdefault(k, v):
    if k not in st.session_state:
        st.session_state[k] = v

ss_setdefault("trip_name_ui", "여행_정산")
ss_setdefault("participants", [])
ss_setdefault("expenses", [])
ss_setdefault("rates", {"KRW": 1.0, "USD": 1350.0, "JPY": 9.2, "EUR": 1450.0})

ss_setdefault("last_loaded_sig", None)
ss_setdefault("toast_msg", None)

ss_setdefault("save_filename_ui", None)
ss_setdefault("save_filename_touched", False)
ss_setdefault("last_saved_filename", None)

ss_setdefault("ui_nonce", 0)
ss_setdefault("editing_id", None)

# -------------------------------
# 토스트
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
# 유틸
# -------------------------------
def to_json_bytes(data: dict) -> BytesIO:
    buf = BytesIO()
    buf.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    buf.seek(0)
    return buf

def ensure_expense_ids():
    for e in st.session_state.expenses:
        if "id" not in e or not e["id"]:
            e["id"] = uuid.uuid4().hex
        e.setdefault("created_at", datetime.now().isoformat())
        e.setdefault("payer_only", False)
        e.setdefault("beneficiary", "")
        e.setdefault("memo", "")
        e.setdefault("currency", "KRW")
        e.setdefault("amount", 0.0)
        e.setdefault("amount_krw", 0)

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

        if beneficiary:
            split_ps = [beneficiary]
        elif payer_only:
            split_ps = [payer]
        else:
            split_ps = display_ps

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

def total_spent_krw() -> int:
    return int(sum(int(e.get("amount_krw", 0)) for e in st.session_state.expenses))

def safe_date_from_str(s: str):
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        try:
            return date.fromisoformat(s)
        except Exception:
            return date.today()

def find_expense(exp_id: str):
    for e in st.session_state.expenses:
        if e.get("id") == exp_id:
            return e
    return None

# -------------------------------
# 저장 파일명 동기화
# -------------------------------
def on_save_filename_change():
    st.session_state.save_filename_touched = True

if st.session_state.save_filename_ui is None:
    st.session_state.save_filename_ui = st.session_state.trip_name_ui
if not st.session_state.save_filename_touched:
    st.session_state.save_filename_ui = st.session_state.trip_name_ui

# -------------------------------
# 사이드바 (설정)
# -------------------------------
with st.sidebar:
    # ✅ 요청: "설정" 타이틀 2배로 크게
    st.markdown('<div class="sidebar-title">⚙️ 설정</div>', unsafe_allow_html=True)

    # ✅ 요청: 총지출 박스 제거 (기능 영향 없음)
    # (삭제됨)

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
            ensure_expense_ids()
            st.session_state.last_loaded_sig = sig

            if not st.session_state.save_filename_touched:
                st.session_state.save_filename_ui = st.session_state.trip_name_ui

            st.session_state.editing_id = None
            st.session_state.ui_nonce += 1

            queue_toast("여행 파일을 불러왔어요 ✅")
            st.rerun()

    st.text_input("저장 파일명 (확장자 제외)", key="save_filename_ui", on_change=on_save_filename_change)

    current_save_name = (st.session_state.save_filename_ui or "").strip() or st.session_state.trip_name_ui
    same_as_last = (st.session_state.last_saved_filename == current_save_name)

    confirm_overwrite = True
    if same_as_last:
        confirm_overwrite = st.checkbox("⚠️ 같은 이름으로 다시 저장합니다(덮어쓰기). 계속할까요?", value=False)

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
        disabled=not can_download,
    ):
        st.session_state.last_saved_filename = current_save_name
        queue_toast("저장 파일이 준비되었습니다 ✅")

    st.divider()

    st.markdown("### 👥 참여자")
    with st.form("add_participant_sidebar", clear_on_submit=True):
        name = st.text_input("이름 추가", placeholder="예: 엄마, 아빠, 민수")
        add = st.form_submit_button("추가")
        if add and name:
            if name not in st.session_state.participants:
                if len(st.session_state.participants) < 8:
                    st.session_state.participants.append(name)
                    st.session_state.ui_nonce += 1
                    queue_toast("참여자가 추가되었습니다 ✅")
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
    r_usd = st.number_input("USD", value=float(st.session_state.rates.get("USD", 1350.0)), step=10.0)
    r_jpy = st.number_input("JPY", value=float(st.session_state.rates.get("JPY", 9.2)), step=0.1)
    r_eur = st.number_input("EUR", value=float(st.session_state.rates.get("EUR", 1450.0)), step=10.0)
    st.session_state.rates = {"KRW": 1.0, "USD": float(r_usd), "JPY": float(r_jpy), "EUR": float(r_eur)}

# -------------------------------
# 메인 UI
# -------------------------------
flush_toast()
st.markdown('<div class="main-title">여행 공동경비 정산</div>', unsafe_allow_html=True)

st.subheader("🧳 여행 이름")
st.text_input("여행 이름 입력", key="trip_name_ui", label_visibility="collapsed")

if not st.session_state.participants:
    st.info("왼쪽 상단 >> 사이드 바 클릭하고 참여자를 먼저 추가하거나 기존 여행 파일을 열어 주세요.")
    st.stop()

ensure_expense_ids()

rates = st.session_state.rates
categories = ["숙박", "식사", "카페", "교통", "쇼핑", "액티비티", "기타"]

# -------------------------------
# 지출 내역 표 (결제자/참여자 컬럼 분리)
# -------------------------------
# ✅ 요청: 타이틀 오른쪽 옆에 총지출 표시 (표 아래 표시는 제거)
total_inline = total_spent_krw()
h1, h2 = st.columns([3, 2])
with h1:
    st.subheader("📋 지출 내역")
# with h2:
#    st.markdown(f'<div class="right-total"><small>총지출</small> {total_inline:,} 원</div>', unsafe_allow_html=True)
with h2:
    st.markdown(
        f"""
        <div class="header-row">
          <div class="right-total">
            <small>총지출</small> {total_inline:,} <small>원</small> 
          </div>
        </div>
        """,
        unsafe_allow_html=True
    )
if st.session_state.expenses:
    expenses_sorted = sorted(
        st.session_state.expenses,
        key=lambda x: (x.get("date", ""), x.get("created_at", "")),
        reverse=True
    )
    id_order = [e["id"] for e in expenses_sorted]

    rows = []
    total_amount = 0
    for e in expenses_sorted:
        total_amount += int(e.get("amount_krw", 0))

        note_parts = []
        if e.get("beneficiary"):
            note_parts.append(f"대신부담: {e['beneficiary']}")
        if e.get("payer_only", False):
            note_parts.append("전액부담")
        note = " / ".join(note_parts)

        rows.append({
            "선택": False,
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
        column_config={"선택": st.column_config.CheckboxColumn("선택", default=False)},
        disabled=["날짜", "항목", "금액(원)", "결제자", "참여자", "비고"],
    )

    selected_idx = [i for i, r in enumerate(edited_df.to_dict("records")) if r.get("선택")]

    col_a, col_b = st.columns([1, 1])

    with col_a:
        if st.button("✏️ 수정", use_container_width=True):
            if len(selected_idx) != 1:
                st.warning("수정할 항목을 1개만 선택해 주세요.")
            else:
                st.session_state.editing_id = id_order[selected_idx[0]]
                st.session_state.ui_nonce += 1
                st.rerun()

    with col_b:
        if st.button("🗑️ 삭제", use_container_width=True):
            if not selected_idx:
                st.warning("삭제할 항목을 선택해 주세요.")
            else:
                delete_ids = set(id_order[i] for i in selected_idx)
                st.session_state.expenses = [e for e in st.session_state.expenses if e.get("id") not in delete_ids]
                if st.session_state.editing_id in delete_ids:
                    st.session_state.editing_id = None
                st.session_state.ui_nonce += 1
                st.rerun()

else:
    st.info("아직 입력된 지출이 없습니다.")

# -------------------------------
# 지출 입력 / 수정
# -------------------------------
st.subheader("🧾 지출 입력")

editing = st.session_state.editing_id is not None
target = find_expense(st.session_state.editing_id) if editing else None
if editing and target is None:
    st.session_state.editing_id = None
    st.session_state.ui_nonce += 1
    editing = False
    target = None

if editing:
    st.markdown('<div class="edit-banner">✏️ 수정 모드: 아래 내용을 수정한 뒤 “수정 저장”을 누르세요.</div>', unsafe_allow_html=True)

def_val_date = safe_date_from_str(target["date"]) if editing else date.today()
def_val_cat = target.get("category", categories[0]) if editing else categories[0]
def_val_payer = target.get("payer", st.session_state.participants[0]) if editing else st.session_state.participants[0]
def_val_cur = target.get("currency", "KRW") if editing else "KRW"
def_val_amt = target.get("amount", "") if editing else ""
def_val_memo = target.get("memo", "") if editing else ""
def_val_ps = target.get("participants", list(st.session_state.participants)) if editing else list(st.session_state.participants)
def_val_payer_only = bool(target.get("payer_only", False)) if editing else False
def_val_beneficiary = (target.get("beneficiary", "") or "").strip() if editing else ""

ui_nonce = st.session_state.ui_nonce

payer = st.selectbox(
    "결제자",
    st.session_state.participants,
    index=st.session_state.participants.index(def_val_payer) if def_val_payer in st.session_state.participants else 0,
    key=f"payer_{ui_nonce}",
)

payer_only = st.checkbox(
    "✅ 결제자가 전액 부담(나만 부담)",
    value=def_val_payer_only if not def_val_beneficiary else False,
    key=f"payer_only_{ui_nonce}",
)

payer_not_owed = st.checkbox(
    "🟣 결제자는 부담 안 함(다른 사람이 전액 부담)",
    value=True if def_val_beneficiary else False,
    key=f"payer_not_owed_{ui_nonce}",
)

if payer_only and payer_not_owed:
    st.warning("전액 옵션은 하나만 선택해 주세요. (저장 시 검증됩니다)")

beneficiary = ""
if payer_not_owed:
    candidates = [p for p in st.session_state.participants if p != payer]
    if candidates:
        init_b = def_val_beneficiary if def_val_beneficiary in candidates else candidates[0]
        beneficiary = st.selectbox(
            "전액 부담자(대신 내는 사람) 선택",
            candidates,
            index=candidates.index(init_b),
            key=f"beneficiary_{ui_nonce}_{payer}",
        )
        st.markdown('<div class="hint">정산 분배 대상: 전액 부담자 1명</div>', unsafe_allow_html=True)
    else:
        st.warning("결제자 외에 다른 참여자가 없습니다. 대신 부담자를 선택할 수 없어요.")

with st.form(f"expense_form_{ui_nonce}", clear_on_submit=False):
    c1, c2, c3 = st.columns(3)
    with c1:
        e_date = st.date_input("날짜", value=def_val_date)
        category = st.selectbox("항목", categories, index=categories.index(def_val_cat) if def_val_cat in categories else 0)
    with c2:
        currency = st.selectbox("통화", list(rates.keys()), index=list(rates.keys()).index(def_val_cur) if def_val_cur in rates else 0)
        amount_str = st.text_input("금액 (쉼표 가능)", value=(f"{def_val_amt}".strip() if def_val_amt != "" else ""), placeholder="예: 12,000")
    with c3:
        memo = st.text_input("메모(선택)", value=def_val_memo)

    ps_display = st.multiselect(
        "참여자 (표시용)  ※ 예외/전액부담이어도 표시용으로 남습니다",
        st.session_state.participants,
        default=[p for p in def_val_ps if p in st.session_state.participants] or list(st.session_state.participants),
    )

    b1, b2 = st.columns([1, 1])
    with b1:
        submitted = st.form_submit_button("수정 저장" if editing else "저장")
    with b2:
        cancel = st.form_submit_button("수정 취소") if editing else False

    if cancel:
        st.session_state.editing_id = None
        st.session_state.ui_nonce += 1
        queue_toast("수정 모드를 종료했습니다.")
        st.rerun()

    if submitted:
        if payer_only and payer_not_owed:
            st.error("전액 옵션은 하나만 선택해 주세요.")
            st.stop()

        if not ps_display:
            st.error("참여자를 최소 1명 이상 선택해 주세요.")
            st.stop()

        if payer_not_owed and not beneficiary:
            st.error("대신 부담자를 선택해 주세요.")
            st.stop()

        try:
            amt = parse_amount_text(amount_str)
        except ValueError as e:
            st.error(str(e))
            st.stop()

        amount_krw = int(round(float(amt) * rates[currency]))

        item = {
            "id": target["id"] if editing else uuid.uuid4().hex,
            "date": str(e_date),
            "category": category,
            "payer": payer,
            "currency": currency,
            "amount": float(amt),
            "amount_krw": amount_krw,
            "participants": ps_display,
            "payer_only": bool(payer_only) if not payer_not_owed else False,
            "beneficiary": beneficiary if payer_not_owed else "",
            "memo": memo,
        }

        if editing:
            for i, e in enumerate(st.session_state.expenses):
                if e.get("id") == target["id"]:
                    item["created_at"] = e.get("created_at", datetime.now().isoformat())
                    item["updated_at"] = datetime.now().isoformat()
                    st.session_state.expenses[i] = item
                    break
            st.session_state.editing_id = None
            queue_toast("지출이 수정되었습니다 ✅")
        else:
            item["created_at"] = datetime.now().isoformat()
            st.session_state.expenses.append(item)
            queue_toast("지출이 추가되었습니다 ✅")

        st.session_state.ui_nonce += 1
        st.rerun()

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
# ✅ 항목별 지출 통계 (다운로드 위에 표시)
# -------------------------------
st.subheader("📌 항목별 지출 총액")

if st.session_state.expenses:
    exp_df_stat = pd.DataFrame(st.session_state.expenses)
    if not exp_df_stat.empty and "category" in exp_df_stat.columns:
        cat_df = (
            exp_df_stat.groupby("category", as_index=False)["amount_krw"]
            .sum()
            .rename(columns={"category": "항목", "amount_krw": "총액(원)"})
            .sort_values("총액(원)", ascending=False)
        )

        total_all = int(exp_df_stat["amount_krw"].sum()) if "amount_krw" in exp_df_stat.columns else 0
        cat_df_show = cat_df.copy()
        cat_df_show["총액(원)"] = cat_df_show["총액(원)"].apply(lambda x: f"{int(x):,}")

        st.dataframe(cat_df_show, use_container_width=True)

        st.markdown(
            f"""
            <div class="stat-total">
            합계: {total_all:,} 원
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.info("통계를 계산할 지출 데이터가 없습니다.")
else:
    st.info("지출이 없어서 통계를 표시할 수 없습니다.")

# -------------------------------
# 다운로드
# -------------------------------
st.subheader("📥 다운로드")

expenses_df = pd.DataFrame(st.session_state.expenses)
if expenses_df.empty:
    expenses_df = pd.DataFrame(columns=[
        "id","date","category","payer","currency","amount","amount_krw","participants",
        "payer_only","beneficiary","memo","created_at","updated_at"
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
