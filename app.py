import streamlit as st
from streamlit_option_menu import option_menu
import datetime
import json 
import pandas as pd
import numpy as np
from streamlit_calendar import calendar
from sqlalchemy import text
import io

# ==========================================
# 💾 클라우드 데이터베이스(Supabase PostgreSQL) 연결 설정
# ==========================================
conn = st.connection("postgresql", type="sql")

# 1. 페이지 기본 설정 및 디자인
st.set_page_config(page_title="QC 시험 스케줄 시스템", layout="wide")
st.markdown("""
    <style>
        [data-testid="stAppViewContainer"] { background-color: #F8F9FA; }
        [data-testid="stSidebar"] { background-color: #FFFFFF; }
        .custom-header { font-size: 1.6rem; font-weight: 600; color: #333333; margin-bottom: 0.5rem; padding-bottom: 12px; border-bottom: 2px solid #FF9F68; }
        .sub-header { font-size: 1.2rem; font-weight: 600; color: #555555; margin-top: 25px; margin-bottom: 10px; }
        div.stButton > button[kind="primary"] { background-color: #FF9F68 !important; color: white !important; border: none !important; }
        div.stButton > button[kind="primary"]:hover { background-color: #FF8C4B !important; }
        .stTabs [data-baseweb="tab-list"] { gap: 24px; }
        .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; background-color: transparent; border-radius: 4px 4px 0px 0px; padding-top: 10px; padding-bottom: 10px; }
        th { background-color: #F0F2F6 !important; color: #333333 !important; }
        div[data-testid="stMetricValue"] { color: #2C3E50; font-size: 2rem; font-weight: 700; }
    </style>
""", unsafe_allow_html=True)

# 🌟 플래시 메시지 시스템
if 'flash_msgs' not in st.session_state: st.session_state.flash_msgs = []
if st.session_state.flash_msgs:
    for msg, level in st.session_state.flash_msgs:
        if level == 'warning': st.warning(msg, icon="⚠️")
        elif level == 'error': st.error(msg, icon="🚨")
        elif level == 'info': st.info(msg, icon="💡")
        elif level == 'success': st.success(msg, icon="✅")
    st.session_state.flash_msgs = []

# --- 🧠 데이터 기억 장치 초기화 ---
if 'custom_tests' not in st.session_state: st.session_state.custom_tests = [] 
if 'test_groups' not in st.session_state:
    st.session_state.test_groups = {
        "A제품 기본시험 세트": ["확인 및 순도 시험", "pH 측정 시험", "엔도톡신시험"],
        "세포주 출하 검사 세트": ["마이코플라스마부정시험(qPCR)", "외래성바이러스부정시험", "총 세포수 및 세포 생존율 시험", "무균시험(직접법)"]
    }
if 'test_master' not in st.session_state:
    st.session_state.test_master = {
        "불용성미립자시험": ["≥10㎛", "≥25㎛"],
        "확인 및 순도 시험": ["CD56+(%)", "CD16+(%)", "CD19+(%)", "CD3+(%)", "CD14+(%)"]
    }
if 'item_master' not in st.session_state:
    st.session_state.item_master = [
        "DWDP-006", "DWDP-004", "DWCB-001", "1N NaOH solution", 
        "1X CTSTM DPBS", "MEM-alpha", "PBMC", "EXOEF1"
    ]
if 'expanded_groups' not in st.session_state: st.session_state.expanded_groups = set()
if 'last_clicked_event' not in st.session_state: st.session_state.last_clicked_event = None

base_tests = [
    "성상", "무균시험(직접법)", "무균시험(신속법)", "무균시험(신속법, 그람염색법)", "외관검사", "규격", "제조처 성적서 확인",
    "확인 및 순도 시험", "역가시험", "마이코플라스마부정시험(qPCR)", "마이코플라스마부정시험(배양법)", "마이코플라스마(신속법)",
    "외래성바이러스부정시험", "총 세포수 및 세포 생존율 시험", "기밀도 시험", "엔도톡신시험", "미생물한도시험", "pH 측정 시험",
    "불용성미립자시험", "DMSO 함량시험"
]
all_available_tests = list(set(base_tests + st.session_state.custom_tests))


# 2. 좌측 사이드바 구성
with st.sidebar:
    try: st.image("logo.png", use_container_width=True) 
    except: st.write("[로고 이미지 삽입 영역]")
    st.markdown("<br>", unsafe_allow_html=True)
    
    selected = option_menu(
        menu_title=None, 
        options=["대시보드", "시험 접수 및 배정", "접수 대장 조회", "전체 스케줄 보드", "결과 입력 (CoA)", "시험 결과 조회", "PQR 경향 분석", "설정"],
        icons=["house", "pencil-square", "table", "calendar-week", "check2-square", "search", "graph-up", "gear"], 
        default_index=2, 
        styles={
            "container": {"padding": "0!important", "background-color": "#FFFFFF"},
            "icon": {"color": "#6C757D", "font-size": "16px"}, 
            "nav-link": {"font-size": "14.5px", "text-align": "left", "margin":"0px", "--hover-color": "#F0F2F6", "color": "#4A4A4A"},
            "nav-link-selected": {"background-color": "#FF9F68", "color": "white", "font-weight": "normal"}, 
        }
    )

# ==========================================
# 🌟 Adverse Trend 감지 엔진
# ==========================================
def check_adverse_trend(item_name, test_name, param_name, current_val):
    try: current_val_float = float(current_val)
    except: return None 
    query = f"SELECT assignments FROM reception_logs WHERE item_name='{item_name}' AND coa_no IS NOT NULL AND coa_no != '' ORDER BY id ASC"
    df = conn.query(query, ttl="0")
    history = []
    for _, row in df.iterrows():
        try:
            assigns = row['assignments']
            if isinstance(assigns, str): assigns = json.loads(assigns)
            if test_name in assigns:
                res = assigns[test_name].get("result", {}).get(param_name)
                if res is not None: history.append(float(res))
        except: pass
    history.append(current_val_float)
    if len(history) >= 3:
        last_3 = history[-3:]
        if last_3[0] < last_3[1] < last_3[2]: return f"[{test_name} - {param_name}] 최근 3회 연속 상승 경향! (현재: {last_3[2]}) Adverse Trend 확인 요망."
        if last_3[0] > last_3[1] > last_3[2]: return f"[{test_name} - {param_name}] 최근 3회 연속 하락 경향! (현재: {last_3[2]}) Adverse Trend 확인 요망."
    return None

