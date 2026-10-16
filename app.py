import streamlit as st
import datetime as dt
import pandas as pd
import re
from supabase import create_client
from streamlit_cropper import st_cropper
from streamlit_paste_button import paste_image_button as pbutton
from PIL import Image
import io
import numpy as np

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

INTERVALS = [1, 2, 4, 7, 15, 30]

# ==================== 错题集 ====================
def add_mistake(subject, question, answer, analysis, tags, image_url="", image_url2=""):
    today = dt.date.today()
    next_review = today + dt.timedelta(days=INTERVALS[0])
    supabase.table("mistakes").insert({
        "subject": subject, "question": question, "answer": answer,
        "analysis": analysis, "tags": tags,
        "image_url": image_url, "image_url2": image_url2,
        "stage": 0, "next_review": next_review.isoformat()
    }).execute()

def get_due_today():
    today = dt.date.today().isoformat()
    res = supabase.table("mistakes").select("*").lte("next_review", today).order("next_review").execute()
    return pd.DataFrame(res.data)

def get_all_mistakes():
    res = supabase.table("mistakes").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data)

def review_mistake(mid, correct):
    res = supabase.table("mistakes").select("stage,wrong_count").eq("id", mid).execute()
    row = res.data[0]
    stage, wrong_count = row["stage"], row["wrong_count"]
    if correct:
        stage += 1
        if stage >= len(INTERVALS):
            next_date = dt.date.today() + dt.timedelta(days=365)
        else:
            next_date = dt.date.today() + dt.timedelta(days=INTERVALS[stage])
    else:
        stage = 0
        wrong_count += 1
        next_date = dt.date.today() + dt.timedelta(days=INTERVALS[0])
    supabase.table("mistakes").update({
        "stage": stage, "next_review": next_date.isoformat(), "wrong_count": wrong_count
    }).eq("id", mid).execute()

def update_mistake(mid, subject, question, answer, analysis, tags):
    supabase.table("mistakes").update({
        "subject": subject, "question": question, "answer": answer,
        "analysis": analysis, "tags": tags
    }).eq("id", mid).execute()

def delete_mistake(mid):
    supabase.table("mistakes").delete().eq("id", mid).execute()

def upload_image_bytes(img_bytes, filename):
    path = str(dt.datetime.now().timestamp()) + "_" + filename
    supabase.storage.from_("mistake-images").upload(path, img_bytes, {"content-type": "image/png"})
    return supabase.storage.from_("mistake-images").get_public_url(path)

# ==================== 记忆卡 ====================
def add_flashcard(chapter, front, back, tags=""):
    today = dt.date.today()
    next_review = today + dt.timedelta(days=INTERVALS[0])
    supabase.table("flashcards").insert({
        "chapter": chapter, "front": front, "back": back, "tags": tags,
        "stage": 0, "next_review": next_review.isoformat(),
        "wrong_count": 0, "learned": False
    }).execute()

def get_new_cards(limit):
    """没学过的卡"""
    res = supabase.table("flashcards").select("*").eq("learned", False).order("id").limit(limit).execute()
    return pd.DataFrame(res.data)

def get_review_cards(chapter_filter=None):
    """学过 + 今天到期的"""
    today = dt.date.today().isoformat()
    q = supabase.table("flashcards").select("*").eq("learned", True).lte("next_review", today).order("next_review")
    if chapter_filter and chapter_filter != "全部":
        q = q.eq("chapter", chapter_filter)
    res = q.execute()
    return pd.DataFrame(res.data)

def get_all_cards():
    res = supabase.table("flashcards").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data)

def count_new_remaining():
    res = supabase.table("flashcards").select("id", count="exact").eq("learned", False).execute()
    return res.count if res.count is not None else 0

