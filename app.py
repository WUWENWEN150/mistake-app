streamlit 作为 st
导入 datetime 为 dt
导入 pandas 为 pd
从 supabase 导入 create_client
从 streamlit_cropper 导入 st_cropper
从 streamlit_paste_button 导入 paste_image_button 为 pbutton
从 PIL 导入 Image
导入 io

# ---------- 读取密钥 ----------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

INTERVALS = [1, 2, 4, 7, 15, 30]

# ---------- 数据操作 ----------
def add_mistake(subject, question, answer, analysis, tags, image_url="", image_url2=""):
    今天 = dt.日期.今天()
    next_review = today + dt.timedelta(days=INTERVALS[0])
    supabase.表("mistakes").插入({
        "主题": 主题, "问题": 问题, "答案": 答案,
        "分析": 分析, "标签": 标签,
        "image_url": image_url, "image_url2": image_url2,
        "阶段": 0, "下次审查": 下次审查。isoformat()
    }).执行()

def get_due_today():
    今天 = dt.date.today().isoformat()
    res = supabase.table("mistakes").select("*") \
        .lte("next_review", today).order("next_review").execute()
    返回 pd.DataFrame(res.data)

def get_all():
    res = supabase.table("mistakes").select("*").order("id", desc=True).execute()
    返回 pd.DataFrame(res.data)

def review(mid, correct):
    res = supabase.table("mistakes").select("stage,wrong_count").eq("id", mid).execute()
    row = res.data[0]
    阶段, 错误计数 = 行["阶段"], 行["错误计数"]
    如果正确：
        stage += 1
        如果 阶段 >= len(INTERVALS):
            next_date = dt.date.today() + dt.timedelta(days=365)
        否则:
            next_date = dt.date.today() + dt.timedelta(days=INTERVALS[stage])
    否则:
        阶段 = 0
        wrong_count += 1
        next_date = dt.date.today() + dt.timedelta(days=INTERVALS[0])
    supabase.表("mistakes").更新({
        "阶段": 阶段, "下次审核": 下次日期。isoformat(),
        "wrong_count": wrong_count
    }).eq("id", mid).execute()

def update_mistake(mid, subject, question, answer, analysis, tags):
    supabase.表("mistakes").更新({
        "主题": 主题, "问题": 问题, "答案": 答案,
        "分析": 分析, "标签": 标签
    }).eq("id", mid).execute()

def delete_mistake(mid):
    supabase.table("mistakes").delete().eq("id", mid).execute()

def upload_image_bytes(img_bytes, filename):
    path = f"{dt.datetime.now().timestamp()}_{filename}"
    supabase.storage.from_("mistake-images").upload(
        路径, img_bytes, {"content-type": "image/png"})
    return supabase.storage.from_("mistake-images").get_public_url(path)

# ---------- 界面 ----------
st.set_page_config(page_title="错题记忆", page_icon="📚", layout="wide")
st.title("📚 错题记忆助手")

tab1, tab2, tab3, tab4 = st.tabs(["➕ 录入", "🔁 复习", "📋 全部错题", "📊 统计"])