# ==========================================
# 3. 메인 화면 분기
# ==========================================

# --- 🏠 대시보드 ---
if selected == "대시보드":
    st.markdown('<div class="custom-header">🏠 QC 스케줄 현황 대시보드</div>', unsafe_allow_html=True)
    df = conn.query("SELECT * FROM reception_logs", ttl="0")
    
    if df.empty:
        st.info("👋 환영합니다! 아직 등록된 데이터가 없습니다.")
    else:
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        today_receipts = len(df[df['reception_date'] == today_str])
        total_ongoing, unassigned, pending_coa_count = 0, 0, 0
        team_members = ["이지은", "차승희", "서유리", "이준호", "이현지", "임현진"]
        assignee_counts = {name: 0 for name in team_members}
        pending_coa_list = []

        for index, row in df.iterrows():
            try:
                assigns = row['assignments']
                if isinstance(assigns, str): assigns = json.loads(assigns)
                
                # [안전장치] 과거 엑셀 데이터(Legacy)는 대시보드 집계에서 무조건 제외
                if "Legacy Data" in assigns or row['coa_no'] == "엑셀이관": continue
                
                is_all_completed = True
                for test, info in assigns.items():
                    status = info.get("status", "진행중")
                    assignee = info.get("assignee", "미정")
                    if status == "진행중":
                        total_ongoing += 1
                        is_all_completed = False
                    if assignee == "미정" and status == "진행중": unassigned += 1
                    if status == "진행중" and assignee in assignee_counts: assignee_counts[assignee] += 1
                        
                coa_val = str(row['coa_no']).strip() if pd.notnull(row['coa_no']) else ""
                if is_all_completed and (coa_val == "" or coa_val == "-" or coa_val.lower() == "nan" or coa_val.lower() == "none"):
                    pending_coa_count += 1
                    pending_coa_list.append({"접수 일자": row['reception_date'], "의뢰 구분": row['category'], "품명": row['item_name'], "제조번호": row['batch_no']})
            except: continue
        
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric(label="📅 오늘 신규 접수", value=f"{today_receipts} 건")
        with col2: st.metric(label="⏳ 진행 중인 시험", value=f"{total_ongoing} 개")
        with col3: st.metric(label="⚠️ 미배정 시험", value=f"{unassigned} 개", delta="-조치 요망" if unassigned > 0 else "완벽 배정", delta_color="inverse" if unassigned > 0 else "normal")
        with col4: st.metric(label="📄 CoA 발행 대기", value=f"{pending_coa_count} 건", delta="-빠른 발행 요망" if pending_coa_count > 0 else "대기 없음", delta_color="inverse" if pending_coa_count > 0 else "normal")
            
        st.markdown("<hr style='margin-top: 15px; margin-bottom: 25px;'>", unsafe_allow_html=True)
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.markdown('<div class="sub-header" style="margin-top:0px;">🧑‍🔬 담당자별 진행 중인 시험 건수</div>', unsafe_allow_html=True)
            assignee_series = pd.Series(assignee_counts)
            if assignee_series.sum() > 0: st.bar_chart(assignee_series[assignee_series > 0], color="#FF9F68")
            else: st.info("현재 팀 내에 진행 중인 시험이 없습니다.")
        with chart_col2:
            st.markdown('<div class="sub-header" style="margin-top:0px;">📈 의뢰 구분별 접수 비율 (전체 누적)</div>', unsafe_allow_html=True)
            category_counts = df['category'].value_counts()
            if not category_counts.empty: st.bar_chart(category_counts, color="#5C8FB5")
            else: st.info("데이터가 충분하지 않습니다.")

        st.markdown('<div class="sub-header">🚨 CoA 성적서 발행 대기 목록</div>', unsafe_allow_html=True)
        if pending_coa_list: st.dataframe(pd.DataFrame(pending_coa_list), use_container_width=True, hide_index=True)
        else: st.success("✔️ 현재 밀려있는 CoA 발행 대기 건이 없습니다.")


