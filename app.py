import streamlit as st
import datetime as dt
import pandas as pd
from supabase import create_client

# ---------- 读取密钥 ----------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

INTERVALS = [1, 2, 4, 7, 15, 30]

# ---------- 数据操作 ----------
def add_mistake(subject, question, answer, analysis, tags, image_url=""):
    today = dt.date.today()
    next_review = today + dt.timedelta(days=INTERVALS[0])
    supabase.table("mistakes").insert({
        "subject": subject, "question": question, "answer": answer,
        "analysis": analysis, "tags": tags, "image_url": image_url,
        "stage": 0, "next_review": next_review.isoformat()
    }).execute()

def get_due_today():
    today = dt.date.today().isoformat()
    res = supabase.table("mistakes").select("*") \
        .lte("next_review", today).order("next_review").execute()
    return pd.DataFrame(res.data)

def get_all():
    res = supabase.table("mistakes").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data)

def review(mid, correct):
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
        "stage": stage, "next_review": next_date.isoformat(),
        "wrong_count": wrong_count
    }).eq("id", mid).execute()

def update_mistake(mid, subject, question, answer, analysis, tags):
    supabase.table("mistakes").update({
        "subject": subject, "question": question, "answer": answer,
        "analysis": analysis, "tags": tags
    }).eq("id", mid).execute()

def delete_mistake(mid):
    supabase.table("mistakes").delete().eq("id", mid).execute()

def upload_image(file):
    path = f"{dt.datetime.now().timestamp()}_{file.name}"
    supabase.storage.from_("mistake-images").upload(
        path, file.getvalue(), {"content-type": file.type})
    return supabase.storage.from_("mistake-images").get_public_url(path)

# ---------- 界面 ----------
st.set_page_config(page_title="错题记忆", page_icon="📚", layout="wide")
st.title("📚 错题记忆助手")

tab1, tab2, tab3, tab4 = st.tabs(["➕ 录入", "🔁 复习", "📋 全部错题", "📊 统计"])

# --- 录入 ---
with tab1:
    with st.form("add"):
        subject = st.text_input("科目", "数学")
        question = st.text_area("题目")
        img = st.file_uploader("上传题目图片（可选）", type=["png", "jpg", "jpeg"])
        answer = st.text_area("正确答案")
        analysis = st.text_area("解析/错因")
        tags = st.text_input("知识点标签", "")
        ok = st.form_submit_button("保存")
        if ok and question:
            img_url = upload_image(img) if img else ""
            add_mistake(subject, question, answer, analysis, tags, img_url)
            st.success("已保存，明天首次复习。")

# --- 复习 ---
with tab2:
    due = get_due_today()
    st.subheader(f"今日待复习：{len(due)} 题")
    if due.empty:
        st.info("今天没有需要复习的题目 🎉")
    for _, row in due.iterrows():
        with st.expander(f"[{row['subject']}] {row['question'][:30]}..."):
            st.markdown(f"**题目：** {row['question']}")
            if row.get("image_url"):
                st.image(row["image_url"])
            st.caption(f"阶段 {row['stage'] + 1}/{len(INTERVALS)} ｜ 标签：{row['tags']}")
            if st.button("显示答案", key=f"s{row['id']}"):
                st.markdown(f"**答案：** {row['answer']}")
                st.markdown(f"**解析：** {row['analysis']}")
            c1, c2 = st.columns(2)
            if c1.button("✅ 答对", key=f"ok{row['id']}"):
                review(row["id"], True); st.rerun()
            if c2.button("❌ 答错", key=f"no{row['id']}"):
                review(row["id"], False); st.rerun()

# --- 全部错题 ---
with tab4 if False else tab3:
    df = get_all()
    if df.empty:
        st.info("还没有错题记录。")
    else:
        # 筛选区
        c1, c2, c3 = st.columns(3)
        subj_filter = c1.selectbox("按科目筛选", ["全部"] + sorted(df["subject"].dropna().unique().tolist()))
        kw = c2.text_input("关键词搜索（题目/答案/标签）")
        sort_by = c3.selectbox("排序", ["最新录入", "下次复习时间", "错误次数"])

        fdf = df.copy()
        if subj_filter != "全部":
            fdf = fdf[fdf["subject"] == subj_filter]
        if kw:
            mask = (
                fdf["question"].fillna("").str.contains(kw, case=False) |
                fdf["answer"].fillna("").str.contains(kw, case=False) |
                fdf["tags"].fillna("").str.contains(kw, case=False)
            )
            fdf = fdf[mask]
        if sort_by == "最新录入":
            fdf = fdf.sort_values("id", ascending=False)
        elif sort_by == "下次复习时间":
            fdf = fdf.sort_values("next_review")
        elif sort_by == "错误次数":
            fdf = fdf.sort_values("wrong_count", ascending=False)

        st.caption(f"共 {len(fdf)} 条（总 {len(df)} 条）")
        st.dataframe(
            fdf[["id", "subject", "question", "tags", "stage", "next_review", "wrong_count"]],
            use_container_width=True, hide_index=True
        )

        st.markdown("---")
        st.subheader("✏️ 编辑 / 🗑️ 删除")
        edit_id = st.selectbox(
            "选择要操作的错题 ID",
            options=fdf["id"].tolist(),
            format_func=lambda x: f"#{x} - {df[df['id']==x]['question'].values[0][:40]}"
        )
        if edit_id:
            row = df[df["id"] == edit_id].iloc[0]
            with st.form(f"edit_{edit_id}"):
                e_subject = st.text_input("科目", row["subject"])
                e_question = st.text_area("题目", row["question"])
                e_answer = st.text_area("答案", row["answer"])
                e_analysis = st.text_area("解析", row["analysis"])
                e_tags = st.text_input("标签", row["tags"])
                col1, col2 = st.columns(2)
                save = col1.form_submit_button("💾 保存修改")
                dele = col2.form_submit_button("🗑️ 删除此题")

                if save:
                    update_mistake(edit_id, e_subject, e_question, e_answer, e_analysis, e_tags)
                    st.success("已更新")
                    st.rerun()
                if dele:
                    delete_mistake(edit_id)
                    st.success("已删除")
                    st.rerun()

# --- 统计 ---
with tab4:
    df = get_all()
    if df.empty:
        st.info("还没有错题记录。")
    else:
        today = dt.date.today().isoformat()
        c1, c2, c3 = st.columns(3)
        c1.metric("错题总数", len(df))
        c2.metric("今日待复习", (df["next_review"] <= today).sum())
        c3.metric("已掌握", (df["stage"] >= len(INTERVALS)).sum())
        st.bar_chart(df.groupby("subject").size())