# --- 录入 ---
with tab1:
    subject = st.text_input("科目", "数学")

    st.markdown("### ① 获取题目图片")
    st.caption("方式一：复制图片后（Ctrl+C），点下面按钮粘贴")
    pasted = pbutton(label="📋 从剪贴板粘贴图片")

        img = None
        if pasted.image_data is not None:
        try:
            import numpy as np
            arr = np.array(pasted.image_data)
            # 有些版本返回 RGBA，转成 RGB
            if arr.ndim == 3 and arr.shape[2] == 4:
                img = Image.fromarray(arr, "RGBA").convert("RGB")
            else:
                img = Image.fromarray(arr).convert("RGB")
            st.session_state["src_img"] = img
        except Exception as e:
            st.error(f"粘贴图片失败：{e}")

    st.caption("方式二：或从电脑选择文件")
    uploaded = st.file_uploader("上传图片（可选）", type=["png", "jpg", "jpeg"], key="uploader")
    if uploaded:
        img = Image.open(uploaded).convert("RGB")
        st.session_state["src_img"] = img

    if "src_img" in st.session_state:
        src = st.session_state["src_img"]
        st.markdown("### ② 拖框裁剪（只保留这道题）")
        st.caption("拖动方框，框住你要的题目部分。手机上也适用。")
        cropped = st_cropper(
            src,
            realtime_update=True,
            box_color="#FF6B6B",
            aspect_ratio=None,
            return_type="image"
        )
        st.image(cropped, caption="预览：这张会被保存", use_container_width=True)
        if st.button("✂️ 使用这张裁剪图"):
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            st.session_state["cropped_bytes"] = buf.getvalue()
            st.success("已裁剪。继续往下填写。")
    else:
        st.info("先粘贴或上传一张图片")

    st.markdown("### ③ 填写题目信息")
    question = st.text_area("题目文字（可选，如果图片已经很清晰可以留空）")
    img2 = st.file_uploader("上传解析图片（可选，第二张）", type=["png", "jpg", "jpeg"], key="uploader2")
    answer = st.text_area("正确答案")
    analysis = st.text_area("解析/错因")
    tags = st.text_input("知识点标签", "")

    if st.button("💾 保存"):
        cropped_bytes = st.session_state.get("cropped_bytes")
        if not question and not cropped_bytes:
            st.warning("题目文字和图片至少填一个")
        else:
            url1 = upload_image_bytes(cropped_bytes, "q.png") if cropped_bytes else ""
            url2 = ""
            if img2:
                buf2 = io.BytesIO()
                Image.open(img2).convert("RGB").save(buf2, format="PNG")
                url2 = upload_image_bytes(buf2.getvalue(), "a.png")
            add_mistake(subject, question, answer, analysis, tags, url1, url2)
            # 清理缓存，避免影响下一题
            st.session_state.pop("cropped_bytes", None)
            st.session_state.pop("src_img", None)
            st.success("已保存，明天首次复习。")
            st.rerun()

# --- 复习 ---
with tab2:
    due = get_due_today()
    st.subheader(f"今日待复习：{len(due)} 题")
    if due.empty:
        st.info("今天没有需要复习的题目 🎉")
    for _, row in due.iterrows():
        with st.expander(f"[{row['subject']}] {str(row['question'])[:30]}..."):
            if row.get("image_url"):
                st.image(row["image_url"], caption="题目图")
            if row.get("question"):
                st.markdown(f"**题目：** {row['question']}")
            st.caption(f"阶段 {row['stage'] + 1}/{len(INTERVALS)} ｜ 标签：{row['tags']}")
            if st.button("显示答案", key=f"s{row['id']}"):
                st.markdown(f"**答案：** {row['answer']}")
                st.markdown(f"**解析：** {row['analysis']}")
                if row.get("image_url2"):
                    st.image(row["image_url2"], caption="解析图")
            c1, c2 = st.columns(2)
            if c1.button("✅ 答对", key=f"ok{row['id']}"):
                review(row["id"], True); st.rerun()
            if c2.button("❌ 答错", key=f"no{row['id']}"):
                review(row["id"], False); st.rerun()

# --- 全部错题 ---
with tab3:
    df = get_all()
    if df.empty:
        st.info("还没有错题记录。")
    else:
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
        st.subheader("👁️ 查看详情 / ✏️ 编辑 / 🗑️ 删除")
        edit_id = st.selectbox(
            "选择错题 ID",
            options=fdf["id"].tolist(),
            format_func=lambda x: f"#{x} - {str(df[df['id']==x]['question'].values[0])[:40]}"
        )
        if edit_id:
            row = df[df["id"] == edit_id].iloc[0]
            if row.get("image_url") or row.get("image_url2"):
                cc1, cc2 = st.columns(2)
                if row.get("image_url"):
                    cc1.image(row["image_url"], caption="题目图")
                if row.get("image_url2"):
                    cc2.image(row["image_url2"], caption="解析图")

            with st.form(f"edit_{edit_id}"):
                e_subject = st.text_input("科目", row["subject"])
                e_question = st.text_area("题目", row["question"] or "")
                e_answer = st.text_area("答案", row["answer"] or "")
                e_analysis = st.text_area("解析", row["analysis"] or "")
                e_tags = st.text_input("标签", row["tags"] or "")
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