# --- 📝 시험 접수 창 ---
elif selected == "시험 접수 및 배정":
    st.markdown('<div class="custom-header">📝 신규 시험 접수 및 배정</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        reception_date = st.date_input("접수 일자 (스케줄 기준일)", datetime.date.today())
        req_date = st.date_input("의뢰 일자 (의뢰서 작성일)", datetime.date.today())
        category = st.selectbox("시험 의뢰 구분", ["01. 원료", "02. 자재", "03. IPC", "04. IPM", "05. 세포주", "06. 완제의약품", "07. 수탁", "08. 기타"])
        item_name = st.selectbox("품명 (제품명 선택)", st.session_state.item_master)
        test_no = st.text_input("시험 번호 (예: RA2026-001)")
    with col2:
        item_code = st.text_input("품목 코드")
        batch_no = st.text_input("제조번호 (Batch No.)")
        in_no = st.text_input("입고등록번호")
        requester = st.text_input("의뢰자")

    st.markdown('<div class="sub-header">🧪 시험 의뢰 항목 선택</div>', unsafe_allow_html=True)
    group_options = ["직접 항목 선택"] + list(st.session_state.test_groups.keys())
    selected_group = st.selectbox("📌 묶음 항목 불러오기 (제품별 프리셋)", group_options)
    
    default_selections = []
    if selected_group != "직접 항목 선택":
        default_selections = [test for test in st.session_state.test_groups[selected_group] if test in all_available_tests]
    selected_tests = st.multiselect("수행할 시험 항목들을 선택하세요", all_available_tests, default=default_selections)

    st.markdown('<div class="sub-header">🧑‍🔬 담당 시험자 배정 (항목별)</div>', unsafe_allow_html=True)
    assignees = ["미정", "이지은", "차승희", "서유리", "이준호", "이현지", "임현진"]
    test_assignments = {} 
    if selected_tests:
        test_col1, test_col2 = st.columns(2)
        for i, test in enumerate(selected_tests):
            col = test_col1 if i % 2 == 0 else test_col2
            with col:
                assignee_name = st.selectbox(f"[{test}] 담당자", assignees, key=f"assign_{test}")
                test_assignments[test] = {"assignee": assignee_name, "status": "진행중", "result": {}, "pass_fail": "판정 전"}
    
    remarks = st.text_area("비고 (특이사항)")
    
    if st.button("✅ 접수 완료 및 스케줄 등록", type="primary", use_container_width=True):
        if not selected_tests: st.error("최소 1개 이상의 시험 항목을 선택해야 합니다.")
        else:
            try:
                tests_str = ", ".join(selected_tests)
                assignments_json = json.dumps(test_assignments, ensure_ascii=False) 
                
                with conn.session as s:
                    s.execute(
                        text("""
                        INSERT INTO reception_logs 
                        (reception_date, req_date, category, item_name, item_code, batch_no, in_no, requester, selected_tests, assignments, remarks, test_no, coa_no, judgment)
                        VALUES (:reception_date, :req_date, :category, :item_name, :item_code, :batch_no, :in_no, :requester, :selected_tests, :assignments, :remarks, :test_no, :coa_no, :judgment)
                        """),
                        {
                            "reception_date": str(reception_date), "req_date": str(req_date), "category": category,
                            "item_name": item_name, "item_code": item_code, "batch_no": batch_no, "in_no": in_no,
                            "requester": requester, "selected_tests": tests_str, "assignments": assignments_json,
                            "remarks": remarks, "test_no": test_no, "coa_no": "", "judgment": ""
                        }
                    )
                    s.commit()
                st.success("🎉 접수가 완료되었습니다!")
            except Exception as e: st.error(f"오류: {e}")


# --- 📁 접수 대장 조회 (🌟 기능 1: 과거 엑셀 데이터 Import 포함) ---
elif selected == "접수 대장 조회":
    st.markdown('<div class="custom-header">📂 시험 접수 대장 조회 및 데이터 관리</div>', unsafe_allow_html=True)
    
    # 🌟 [수정됨] expanded=True 를 추가하여 파일 업로드 후 화면이 새로고침돼도 창이 닫히지 않게 고정!
    with st.expander("📥 과거 엑셀/CSV 데이터 일괄 업로드 (Import) - 클릭하여 열기", expanded=True):
        st.info("이곳에 업로드된 데이터는 시스템 로직과 충돌하지 않도록 **'완료된 과거 데이터'**로 취급되어 대장 조회와 결과 조회 화면에만 나타납니다. (진행 중 카운트 및 결과 입력 창에는 반영되지 않습니다.)")
        
        # 템플릿 다운로드 제공 (실제 대장 컬럼과 100% 동일하게 매핑!)
        template_df = pd.DataFrame(columns=["접수 일자", "품명", "품목 코드", "제조번호", "입고등록번호", "의뢰 일자", "시험 의뢰 구분", "시험 의뢰 항목", "시험 번호", "의뢰자", "비고", "COA 발행 여부(성적번호)", "판정"])
        template_csv = template_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("1️⃣ 엑셀 업로드용 템플릿 양식 다운로드 (대장과 동일)", data=template_csv, file_name="Import_Template.csv", mime="text/csv")
        
        uploaded_file = st.file_uploader("2️⃣ 작성한 템플릿 파일(CSV)을 업로드하세요", type=["csv"])
        if uploaded_file is not None:
            try:
                # 🌟 [수정됨] 메모리 버퍼 방식으로 파일 읽기 강화 (인코딩 및 읽기 에러 완벽 차단)
                bytes_data = uploaded_file.getvalue()
                try:
                    import_df = pd.read_csv(io.BytesIO(bytes_data), encoding='utf-8-sig')
                except UnicodeDecodeError:
                    import_df = pd.read_csv(io.BytesIO(bytes_data), encoding='cp949')
                    
                st.success(f"✅ 파일을 성공적으로 읽었습니다! (총 {len(import_df)}건의 데이터 확인)")
                
                # 버튼을 화면 꽉 차게 눈에 잘 띄도록 수정
                if st.button("🚀 데이터 일괄 업로드 실행", type="primary", use_container_width=True):
                    with conn.session as s:
                        for _, row in import_df.iterrows():
                            # 과거 데이터 방어용 더미 JSON
                            dummy_assigns = json.dumps({"Legacy Data": {"status": "완료", "pass_fail": str(row.get('판정', ''))}}, ensure_ascii=False)
                            s.execute(
                                text("""
                                INSERT INTO reception_logs 
                                (reception_date, req_date, category, item_name, item_code, batch_no, in_no, requester, selected_tests, assignments, remarks, test_no, coa_no, judgment)
                                VALUES (:reception_date, :req_date, :category, :item_name, :item_code, :batch_no, :in_no, :requester, :selected_tests, :assignments, :remarks, :test_no, :coa_no, :judgment)
                                """),
                                {
                                    "reception_date": str(row.get('접수 일자', '')), "req_date": str(row.get('의뢰 일자', '')), "category": str(row.get('시험 의뢰 구분', '')),
                                    "item_name": str(row.get('품명', '')), "item_code": str(row.get('품목 코드', '')), "batch_no": str(row.get('제조번호', '')), 
                                    "in_no": str(row.get('입고등록번호', '')), "requester": str(row.get('의뢰자', '')), "selected_tests": str(row.get('시험 의뢰 항목', '')), 
                                    "assignments": dummy_assigns, "remarks": str(row.get('비고', '')), 
                                    "test_no": str(row.get('시험 번호', '-')), "coa_no": str(row.get('COA 발행 여부(성적번호)', '엑셀이관')), "judgment": str(row.get('판정', ''))
                                }
                            )
                        s.commit()
                    st.session_state.flash_msgs.append((f"🎉 {len(import_df)}건의 과거 데이터가 성공적으로 대장에 등록되었습니다!", 'success'))
                    st.rerun()
            except Exception as e:
                st.error(f"업로드 중 오류가 발생했습니다. 양식을 다시 확인해주세요. (에러: {e})")
        
        # 🌟 [신규 추가] 테스트 데이터 일괄 초기화 버튼
        st.markdown("---")
        st.markdown("💡 **테스트 업로드를 지우고 싶으신가요?** 아래 버튼을 누르면 엑셀로 업로드했던 데이터만 한 번에 싹 지워집니다. (직접 수기로 접수한 진짜 데이터는 안전합니다!)")
        if st.button("🗑️ 엑셀 업로드 데이터(엑셀이관) 전체 일괄 삭제", type="secondary"):
            with conn.session as s:
                s.execute(text("DELETE FROM reception_logs WHERE coa_no = '엑셀이관'"))
                s.commit()
            st.session_state.flash_msgs.append(("🗑️ 엑셀로 업로드된 테스트 데이터가 모두 초기화되었습니다.", 'info'))
            st.rerun()

    st.markdown("---")
    df = conn.query("SELECT * FROM reception_logs ORDER BY id DESC", ttl="0")
    
    if df.empty: st.info("아직 등록된 내역이 없습니다.")
    else:
        df['test_no'] = df['test_no'].fillna("-")
        df['coa_no'] = df['coa_no'].fillna("-")
        df['judgment'] = df['judgment'].fillna("")
        df.loc[df['coa_no'] == "", 'coa_no'] = "-"
        df.loc[df['judgment'] == "", 'judgment'] = "-"
        
        df_display = df[['id', 'item_name', 'item_code', 'batch_no', 'in_no', 'req_date', 'category', 'selected_tests', 'test_no', 'requester', 'remarks', 'coa_no', 'judgment']]
        df_display.columns = ['번호', '품명', '품목 코드', '제조번호', '입고등록번호', '의뢰 일자', '시험 의뢰 구분', '시험 의뢰 항목', '시험 번호', '의뢰자', '비고', 'COA 발행 여부(성적번호)', '판정']
        
        st.markdown('<div class="sub-header" style="margin-top:0px;">🔍 맞춤형 대장 필터</div>', unsafe_allow_html=True)
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        with col_f1: sel_cat = st.selectbox("📌 의뢰 구분", ["전체"] + sorted(df_display['시험 의뢰 구분'].unique().tolist()))
        with col_f2: sel_item = st.multiselect("📦 품명 선택", sorted(df_display['품명'].unique().tolist()))
        with col_f3: sel_batch = st.multiselect("🔢 제조번호 선택", sorted(df_display['제조번호'].unique().tolist()))
        with col_f4: sel_jdg = st.multiselect("⚖️ 최종 판정 여부", sorted(df_display['판정'].unique().tolist()))
        
        if sel_cat != "전체": df_display = df_display[df_display['시험 의뢰 구분'] == sel_cat]
        if sel_item: df_display = df_display[df_display['품명'].isin(sel_item)]
        if sel_batch: df_display = df_display[df_display['제조번호'].isin(sel_batch)]
        if sel_jdg: df_display = df_display[df_display['판정'].isin(sel_jdg)]
            
        st.write("")
        def highlight_fail_row(row):
            if row['판정'] == '부적합': return ['background-color: #FFE6E6; color: #D8000C; font-weight: bold'] * len(row)
            return [''] * len(row)
            
        styled_df = df_display.style.apply(highlight_fail_row, axis=1)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        csv = df_display.to_csv(index=False).encode('utf-8-sig') 
        st.download_button("📥 현재 화면의 대장 엑셀(CSV) 다운로드", data=csv, file_name="QC_시험접수대장.csv", mime="text/csv")
        
        # 🌟 [신규 추가] 개별 데이터 수정/삭제 UI
        st.markdown("---")
        st.markdown('<div class="sub-header">⚙️ 개별 접수 내역 수정 및 취소(삭제)</div>', unsafe_allow_html=True)
        with st.expander("데이터 수정 또는 개별 삭제를 원하시면 여기를 클릭하세요."):
            edit_options = df['id'].astype(str) + " - " + df['item_name'] + " (" + df['reception_date'] + ")"
            selected_edit = st.selectbox("수정/삭제할 접수 건을 선택하세요", ["선택 안 함"] + edit_options.tolist())
            if selected_edit != "선택 안 함":
                target_id = selected_edit.split(" - ")[0]
                target_row = df[df['id'] == int(target_id)].iloc[0]
                with st.form("edit_form"):
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        new_item = st.selectbox("품명 (변경)", st.session_state.item_master, index=st.session_state.item_master.index(target_row['item_name']) if target_row['item_name'] in st.session_state.item_master else 0)
                        new_batch = st.text_input("제조번호", value=target_row['batch_no'] if target_row['batch_no'] else "")
                    with col_e2:
                        new_test_no = st.text_input("시험번호", value=target_row['test_no'] if target_row['test_no'] != "-" else "")
                        new_remark = st.text_input("비고", value=target_row['remarks'] if target_row['remarks'] else "")
                    
                    btn_e1, btn_e2 = st.columns(2)
                    with btn_e1:
                        if st.form_submit_button("🔄 수정 완료", type="primary"):
                            with conn.session as s:
                                s.execute(text("UPDATE reception_logs SET item_name=:it, batch_no=:ba, test_no=:te, remarks=:re WHERE id=:id"),
                                          {"it": new_item, "ba": new_batch, "te": new_test_no, "re": new_remark, "id": target_id})
                                s.commit()
                            st.session_state.flash_msgs.append(("수정이 완료되었습니다.", "success"))
                            st.rerun()
                    with btn_e2:
                        if st.form_submit_button("🗑️ 접수 취소(삭제)"):
                            with conn.session as s:
                                s.execute(text("DELETE FROM reception_logs WHERE id=:id"), {"id": target_id})
                                s.commit()
                            st.session_state.flash_msgs.append(("해당 데이터가 삭제되었습니다.", "success"))
                            st.rerun()

# --- 📅 전체 스케줄 보드 창 ---
elif selected == "전체 스케줄 보드":
    st.markdown('<div class="custom-header">📅 QC 시험 스케줄 보드</div>', unsafe_allow_html=True)
    df = conn.query("SELECT * FROM reception_logs", ttl="0")
    
    all_items = sorted(df['item_name'].dropna().unique().tolist())
    all_batches = sorted(df['batch_no'].dropna().unique().tolist())
    all_assignees = set()
    all_tests = set()
    
    for _, row in df.iterrows():
        try:
            assigns = row['assignments']
            if isinstance(assigns, str): assigns = json.loads(assigns)
            if "Legacy Data" in assigns: continue # 엑셀 수입 데이터는 달력에서 제외
            for t, val in assigns.items():
                all_tests.add(t)
                all_assignees.add(val.get("assignee", "미정"))
        except: pass
        
    all_assignees = sorted(list(all_assignees))
    all_tests = sorted(list(all_tests))

    with st.expander("🔍 달력 상세 검색 및 필터링 (클릭하여 열기)", expanded=False):
        f_col1, f_col2, f_col3, f_col4, f_col5 = st.columns(5)
        with f_col1: sel_items = st.multiselect("📦 제품명", all_items)
        with f_col2: sel_batches = st.multiselect("🔢 제조번호", all_batches)
        with f_col3: sel_assignees = st.multiselect("🧑‍🔬 시험자", all_assignees)
        with f_col4: sel_tests = st.multiselect("🧪 시험항목", all_tests)
        with f_col5: sel_status = st.multiselect("✅ 완료 여부", ["진행중", "완료"])

    calendar_events = []
    summary = {}
    def get_product_color(product_name):
        palette = ["#5C8FB5", "#A680B8", "#C9A66B", "#D98080", "#7A9E9F", "#6D8299", "#B2AD7F", "#B39C82", "#E8A598", "#7D9D9C"]
        hash_val = sum(ord(c) for c in product_name)
        return palette[hash_val % len(palette)]

    for _, row in df.iterrows():
        r_id, r_date, r_item, r_batch = row['id'], row['reception_date'], row['item_name'], row['batch_no']
        if sel_items and r_item not in sel_items: continue
        if sel_batches and r_batch not in sel_batches: continue
        try:
            assigns = row['assignments']
            if isinstance(assigns, str): assigns = json.loads(assigns)
            if "Legacy Data" in assigns: continue
        except: continue

        filtered_assignments = {}
        for test, info in assigns.items():
            assignee = info.get("assignee", "미정")
            status = info.get("status", "진행중")
            if sel_assignees and assignee not in sel_assignees: continue
            if sel_tests and test not in sel_tests: continue
            if sel_status and status not in sel_status: continue
            filtered_assignments[test] = {"assignee": assignee, "status": status}
            
        if not filtered_assignments: continue
        
        group_key = f"{r_date}:::{r_item}:::{r_batch}:::{r_id}"
        summary[group_key] = {
            "date": r_date, "item": r_item, "batch": r_batch, "total": len(filtered_assignments), "done": 0, "tests": filtered_assignments
        }
        for t, info in filtered_assignments.items():
            if info["status"] == "완료": summary[group_key]["done"] += 1

    sorted_summary = sorted(summary.items(), key=lambda x: (x[1]['date'], x[1]['item']))
    group_idx = 0
    for g_key, data in sorted_summary:
        group_idx += 1
        base_sort = group_idx * 100 
        product_color = get_product_color(data["item"])
        
        if g_key in st.session_state.expanded_groups:
            calendar_events.append({
                "id": f"COLLAPSE:::{g_key}", "title": f"📂 [{data['item']}] 상세 숨기기", "start": data["date"],
                "backgroundColor": product_color, "borderColor": product_color, "textColor": "white", "sort_order": base_sort 
            })
            test_idx = 1
            for test, info in data["tests"].items():
                assignee = info["assignee"]
                status = info["status"]
                test_bg_color = "#88B04B" if status == "완료" else "#FF9F68"
                status_icon = "✅" if status == "완료" else "⏳"
                calendar_events.append({
                    "id": f"TEST:::{g_key}:::{test}", "title": f"{status_icon} {test} - {assignee}", "start": data["date"],
                    "backgroundColor": test_bg_color, "borderColor": test_bg_color, "textColor": "white", "sort_order": base_sort + test_idx 
                })
                test_idx += 1
        else:
            title = f"✅ [{data['item']}] 시험 완료" if data["total"] == data["done"] else f"⏳ [{data['item']}] 진행중 ({data['done']}/{data['total']})"
            calendar_events.append({
                "id": f"GROUP:::{g_key}", "title": title, "start": data["date"],
                "backgroundColor": product_color, "borderColor": product_color, "textColor": "white", "sort_order": base_sort
            })
            
    calendar_options = {
        "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,dayGridWeek,listWeek"},
        "initialView": "dayGridMonth", "locale": "ko", "height": 750, "eventOrder": "start,sort_order" 
    }
    cal_result = calendar(events=calendar_events, options=calendar_options)

    if cal_result.get("callback") == "eventClick":
        clicked_id = cal_result["eventClick"]["event"].get("id", "")
        if st.session_state.last_clicked_event != clicked_id:
            st.session_state.last_clicked_event = clicked_id
            if clicked_id.startswith("GROUP:::"):
                st.session_state.expanded_groups.add(clicked_id.replace("GROUP:::", ""))
                st.rerun() 
            elif clicked_id.startswith("COLLAPSE:::"):
                st.session_state.expanded_groups.discard(clicked_id.replace("COLLAPSE:::", ""))
                st.rerun()


