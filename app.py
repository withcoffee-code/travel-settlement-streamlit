import streamlit as st
import pandas as pd
from datetime import date, datetime
from io import BytesIO
import json
from collections import defaultdict
import hashlib
import re
import streamlit.components.v1 as components

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

# 설정 변화 감지용 시그니처
st.session_state.setdefault("settings_sig", None)

# 토스트 메시지 (rerun 후 띄우기)
st.session_state.setdefault("toast_msg", None)

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
# UI: 소제목 폰트 50% (bold 유지) + 타이틀 컬러
# -------------------------------
TONED_ORANGE = "#C97A2B"  # 톤다운 주황

st.markdown(
    f"""
    <style>
      /* subheader(h2) 크기 줄이기 */
      [data-testid="stMarkdownContainer"] h2 {{
        font-size: 1.05rem !important;
        font-weight: 700 !important;
      }}

      /* 메인 타이틀 톤다운 주황 */
      .main-title {{
        font-size: 28px;
        font-weight: 800;
        margin-bottom: 0.25em;
        color: {TONED_ORANGE};
      }}

      /* 메인 레이아웃 약간 정돈 */
      .tight {{
        margin-top: 0.25rem;
        margin-bottom: 0.25rem;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------------
# (실험적) 사이드바 자동 닫기: 마우스가 사이드바 밖으로 나가면 collapse 클릭
# - iPhone에서는 mouseleave가 거의 동작하지 않음(마우스가 없기 때문)
# - Streamlit DOM 변경 시 깨질 수 있음
# -------------------------------
components.html(
    """
    <script>
      (function() {
        function setup() {
          const sidebar = window.parent.document.querySelector('section[data-testid="stSidebar"]');
          if (!sidebar) return;

          // 중복 리스너 방지
          if (sidebar.dataset.autocloseAttached === "1") return;
          sidebar.dataset.autocloseAttached = "1";

          sidebar.addEventListener('mouseleave', function() {
            try {
              // Streamlit의 사이드바 토글 버튼
              const btn = window.parent.document.querySelector('button[data-testid="collapsedControl"]');
              if (btn) btn.click();
            } catch (e) {}
          });
        }

        // DOM이 늦게 올라오는 경우를 대비해 여러 번 시도
        let tries = 0;
        const timer = setInterval(() => {
          setup();
          tries += 1;
          if (tries > 20) clearInterval(timer);
        }, 250);
      })();
    </script>
    """,
    height=0
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
# 금액 입력 파서 (쉼표 허용)
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
# 총 지출 (KRW) 계산
# -------------------------------
def total_spent_krw() -> int:
    return int(sum(int(e.get("amount_krw", 0)) for e in st.session_state.expenses))

# -------------------------------
# ✅ 사이드바: 설정(파일/참여자/환율) + 총 지출 요약
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

    # ---------------------------
    # 여행 파일 저장/불러오기
    # ---------------------------
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
            st.session_state.last_loaded_sig = sig

            queue_toast("설정이 자동 반영되었습니다 ✅ (여행 파일 불러옴)")
            st.rerun()

    st.download_button(
        "📥 여행 파일 저장 (JSON)",
        data=to_json_bytes({
            "trip_name": st.session_state.trip_name_ui,
            "participants": st.session_state.participants,
            "expenses": st.session_state.expenses,
        }),
        file_name=f"{st.session_state.trip_name_ui}.json",
        mime="application/json",
        use_container_width=True
    )

    st.divider()

    # ---------------------------
    # 참여자 관리
    # ---------------------------
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

    # ---------------------------
    # 환율 설정 (세션에 저장)
    # ---------------------------
    st.markdown("### 💱 환율 (KRW 기준)")

    st.session_state.setdefault("rates", {"KRW": 1.0, "USD": 1350.0, "JPY": 9.2, "EUR": 1450.0})

    r_usd = st.number_input("USD", value=float(st.session_state.rates["USD"]), step=10.0, key="rate_usd")
    r_jpy = st.number_input("JPY", value=float(st.session_state.rates["JPY"]), step=0.1, key="rate_jpy")
    r_eur = st.number_input("EUR", value=float(st.session_state.rates["EUR"]), step=10.0, key="rate_eur")

    st.session_state.rates = {"KRW": 1.0, "USD": float(r_usd), "JPY": float(r_jpy), "EUR": float(r_eur)}

# -------------------------------
# 메인: 토스트 표시(한 번만)
# -------------------------------
flush_toast()

# -------------------------------
# 메인 타이틀(톤다운 주황)
# -------------------------------
st.markdown('<div class="main-title">여행 공동경비 정산</div>', unsafe_allow_html=True)

# -------------------------------
# 여행 이름 (subheader 레벨 + 아이콘)
# -------------------------------
st.subheader("🧳 여행 이름")
st.text_input(
    "여행 이름 입력",
    key="trip_name_ui",
    label_visibility="collapsed"
)

# 설정 변경 감지(토스트)
def current_settings_sig() -> str:
    payload = {
        "trip_name": st.session_state.trip_name_ui,
        "participants": st.session_state.participants,
        "rates": st.session_state.get("rates", {}),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

sig_now = current_settings_sig()
if st.session_state.settings_sig is None:
    st.session_state.settings_sig = sig_now
else:
    if sig_now != st.session_state.settings_sig:
        st.session_state.settings_sig = sig_now
        try:
            st.toast("설정이 자동 반영되었습니다 ✅")
        except Exception:
            pass

# 참여자 없으면 안내 문구 변경
if not st.session_state.participants:
    st.info("왼쪽 상단 >> 사이드 바 클릭하고 참여자를 먼저 추가하거나 기존 여행 파일을 열어 주세요")
    st.stop()

rates = st.session_state.rates
categories = ["숙박", "식사", "카페", "교통", "쇼핑", "액티비티", "기타"]

# -------------------------------
# 지출 입력 (Enter로 저장 / 쉼표 입력 가능 / 0 없음)
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
            "금액 (Enter로 저장)  ※ 1,234 입력 가능",
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
# 지출 내역: 표(테이블) + 체크 삭제 + 총액
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
        rows.append({
            "삭제": False,
            "날짜": e.get("date", ""),
            "항목": e.get("category", ""),
            "금액(원)": f"{int(e.get('amount_krw', 0)):,}",
            "결제자": e.get("payer", ""),
            "참여자": ", ".join(e.get("participants", [])),
        })

    df_table = pd.DataFrame(rows)

    edited_df = st.data_editor(
        df_table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "삭제": st.column_config.CheckboxColumn("삭제", default=False),
        },
        disabled=["날짜", "항목", "금액(원)", "결제자", "참여자"]
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
# 다운로드(엑셀)
# -------------------------------
st.subheader("📥 다운로드")

expenses_df = pd.DataFrame(st.session_state.expenses)
if expenses_df.empty:
    expenses_df = pd.DataFrame(columns=["date","category","payer","currency","amount","amount_krw","participants","memo","created_at"])

st.download_button(
    "📊 엑셀 다운로드 (지출/정산/송금)",
    data=make_excel(expenses_df, summary_df, transfers_df),
    file_name=f"{st.session_state.trip_name_ui}.xlsx",
    use_container_width=True
)