def review_card(cid, result):
    """result: forget | fuzzy | remember"""
    res = supabase.table("flashcards").select("stage,wrong_count").eq("id", cid).execute()
    row = res.data[0]
    stage, wrong_count = row["stage"], row["wrong_count"]

    if result == "remember":
        stage += 1
        if stage >= len(INTERVALS):
            next_date = dt.date.today() + dt.timedelta(days=365)
        else:
            next_date = dt.date.today() + dt.timedelta(days=INTERVALS[stage])
    else:
        stage = 0
        wrong_count += 1
        next_date = dt.date.today() + dt.timedelta(days=INTERVALS[0])

    supabase.table("flashcards").update({
        "stage": stage,
        "next_review": next_date.isoformat(),
        "wrong_count": wrong_count,
        "learned": True
    }).eq("id", cid).execute()

def update_card(cid, chapter, front, back, tags):
    supabase.table("flashcards").update({
        "chapter": chapter, "front": front, "back": back, "tags": tags
    }).eq("id", cid).execute()

def delete_card(cid):
    supabase.table("flashcards").delete().eq("id", cid).execute()

# ==================== 设置 ====================
def get_daily_limit():
    res = supabase.table("settings").select("daily_new_limit").eq("id", 1).execute()
    if res.data:
        return res.data[0]["daily_new_limit"]
    return 20

def set_daily_limit(n):
    supabase.table("settings").update({"daily_new_limit": n}).eq("id", 1).execute()