# --- ✅ 결과 입력 (CoA) 창 ---
elif selected == "결과 입력 (CoA)":
    st.markdown('<div class="custom-header">✅ 시험 결과 입력 및 CoA 발행</div>', unsafe_allow_html=True)
    st.write("💡 실제 결과값(Raw Data)과 판정(적합/부적합)을 입력하세요.")
    
    # [방어 로직] coa_no가 없거나 비어있는 진짜 '진행 중' 데이터만 불러오기 (엑셀 이관 데이터 제외)
    df = conn.query("SELECT id, reception_date, item_name, assignments, coa_no, test_no, batch_no FROM reception_logs WHERE (coa_no IS NULL OR coa_no = '') AND (coa_no != '엑셀이관') ORDER BY id DESC", ttl="0")
    
    if df.empty: st.info("현재 대기 중이거나 진행 중인 시험 내역이 없습니다.")
        
    for _, row in df.iterrows():
        r_id, date, item, assigns_data, coa_no, test_no_val, batch_val = row['id'], row['reception_date'], row['item_name'], row['assignments'], row['coa_no'], row['test_no'], row['batch_no']
        
        try:
            if isinstance(assigns_data, str): assignments = json.loads(assigns_data)
            else: assignments = assigns_data
            
            # 방어 로직 (엑셀 데이터가 실수로 잡히지 않도록)
            if "Legacy Data" in assignments: continue
            
            for t, val in assignments.items():
                if "pass_fail" not in val: val["pass_fail"] = "판정 전"
                
            all_completed = all(info.get("status", "진행중") == "완료" for info in assignments.values())
            box_title = f"✅ [{date}] {item} ({batch_val}) - 모두 완료 (CoA 대기)" if all_completed else f"⏳ [{date}] {item} ({batch_val}) - 진행 중"
            
            with st.expander(box_title, expanded=not all_completed):
                for test, info in assignments.items():
                    status = info.get("status", "진행중")
                    assignee = info.get("assignee", "미정")
                    result_dict = info.get("result", {})
                    pass_fail = info.get("pass_fail", "판정 전")
                    
                    pf_color = "#E74C3C" if pass_fail == "부적합" else "#2C3E50"
                    pf_text = f" - <span style='color:{pf_color}; font-weight:bold;'>[{pass_fail}]</span>" if pass_fail != "판정 전" else ""
                    st.markdown(f"**🧪 {test}** (담당: {assignee}){pf_text}", unsafe_allow_html=True)
                    
                    if status == "진행중":
                        with st.form(key=f"form_{r_id}_{test}"):
                            res_inputs = {}
                            master_params = st.session_state.test_master.get(test, [])
                            
                            if master_params:
                                for i in range(0, len(master_params), 4):
                                    cols = st.columns(4)
                                    for j in range(4):
                                        if i + j < len(master_params):
                                            param = master_params[i + j]
                                            res_inputs[param] = cols[j].text_input(param, key=f"inp_{r_id}_{test}_{param}")
                            else:
                                res_inputs["단일결과"] = st.text_input("결과값 입력 (숫자 또는 판정)", placeholder="예: 98.5, ND 등")
                                
                            st.write("")
                            new_pf = st.radio("이 항목의 판정을 선택하세요", ["판정 전", "적합", "부적합"], index=["판정 전", "적합", "부적합"].index(pass_fail), horizontal=True, key=f"rad_{r_id}_{test}")
                            
                            btn_c1, btn_c2 = st.columns(2)
                            save_temp = btn_c1.form_submit_button("💾 판정/결과 임시 저장")
                            save_comp = btn_c2.form_submit_button("✔️ 시험 완료 처리", type="primary")
                            
                            if save_temp or save_comp:
                                n_stat = "완료" if save_comp else "진행중"
                                current_inputs = {}
                                
                                has_tntc = False
                                for k, v in res_inputs.items():
                                    val = v.strip()
                                    if not val: continue
                                    
                                    if val.upper() in ["ND", "불검출", "NOT DETECTED"]:
                                        current_inputs[k] = "0"
                                        st.session_state.flash_msgs.append((f"[{k}] 'ND/불검출' 입력이 감지되어 통계를 위해 '0'으로 자동 변환되었습니다.", 'info'))
                                    elif val.upper() == "TNTC":
                                        current_inputs[k] = "TNTC"
                                        has_tntc = True
                                        st.session_state.flash_msgs.append((f"[{k}] 'TNTC' 입력이 감지되었습니다. OOS 조사를 준비하세요.", 'error'))
                                    else:
                                        current_inputs[k] = val
                                        if n_stat == "완료":
                                            trend_msg = check_adverse_trend(item, test, k, val)
                                            if trend_msg: st.session_state.flash_msgs.append((trend_msg, 'warning'))

                                assignments[test] = {"assignee": assignee, "status": n_stat, "result": current_inputs, "pass_fail": new_pf}
                                
                                with conn.session as s:
                                    s.execute(text("UPDATE reception_logs SET assignments=:ass WHERE id=:id"), {"ass": json.dumps(assignments, ensure_ascii=False), "id": r_id})
                                    s.commit()
                                st.rerun()
                    else:
                        res_str = " / ".join([f"{k}: {v}" for k, v in result_dict.items() if v])
                        if res_str: st.success(f"입력된 결과 ➡️ {res_str}")
                        if st.button("↩️ 수정하기 (진행중으로 되돌리기)", key=f"revert_{r_id}_{test}"):
                            assignments[test] = {"assignee": assignee, "status": "진행중", "result": result_dict, "pass_fail": pass_fail}
                            with conn.session as s:
                                s.execute(text("UPDATE reception_logs SET assignments=:ass WHERE id=:id"), {"ass": json.dumps(assignments, ensure_ascii=False), "id": r_id})
                                s.commit()
                            st.rerun()
                    st.write("")
                
                st.markdown("---")
                if all_completed:
                    st.write("🎉 **모든 시험 항목이 완료되었습니다. CoA 성적서를 발행해 주세요.**")
                    col_c1, col_c2, col_c3 = st.columns([3, 2, 2])
                    new_coa_no = col_c1.text_input("발행할 CoA 번호 입력 (예: DWCOA26-001)", key=f"coa_{r_id}")
                    final_jdg = col_c2.radio("⚖️ 제품 최종 판정", ["적합", "부적합"], horizontal=True, key=f"fjdg_{r_id}")
                    
                    if col_c3.button("📄 CoA 성적서 발행 완료", key=f"coa_btn_{r_id}", type="primary"):
                        if new_coa_no:
                            with conn.session as s:
                                s.execute(text("UPDATE reception_logs SET coa_no=:coa, judgment=:jdg WHERE id=:id"), {"coa": new_coa_no, "jdg": final_jdg, "id": r_id})
                                s.commit()
                            st.success("CoA 발행 및 최종 판정이 완료되어 대장에 등록되었습니다!")
                            st.rerun()
                        else: st.error("성적번호를 입력하세요.")
        except: pass


# --- 🔎 시험 결과 조회 (🌟 기능 2: 완료된 시험 상세 조회) ---
elif selected == "시험 결과 조회":
    st.markdown('<div class="custom-header">🔎 시험 결과 및 판정 상세 조회</div>', unsafe_allow_html=True)
    st.write("발행 완료된 성적서(CoA) 및 과거 데이터를 기반으로 각 품목의 최종 결과와 세부 시험 항목의 결과를 조회합니다.")
    
    # CoA가 발행되었거나 엑셀로 이관된(완료된) 데이터만 가져오기
    df = conn.query("SELECT * FROM reception_logs WHERE coa_no IS NOT NULL AND coa_no != '' AND coa_no != '-' ORDER BY id DESC", ttl="0")
    
    if df.empty:
        st.info("현재 조회가 가능한 완료된 시험 데이터가 없습니다.")
    else:
        # 상단 필터부
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)
        with col_s1: search_item = st.multiselect("📦 품명 선택", sorted(df['item_name'].dropna().unique().tolist()))
        with col_s2: search_testno = st.multiselect("🏷️ 시험번호 선택", sorted(df[df['test_no'] != '-']['test_no'].dropna().unique().tolist()))
        with col_s3: search_batch = st.multiselect("🔢 제조번호 선택", sorted(df['batch_no'].dropna().unique().tolist()))
        with col_s4: search_inno = st.multiselect("📥 입고번호 선택", sorted(df['in_no'].dropna().unique().tolist()))

        if search_item: df = df[df['item_name'].isin(search_item)]
        if search_testno: df = df[df['test_no'].isin(search_testno)]
        if search_batch: df = df[df['batch_no'].isin(search_batch)]
        if search_inno: df = df[df['in_no'].isin(search_inno)]

        st.markdown("---")
        st.markdown(f"**총 {len(df)}건의 완료된 데이터를 찾았습니다.**")
        
        for _, row in df.iterrows():
            item = row['item_name']
            batch = row['batch_no']
            test_no = row['test_no']
            in_no = row['in_no']
            coa_no = row['coa_no']
            jdg = row['judgment']
            
            # 판정 색상 부여
            jdg_color = "red" if jdg == "부적합" else "green"
            
            with st.expander(f"📄 [{item}] 제조번호: {batch} | 성적번호: {coa_no} | 판정: {jdg}"):
                c1, c2, c3, c4 = st.columns(4)
                c1.write(f"**시험번호:** {test_no}")
                c2.write(f"**입고번호:** {in_no}")
                c3.write(f"**접수일자:** {row['reception_date']}")
                c4.markdown(f"**최종판정:** <span style='color:{jdg_color}; font-weight:bold;'>{jdg}</span>", unsafe_allow_html=True)
                
                st.markdown("<hr style='margin:10px 0px;'>", unsafe_allow_html=True)
                
                try:
                    assigns = row['assignments']
                    if isinstance(assigns, str): assigns = json.loads(assigns)
                    
                    if "Legacy Data" in assigns:
                        st.info("📌 엑셀에서 이관된 과거 데이터이므로 세부 결과(Raw Data)는 원본 엑셀을 참조하세요.")
                    else:
                        result_list = []
                        for t_name, info in assigns.items():
                            assignee = info.get("assignee", "-")
                            pf = info.get("pass_fail", "-")
                            res_dict = info.get("result", {})
                            res_str = " / ".join([f"{k}: {v}" for k, v in res_dict.items() if v])
                            result_list.append({"시험항목": t_name, "담당자": assignee, "입력 결과(Raw Data)": res_str, "항목별 판정": pf})
                        
                        if result_list:
                            res_df = pd.DataFrame(result_list)
                            st.dataframe(res_df, use_container_width=True, hide_index=True)
                except:
                    st.write("세부 데이터 파싱 오류")