# ==================== 解析文本 ====================
def parse_cards_text(raw_text):
    cards = []
    current_chapter = "未分类"
    blocks = re.split(r'\n?===\n?', raw_text.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        ch_match = re.search(r'###\s*(.+)', block)
        if ch_match:
            current_chapter = ch_match.group(1).strip()
            block = re.sub(r'###.*\n?', '', block).strip()
        if not block:
            continue
        parts = re.split(r'\n?---\n?', block)
        if len(parts) < 2:
            continue
        front = parts[0].strip()
        back = " ".join(parts[1:]).strip()
        if front and back:
            cards.append((current_chapter, front, back))
    return cards

def replace_blanks(text):
    answers = re.findall(r'\[F#\d+#(.+?)\]', text)
    display = re.sub(r'\[F#\d+#(.+?)\]', '______', text)
    return display, answers

def fill_blanks_step_by_step(text, shown_count):
    answers = re.findall(r'\[F#\d+#(.+?)\]', text)
    counter = [0]
    def repl(m):
        if counter[0] < shown_count:
            counter[0] += 1
            return m.group(1)
        else:
            counter[0] += 1
            return '______'
    display = re.sub(r'\[F#\d+#(.+?)\]', repl, text)
    return display, len(answers)

def clean_mark(text):
    return re.sub(r'</?mark>', '', text)

# ==================== 主界面 ====================
st.set_page_config(page_title="错题记忆助手", page_icon="📚", layout="wide")
st.title("📚 错题记忆助手")

mode = st.radio("选择模块", ["📚 错题集", "🃏 记忆卡"], horizontal=True)

# ==========================================================
# 错题集
# ==========================================================
if mode == "📚 错题集":
    tab1, tab2, tab3, tab4 = st.tabs(["➕ 录入", "🔁 复习", "📋 题库", "📊 统计"])

    with tab1:
        subject = st.text_input("科目", "数学", key="add_subject")
        st.markdown("### ① 获取题目图片")
        pasted = pbutton(label="📋 从剪贴板粘贴图片")
        img = None
        if pasted.image_data is not None:
            try:
                arr = np.array(pasted.image_data)
                if arr.ndim == 3 and arr.shape[2] == 4:
                    img = Image.fromarray(arr, "RGBA").convert("RGB")
                else:
                    img = Image.fromarray(arr).convert("RGB")
                st.session_state["src_img"] = img
            except Exception as e:
                st.error("粘贴失败：" + str(e))
        uploaded = st.file_uploader("或上传图片", type=["png", "jpg", "jpeg"], key="uploader")
        if uploaded:
            img = Image.open(uploaded).convert("RGB")
            st.session_state["src_img"] = img
        if "src_img" in st.session_state:
            st.markdown("### ② 拖框裁剪")
            cropped = st_cropper(st.session_state["src_img"], realtime_update=True,
                                 box_color="#FF6B6B", aspect_ratio=None, return_type="image")
            st.image(cropped, caption="预览", width=300)
            if st.button("✂️ 使用这张裁剪图"):
                buf = io.BytesIO()
                cropped.save(buf, format="PNG")
                st.session_state["cropped_bytes"] = buf.getvalue()
                st.success("已裁剪")
        st.markdown("### ③ 填写题目信息")
        question = st.text_area("题目（可选）", key="add_question")
        img2 = st.file_uploader("解析图片（可选）", type=["png", "jpg", "jpeg"], key="uploader2")
        answer = st.text_area("答案", key="add_answer")
        analysis = st.text_area("解析", key="add_analysis")
        tags = st.text_input("标签", "", key="add_tags")
        if st.button("💾 保存"):
            cropped_bytes = st.session_state.get("cropped_bytes")
            if not question and not cropped_bytes:
                st.warning("至少填题目或传图")
            else:
                url1 = upload_image_bytes(cropped_bytes, "q.png") if cropped_bytes else ""
                url2 = ""
                if img2:
                    buf2 = io.BytesIO()
                    Image.open(img2).convert("RGB").save(buf2, format="PNG")
                    url2 = upload_image_bytes(buf2.getvalue(), "a.png")
                add_mistake(subject, question, answer, analysis, tags, url1, url2)
                st.session_state.pop("cropped_bytes", None)
                st.session_state.pop("src_img", None)
                for k in ["add_question", "add_answer", "add_analysis", "add_tags"]:
                    st.session_state.pop(k, None)
                st.success("已保存")
                st.rerun()

    with tab2:
        due = get_due_today()
        st.subheader("今日待复习：" + str(len(due)) + " 题")
        if due.empty:
            st.info("今天没有复习任务 🎉")
        for _, row in due.iterrows():
            qtext = str(row["question"]) if row["question"] else "(图片题)"
            with st.expander("[" + str(row["subject"]) + "] " + qtext[:30] + "..."):
                if row.get("image_url"):
                    st.image(row["image_url"], caption="题目图")
                if row.get("question"):
                    st.markdown("**题目：** " + str(row["question"]))
                st.caption("阶段 " + str(row["stage"] + 1) + " ｜ 标签：" + str(row["tags"]))
                if st.button("显示答案", key="s" + str(row["id"])):
                    st.markdown("**答案：** " + str(row["answer"]))
                    st.markdown("**解析：** " + str(row["analysis"]))
                    if row.get("image_url2"):
                        st.image(row["image_url2"])
                c1, c2 = st.columns(2)
                if c1.button("✅ 答对", key="ok" + str(row["id"])):
                    review_mistake(row["id"], True); st.rerun()
                if c2.button("❌ 答错", key="no" + str(row["id"])):
                    review_mistake(row["id"], False); st.rerun()

    with tab3:
        df = get_all_mistakes()
        if df.empty:
            st.info("还没有错题")
        else:
            c1, c2, c3 = st.columns(3)
            kw = c1.text_input("关键词")
            subjects = ["全部"] + sorted(df["subject"].dropna().unique().tolist())
            subj_filter = c2.selectbox("科目", subjects)
            sort_by = c3.selectbox("排序", ["最新", "复习时间", "错误次数"])
            fdf = df.copy()
            if subj_filter != "全部":
                fdf = fdf[fdf["subject"] == subj_filter]
            if kw:
                mask = (fdf["question"].fillna("").str.contains(kw, case=False) |
                        fdf["answer"].fillna("").str.contains(kw, case=False) |
                        fdf["tags"].fillna("").str.contains(kw, case=False))
                fdf = fdf[mask]
            if sort_by == "最新":
                fdf = fdf.sort_values("id", ascending=False)
            elif sort_by == "复习时间":
                fdf = fdf.sort_values("next_review")
            elif sort_by == "错误次数":
                fdf = fdf.sort_values("wrong_count", ascending=False)
            st.caption("共 " + str(len(fdf)) + " 条")
            st.dataframe(fdf[["id", "subject", "question", "tags", "stage", "next_review", "wrong_count"]],
                         use_container_width=True, hide_index=True)
            st.markdown("---")
            st.subheader("✏️ 修改 / 🗑️ 删除")
            edit_id = st.selectbox("选择 ID", fdf["id"].tolist(),
                                   format_func=lambda x: "#" + str(x) + " - " + str(df[df["id"] == x]["question"].values[0])[:40])
            if edit_id:
                row = df[df["id"] == edit_id].iloc[0]
                with st.form("edit_m_" + str(edit_id)):
                    e1 = st.text_input("科目", row["subject"] or "")
                    e2 = st.text_area("题目", row["question"] or "")
                    e3 = st.text_area("答案", row["answer"] or "")
                    e4 = st.text_area("解析", row["analysis"] or "")
                    e5 = st.text_input("标签", row["tags"] or "")
                    cc1, cc2 = st.columns(2)
                    if cc1.form_submit_button("💾 保存"):
                        update_mistake(edit_id, e1, e2, e3, e4, e5); st.success("已更新"); st.rerun()
                    if cc2.form_submit_button("🗑️ 删除"):
                        delete_mistake(edit_id); st.success("已删除"); st.rerun()

    with tab4:
        df = get_all_mistakes()
        if df.empty:
            st.info("还没有数据")
        else:
            today = dt.date.today().isoformat()
            c1, c2, c3 = st.columns(3)
            c1.metric("错题总数", len(df))
            c2.metric("今日待复习", int((df["next_review"] <= today).sum()))
            c3.metric("已掌握", int((df["stage"] >= len(INTERVALS)).sum()))
            st.bar_chart(df.groupby("subject").size())

# ==========================================================
# 记忆卡
# ==========================================================
else:
    tab1, tab2, tab3 = st.tabs(["➕ 录入卡片", "🃏 刷卡", "📋 卡片列表"])

    with tab1:
        st.markdown("### 批量录入（粘贴格式）")
        raw = st.text_area("粘贴卡片文本", height=300, key="raw_cards")
        if st.button("解析并导入"):
            if raw.strip():
                cards = parse_cards_text(raw)
                for ch, fr, bk in cards:
                    add_flashcard(ch, fr, bk)
                st.success("已导入 " + str(len(cards)) + " 张")
                st.rerun()
            else:
                st.warning("请先粘贴内容")

        st.markdown("---")
        st.markdown("### 单张录入")
        with st.form("single_card"):
            c_ch = st.text_input("章节", "")
            c_fr = st.text_area("正面（题目）")
            c_bk = st.text_area("背面（答案）")
            c_tags = st.text_input("标签", "")
            if st.form_submit_button("保存单张"):
                if c_fr and c_bk:
                    add_flashcard(c_ch, c_fr, c_bk, c_tags)
                    st.success("已保存")
                    st.rerun()

    with tab2:
        # 顶部设置区
        c1, c2 = st.columns([1, 3])
        current_limit = get_daily_limit()
        new_limit = c1.number_input("每日新学上限", min_value=1, max_value=500, value=current_limit, step=5)
        if new_limit != current_limit:
            set_daily_limit(new_limit)
            st.rerun()

        all_cards = get_all_cards()
        if all_cards.empty:
            st.info("还没有卡片")
        else:
            # 统计
            total_new_remaining = count_new_remaining()
            chapters = ["全部"] + sorted(all_cards["chapter"].dropna().unique().tolist())
            ch_filter = st.selectbox("按章节筛选", chapters, key="card_ch_filter")

            new_cards = get_new_cards(new_limit)
            review_cards = get_review_cards(ch_filter)

            # 若筛选章节，新卡也按章节过滤
            if ch_filter != "全部" and not new_cards.empty:
                new_cards = new_cards[new_cards["chapter"] == ch_filter]

            st.markdown("---")
            col1, col2 = st.columns(2)
            col1.metric("📅 新卡（今日可学）", str(len(new_cards)))
            col2.metric("🔁 待复习", str(len(review_cards)))
            st.caption("还剩新卡（总量）：" + str(total_new_remaining) + " 张")

            # 合并：先新卡，后复习
            if not new_cards.empty:
                due = new_cards
                mode_label = "🆕 新卡"
            elif not review_cards.empty:
                due = review_cards
                mode_label = "🔁 复习"
            else:
                due = pd.DataFrame()
                mode_label = ""

            if due.empty:
                st.success("今天的任务都完成了 🎉")
            else:
                if "card_idx" not in st.session_state:
                    st.session_state.card_idx = 0
                    st.session_state.shown_blanks = 0

                if st.session_state.card_idx >= len(due):
                    st.session_state.card_idx = 0
                    st.session_state.shown_blanks = 0
                    st.rerun()

                row = due.iloc[st.session_state.card_idx]
                front_text = row["front"] or ""
                back_text = row["back"] or ""

                st.markdown("### " + mode_label + " ｜ " + str(row["chapter"] or ""))
                display_front, ans_list = replace_blanks(front_text)
                st.markdown("**" + clean_mark(display_front) + "**")
                st.caption("进度：" + str(st.session_state.card_idx + 1) + " / " + str(len(due)))

                if st.session_state.shown_blanks < len(ans_list):
                    if st.button("👁️ 显示下一个空（" + str(st.session_state.shown_blanks + 1) + "/" + str(len(ans_list)) + "）"):
                        st.session_state.shown_blanks += 1
                        st.rerun()

                if st.session_state.shown_blanks > 0:
                    filled, _ = fill_blanks_step_by_step(front_text, st.session_state.shown_blanks)
                    st.markdown("**" + clean_mark(filled) + "**")

                if st.session_state.shown_blanks >= len(ans_list):
                    st.markdown("---")
                    st.markdown("**完整答案：** " + clean_mark(back_text))
                    st.markdown("### 你记住了吗？")
                    c1, c2, c3 = st.columns(3)
                    if c1.button("😵 忘记", key="cf_" + str(row["id"])):
                        review_card(row["id"], "forget")
                        st.session_state.card_idx += 1
                        st.session_state.shown_blanks = 0
                        st.rerun()
                    if c2.button("🤔 模糊", key="cfz_" + str(row["id"])):
                        review_card(row["id"], "fuzzy")
                        st.session_state.card_idx += 1
                        st.session_state.shown_blanks = 0
                        st.rerun()
                    if c3.button("😎 记住", key="cr_" + str(row["id"])):
                        review_card(row["id"], "remember")
                        st.session_state.card_idx += 1
                        st.session_state.shown_blanks = 0
                        st.rerun()

    with tab3:
        all_cards = get_all_cards()
        if all_cards.empty:
            st.info("还没有卡片")
        else:
            chs = ["全部"] + sorted(all_cards["chapter"].dropna().unique().tolist())
            ch_f = st.selectbox("章节", chs, key="card_list_ch")
            kw = st.text_input("搜索关键词", key="card_kw")
            fdf = all_cards.copy()
            if ch_f != "全部":
                fdf = fdf[fdf["chapter"] == ch_f]
            if kw:
                mask = (fdf["front"].fillna("").str.contains(kw, case=False) |
                        fdf["back"].fillna("").str.contains(kw, case=False))
                fdf = fdf[mask]
            st.caption("共 " + str(len(fdf)) + " 张")
            st.dataframe(fdf[["id", "chapter", "front", "back", "stage", "learned", "next_review", "wrong_count"]],
                         use_container_width=True, hide_index=True)
            st.markdown("---")
            st.subheader("✏️ 修改 / 🗑️ 删除")
            edit_cid = st.selectbox("选择卡片 ID", fdf["id"].tolist(),
                                    format_func=lambda x: "#" + str(x) + " - " + str(all_cards[all_cards["id"] == x]["front"].values[0])[:40])
            if edit_cid:
                row = all_cards[all_cards["id"] == edit_cid].iloc[0]
                with st.form("edit_c_" + str(edit_cid)):
                    f1 = st.text_input("章节", row["chapter"] or "")
                    f2 = st.text_area("正面", row["front"] or "")
                    f3 = st.text_area("背面", row["back"] or "")
                    f4 = st.text_input("标签", row["tags"] or "")
                    cc1, cc2 = st.columns(2)
                    if cc1.form_submit_button("💾 保存"):
                        update_card(edit_cid, f1, f2, f3, f4)
                        st.success("已更新"); st.rerun()
                    if cc2.form_submit_button("🗑️ 删除"):
                        delete_card(edit_cid)
                        st.success("已删除"); st.rerun()