# --- 📈 PQR 경향 분석 ---
elif selected == "PQR 경향 분석":
    st.markdown('<div class="custom-header">📈 PQR 제품 품질 경향 분석 (관리도 & Cpk)</div>', unsafe_allow_html=True)
    df = conn.query("SELECT reception_date, batch_no, item_name, assignments FROM reception_logs WHERE coa_no IS NOT NULL AND coa_no != '' AND coa_no != '-' ORDER BY reception_date ASC", ttl="0")
    
    if df.empty: st.info("현재 PQR 분석을 수행할 수 있는 완료된(CoA 발행) 데이터가 없습니다.")
    else:
        product_list = df['item_name'].unique().tolist()
        selected_prod = st.selectbox("📊 분석할 제품을 선택하세요 (품명)", product_list)
        df_prod = df[df['item_name'] == selected_prod]
        available_params = []
        for idx, row in df_prod.iterrows():
            try:
                assigns = row['assignments']
                if isinstance(assigns, str): assigns = json.loads(assigns)
                if "Legacy Data" in assigns: continue # 엑셀 데이터는 PQR 통계에서 제외
                for t_name, info in assigns.items():
                    res_dict = info.get("result", {})
                    if isinstance(res_dict, dict):
                        for sub_k, sub_v in res_dict.items():
                            try:
                                float(sub_v)
                                param_str = f"[{t_name}] {sub_k}"
                                if param_str not in available_params: available_params.append(param_str)
                            except: pass
            except: pass
            
        if not available_params: st.warning("선택한 제품에 숫자로 입력된 결과값이 없어 트렌드 그래프를 그릴 수 없습니다.")
        else:
            selected_param = st.selectbox("🔬 트렌드를 분석할 시험 항목을 선택하세요", available_params)
            target_test = selected_param.split("] ")[0].replace("[", "")
            target_sub = selected_param.split("] ")[1]
            plot_data = []
            for idx, row in df_prod.iterrows():
                try:
                    assigns = row['assignments']
                    if isinstance(assigns, str): assigns = json.loads(assigns)
                    if target_test in assigns:
                        val = assigns[target_test].get("result", {}).get(target_sub)
                        if val is not None: plot_data.append({"Batch": row['batch_no'], "Date": row['reception_date'], "Value": float(val)})
                except: pass
            df_plot = pd.DataFrame(plot_data)
            
            if len(df_plot) < 2: st.info("데이터 포인트가 최소 2개(2개 배치) 이상이어야 관리도와 통계를 계산할 수 있습니다.")
            else:
                mean_val = df_plot["Value"].mean()
                std_val = df_plot["Value"].std()
                ucl = mean_val + (3 * std_val)
                lcl = mean_val - (3 * std_val)
                df_plot["Mean"] = mean_val; df_plot["UCL (평균+3σ)"] = ucl; df_plot["LCL (평균-3σ)"] = lcl
                st.markdown("---")
                col_c1, col_c2 = st.columns([7, 3])
                with col_c1:
                    st.markdown(f"**📉 {selected_prod} - {selected_param} 관리도 (Control Chart)**")
                    chart_data = df_plot.set_index("Batch")[["Value", "Mean", "UCL (평균+3σ)", "LCL (평균-3σ)"]]
                    st.line_chart(chart_data, color=["#FF9F68", "#BDBDBD", "#E74C3C", "#E74C3C"])
                with col_c2:
                    st.markdown("**통계 요약**")
                    st.write(f"- **배치 수:** {len(df_plot)} 개")
                    st.write(f"- **평균:** {mean_val:.3f}")
                    st.write(f"- **표준편차:** {std_val:.3f}")
                    st.markdown("<br><b>공정능력지수 (Cpk)</b>", unsafe_allow_html=True)
                    usl = st.number_input("규격 상한 (USL)", value=float(mean_val + std_val*5))
                    lsl = st.number_input("규격 하한 (LSL)", value=float(mean_val - std_val*5))
                    if std_val > 0:
                        cpk = min((usl - mean_val) / (3 * std_val), (mean_val - lsl) / (3 * std_val))
                        st.metric("Cpk 값", f"{cpk:.2f}", delta="양호" if cpk >= 1.33 else "개선필요", delta_color="normal" if cpk >= 1.33 else "inverse")
                    else: st.write("표준편차가 0이어서 계산할 수 없습니다.")

# --- ⚙️ 설정 메뉴 ---
elif selected == "설정":
    st.markdown('<div class="custom-header">⚙️ 시스템 설정</div>', unsafe_allow_html=True)
    tab1, tab2, tab3, tab4 = st.tabs(["🧪 시험 항목/그룹 관리", "👤 사용자 관리", "⚙️ 세부 파라미터 마스터", "📦 품명(제품명) 마스터"])
    
    with tab1:
        st.markdown('<div class="sub-header">1. 새로운 시험 항목 추가</div>', unsafe_allow_html=True)
        col_t1, col_t2 = st.columns([3, 1])
        with col_t1: new_test = st.text_input("새로운 시험 항목 이름 입력", label_visibility="collapsed")
        with col_t2:
            if st.button("➕ 항목 추가", use_container_width=True):
                if new_test and new_test not in st.session_state.custom_tests and new_test not in base_tests:
                    st.session_state.custom_tests.append(new_test)
                    st.rerun()
        st.markdown("---")
        st.markdown('<div class="sub-header">2. 그룹(묶음) 만들기 / 삭제</div>', unsafe_allow_html=True)
        new_group_name = st.text_input("새 그룹 이름")
        new_group_items = st.multiselect("이 그룹에 포함될 시험 항목 선택", all_available_tests)
        if st.button("💾 새 그룹 저장"):
            if new_group_name and new_group_items:
                st.session_state.test_groups[new_group_name] = new_group_items
                st.rerun()

    with tab2: st.write("추후 개발 예정 (부서원 추가 등)")
        
    with tab3:
        st.markdown('<div class="sub-header">시험 항목별 세부 결과(파라미터) 설정</div>', unsafe_allow_html=True)
        selected_master_test = st.selectbox("파라미터를 설정할 시험 항목 선택", all_available_tests)
        current_params = st.session_state.test_master.get(selected_master_test, [])
        params_str = st.text_input("하위 파라미터 입력 (쉼표로 구분)", value=", ".join(current_params))
        if st.button("💾 마스터 설정 저장", type="primary"):
            if params_str.strip(): st.session_state.test_master[selected_master_test] = [p.strip() for p in params_str.split(",") if p.strip()]
            else:
                if selected_master_test in st.session_state.test_master: del st.session_state.test_master[selected_master_test]
            st.rerun()
            
    with tab4:
        st.markdown('<div class="sub-header">📦 접수용 품명(제품명) 목록 관리</div>', unsafe_allow_html=True)
        new_item_master = st.text_input("새로 등록할 품명(제품명) 입력")
        if st.button("➕ 품명 목록에 추가하기"):
            if new_item_master and new_item_master not in st.session_state.item_master:
                st.session_state.item_master.append(new_item_master)
                st.rerun()
        st.markdown("---")
        del_item_master = st.selectbox("삭제할 품명을 선택하세요", ["선택 안 함"] + st.session_state.item_master)
        if st.button("🗑️ 선택한 품명 삭제"):
            if del_item_master != "선택 안 함":
                st.session_state.item_master.remove(del_item_master)
                st.rerun()
