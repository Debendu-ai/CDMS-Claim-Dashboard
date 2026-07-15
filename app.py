"""
app.py — CDMS Promo Claim Accuracy Dashboard
================================================
A two-stage Streamlit GUI:

  STAGE 1: Upload the Master file (reference/documentation) + the
           Secondary Sales dump. The dashboard independently computes the
           "Working" — what Prc Off Claim & DB Margin Amt SHOULD be, per
           distributor, per the Master's approved formula logic.

  STAGE 2: Once CDMS actually generates the Promo Claim, upload that file.
           The dashboard compares it against the Working from Stage 1 and
           shows an accuracy dashboard — matched / over-claimed /
           under-claimed / missing distributors, with variance amounts.

--------------------------------------------------------------------
SETUP (run once):
    pip install streamlit pandas openpyxl plotly xlsxwriter

RUN:
    streamlit run app.py
--------------------------------------------------------------------
"""

import io

import pandas as pd
import plotly.express as px
import streamlit as st

import cdms_engine as eng
import history_store as hs
import pdf_report as pdfrep

st.set_page_config(page_title="CDMS Promo Claim Accuracy Dashboard", layout="wide")
st.title("CDMS Promo Claim Accuracy Dashboard")

if "working_summary" not in st.session_state:
    st.session_state.working_summary = None
    st.session_state.working_detail = None
    st.session_state.working_run_id = None

tab1, tab2, tab3 = st.tabs([
    "Stage 1 — Build the Working",
    "Stage 2 — Validate CDMS Promo Claim",
    "History",
])

# ======================================================================
# STAGE 1
# ======================================================================
with tab1:
    st.header("Stage 1 — Build the Working from Master + Secondary Sales")
    st.write(
        "Upload the Master file (for reference) and the Secondary Sales dump. "
        "The dashboard independently calculates what the Prc Off Claim and "
        "DB Margin Amount **should be**, per distributor, using the Master's "
        "approved formula logic."
    )

    c1, c2 = st.columns(2)
    with c1:
        master_file = st.file_uploader(
            "Master file (.xlsx / .xlsb)", type=["xlsx", "xlsb"], key="master_upl"
        )
    with c2:
        sec_sales_file = st.file_uploader(
            "Secondary Sales dump (.xlsx)", type=["xlsx"], key="secsales_upl"
        )

    sheet_name_1 = st.text_input("Sheet name (Secondary Sales file)", value="Sheet1", key="sheet1")

    if master_file is not None:
        st.success(f"Master file received: {master_file.name}. "
                   "Formula logic already embedded in this dashboard is derived from this workbook's 'Cal' sheet.")

    if sec_sales_file is None:
        st.info("Upload the Secondary Sales dump to build the Working.")
    else:
        try:
            df = pd.read_excel(sec_sales_file, sheet_name=sheet_name_1)
        except Exception as e:
            st.error(f"Could not read the Secondary Sales file: {e}")
            df = None

        if df is not None:
            missing = eng.check_base_columns(df)
            if missing:
                st.error(
                    "The Secondary Sales file is missing columns needed to build the Working:\n\n"
                    + ", ".join(missing)
                )
            else:
                st.subheader("Review & edit uploaded data (optional)")
                st.caption(
                    "Remove distributors entirely, or edit/delete individual rows, before the "
                    "Working is calculated. Nothing here changes your original file — it's a "
                    "working copy for this session only."
                )

                all_distributors = sorted(df['Distributor Name'].dropna().unique())
                excluded = st.multiselect(
                    "Exclude distributor(s) entirely from this calculation",
                    all_distributors, key="stage1_exclude",
                )
                df_filtered = df[~df['Distributor Name'].isin(excluded)]
                if excluded:
                    st.caption(f"Excluded {len(excluded)} distributor(s), "
                               f"{len(df) - len(df_filtered)} row(s) removed.")

                with st.expander("Edit or delete individual rows"):
                    edit_scope = st.selectbox(
                        "Filter to one distributor to edit (recommended for large files, "
                        "keeps the table fast)",
                        ["(select a distributor)"] + sorted(df_filtered['Distributor Name'].dropna().unique()),
                        key="stage1_edit_scope",
                    )
                    if edit_scope != "(select a distributor)":
                        subset = df_filtered[df_filtered['Distributor Name'] == edit_scope].reset_index(drop=True)
                        st.caption(f"{len(subset)} row(s) for {edit_scope}. "
                                   "Use the row checkbox + trash icon to delete a row, or edit cells directly.")
                        edited_subset = st.data_editor(
                            subset, num_rows="dynamic", use_container_width=True, key="stage1_editor"
                        )
                        df_final = pd.concat(
                            [df_filtered[df_filtered['Distributor Name'] != edit_scope], edited_subset],
                            ignore_index=True,
                        )
                    else:
                        st.info("Pick a distributor above to edit or delete its rows.")
                        df_final = df_filtered

                working = eng.build_working(df_final)
                summary = eng.working_distributor_summary(working)
                depot = eng.working_depot_summary(working)

                st.session_state.working_summary = summary
                st.session_state.working_detail = working

                st.subheader("Save this run")
                sc1, sc2 = st.columns([3, 1])
                with sc1:
                    stage1_label = st.text_input(
                        "Label for this Working (e.g. 'June 2026')", value="", key="stage1_label"
                    )
                with sc2:
                    st.write("")
                    st.write("")
                    if st.button("💾 Save to History", key="save_stage1"):
                        if not stage1_label.strip():
                            st.error("Give this run a label first (e.g. the month).")
                        else:
                            run_id = hs.save_working_run(
                                summary, label=stage1_label.strip(),
                                source_file=sec_sales_file.name,
                            )
                            st.session_state.working_run_id = run_id
                            st.success(f"Saved as '{stage1_label.strip()}'. See it under the History tab.")

                st.subheader("Overview")
                k1, k2, k3 = st.columns(3)
                k1.metric("Distributors", f"{summary.shape[0]:,}")
                k2.metric("Working Prc Off Claim", f"₹{summary['Working_Prc_Off_Claim'].sum():,.2f}")
                k3.metric("Working DB Margin Amt", f"₹{summary['Working_DB_Margin_Amt'].sum():,.2f}")

                # optional self-check vs the dump's own claim columns, if present
                check_df = eng.self_check(working)
                if check_df is not None:
                    st.subheader("Self-check (dump's own claim columns vs Working)")
                    st.caption(
                        "This file already contains its own Pur Inv Amt / Prc Off Claim / DB Margin Amt "
                        "columns — shown here purely as an extra sanity check. The Working above is "
                        "still computed independently from base fields."
                    )
                    st.dataframe(eng.self_check_scorecard(check_df), use_container_width=True, hide_index=True)

                st.subheader("Working — Distributor-wise")
                st.dataframe(summary, use_container_width=True, hide_index=True)

                cc1, cc2 = st.columns(2)
                with cc1:
                    fig1 = px.bar(
                        summary, x="Distributor Name",
                        y=["Working_Prc_Off_Claim", "Working_DB_Margin_Amt"],
                        barmode="group", title="Working Claim Components by Distributor",
                        labels={"value": "Amount (₹)", "variable": "Component"},
                    )
                    st.plotly_chart(fig1, use_container_width=True)
                with cc2:
                    fig2 = px.pie(
                        summary, names="Distributor Name", values="Working_DB_Tot_Claim",
                        title="Share of Working Total Claim by Distributor",
                    )
                    st.plotly_chart(fig2, use_container_width=True)

                st.subheader("Working — Depot-wise")
                st.dataframe(depot, use_container_width=True, hide_index=True)

                @st.cache_data
                def build_stage1_workbook(summary_df, depot_df, detail_df):
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                        summary_df.to_excel(writer, sheet_name="Working - Distributor", index=False)
                        depot_df.to_excel(writer, sheet_name="Working - Depot", index=False)
                        detail_df.to_excel(writer, sheet_name="Working - Detail", index=False)
                    return buf.getvalue()

                wb_bytes = build_stage1_workbook(summary, depot, working)

                @st.cache_data
                def build_stage1_pdf(summary_df, depot_df):
                    return pdfrep.build_working_pdf(summary_df, depot_df)

                pdf_bytes = build_stage1_pdf(summary, depot)

                dl1, dl2 = st.columns(2)
                with dl1:
                    st.download_button(
                        "Download Working workbook (.xlsx)",
                        data=wb_bytes,
                        file_name="CDMS_Working.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                with dl2:
                    st.download_button(
                        "Download Working report (.pdf, with pie chart)",
                        data=pdf_bytes,
                        file_name="CDMS_Working.pdf",
                        mime="application/pdf",
                    )

# ======================================================================
# STAGE 2
# ======================================================================
with tab2:
    st.header("Stage 2 — Validate the actual CDMS Promo Claim")

    if st.session_state.working_summary is None:
        st.warning("Build the Working in Stage 1 first — this tab compares against it.")
    else:
        st.write(
            "Upload the Promo Claim file CDMS actually generated. The dashboard "
            "will compare it against the Working from Stage 1, distributor by "
            "distributor, and show where it matches, over-claims, under-claims, "
            "or is missing entirely."
        )

        claim_file = st.file_uploader("CDMS Promo Claim file (.xlsx)", type=["xlsx"], key="claim_upl")
        sheet_name_2 = st.text_input("Sheet name (Claim file)", value="Sheet1", key="sheet2")

        if claim_file is not None:
            try:
                claim_df = pd.read_excel(claim_file, sheet_name=sheet_name_2)
            except Exception as e:
                st.error(f"Could not read the claim file: {e}")
                claim_df = None

            if claim_df is not None:
                if eng.is_portal_report_format(claim_df):
                    st.success(
                        "Recognized this as a CDMS Portal Report export (Parent No / Claim Disc. / "
                        "Claim Amount format) — pivoted automatically, no column mapping needed."
                    )
                    claim_wide = eng.pivot_portal_report(claim_df)
                    db_code_col, prc_off_claim_col, db_margin_col = 'DB Code', 'Prc Off Claim', 'DB Margin Amt'
                    distributor_col = None
                    claim_for_compare = claim_wide
                else:
                    st.write("Map the claim file's columns to the fields needed for comparison:")
                    cols = list(claim_df.columns)
                    m1, m2, m3, m4 = st.columns(4)
                    with m1:
                        db_code_col = st.selectbox("DB Code column", cols, index=cols.index("DB Code") if "DB Code" in cols else 0)
                    with m2:
                        dist_col_options = ["(none)"] + cols
                        dist_default = dist_col_options.index("Distributor Name") if "Distributor Name" in cols else 0
                        distributor_col = st.selectbox("Distributor Name column (optional)", dist_col_options, index=dist_default)
                        distributor_col = None if distributor_col == "(none)" else distributor_col
                    with m3:
                        prc_col_guess = next((c for c in cols if "prc off" in c.lower() or "price off" in c.lower()), cols[0])
                        prc_off_claim_col = st.selectbox("Prc Off Claim column", cols, index=cols.index(prc_col_guess))
                    with m4:
                        margin_col_guess = next((c for c in cols if "margin" in c.lower()), cols[0])
                        db_margin_col = st.selectbox("DB Margin Amt column", cols, index=cols.index(margin_col_guess))
                    claim_for_compare = claim_df

                tol = st.number_input("Match tolerance (₹, per distributor)", value=1.0, step=1.0)

                st.subheader("Review & edit claim data (optional)")
                st.caption(
                    "Remove a distributor's claim entirely, or edit its amounts, before comparing "
                    "against the Working. Nothing here changes your original file."
                )
                claim_display = claim_for_compare.rename(columns={
                    db_code_col: 'DB Code', prc_off_claim_col: 'Claim Prc Off Claim',
                    db_margin_col: 'Claim DB Margin Amt',
                })
                keep_disp_cols = ['DB Code', 'Claim Prc Off Claim', 'Claim DB Margin Amt']
                if distributor_col and distributor_col in claim_for_compare.columns:
                    claim_display = claim_display.rename(columns={distributor_col: 'Distributor Name'})
                    keep_disp_cols = ['DB Code', 'Distributor Name'] + keep_disp_cols[1:]
                claim_display = claim_display[[c for c in keep_disp_cols if c in claim_display.columns]]

                claim_codes = sorted(claim_display['DB Code'].dropna().unique())
                excl_claim_codes = st.multiselect(
                    "Exclude DB Code(s) entirely from this comparison", claim_codes, key="stage2_exclude",
                )
                claim_display = claim_display[~claim_display['DB Code'].isin(excl_claim_codes)]

                with st.expander("Edit or delete individual claim rows"):
                    edited_claim = st.data_editor(
                        claim_display, num_rows="dynamic", use_container_width=True, key="stage2_editor"
                    )

                edited_claim = edited_claim.rename(columns={
                    'Claim Prc Off Claim': 'Actual_Prc_Off_Claim_edited',
                    'Claim DB Margin Amt': 'Actual_DB_Margin_Amt_edited',
                })

                comparison = eng.compare_with_claim(
                    st.session_state.working_summary,
                    edited_claim,
                    db_code_col='DB Code',
                    prc_off_claim_col='Actual_Prc_Off_Claim_edited',
                    db_margin_col='Actual_DB_Margin_Amt_edited',
                    distributor_col='Distributor Name' if 'Distributor Name' in edited_claim.columns else None,
                    tol=tol,
                )
                score = eng.claim_accuracy_scorecard(comparison)

                st.subheader("Save this run")
                sc1, sc2 = st.columns([3, 1])
                with sc1:
                    stage2_label = st.text_input(
                        "Label for this comparison (e.g. 'June 2026 vs Portal')", value="", key="stage2_label"
                    )
                with sc2:
                    st.write("")
                    st.write("")
                    if st.button("💾 Save to History", key="save_stage2"):
                        if not stage2_label.strip():
                            st.error("Give this run a label first.")
                        else:
                            hs.save_claim_run(
                                comparison, score, label=stage2_label.strip(),
                                working_run_id=st.session_state.working_run_id,
                                claim_file=claim_file.name,
                            )
                            st.success(f"Saved as '{stage2_label.strip()}'. See it under the History tab.")

                st.subheader("Accuracy Overview")
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Accuracy", f"{score['Accuracy %']}%")
                k2.metric("Distributors Matched", f"{score['Matched']} / {score['Distributors Checked']}")
                k3.metric("Total Working Claim", f"₹{score['Total Working Claim']:,.2f}")
                k4.metric("Total Variance", f"₹{score['Total Variance']:,.2f}")

                if score["Accuracy %"] == 100.0:
                    st.success("The CDMS Promo Claim matches the Working exactly for every distributor.")
                else:
                    st.warning(f"{score['Mismatched']} distributor(s) don't reconcile — see details below.")

                st.subheader("Distributor-wise Comparison")
                status_filter = st.radio("Show", ["All", "Mismatches only"], horizontal=True, key="stage2_filter")
                view = comparison if status_filter == "All" else comparison[comparison["Status"] != "MATCH"]
                st.dataframe(view, use_container_width=True, hide_index=True)

                cc1, cc2 = st.columns(2)
                with cc1:
                    fig3 = px.bar(
                        comparison, x="Distributor Name",
                        y=["Working_DB_Tot_Claim", "Actual_DB_Tot_Claim"],
                        barmode="group", title="Working vs Actual Total Claim by Distributor",
                        labels={"value": "Amount (₹)", "variable": "Source"},
                    )
                    st.plotly_chart(fig3, use_container_width=True)
                with cc2:
                    status_counts = comparison["Status"].value_counts().reset_index()
                    status_counts.columns = ["Status", "Count"]
                    fig4 = px.pie(status_counts, names="Status", values="Count", title="Distributors by Status")
                    st.plotly_chart(fig4, use_container_width=True)

                @st.cache_data
                def build_stage2_workbook(comparison_df, score_dict):
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                        pd.DataFrame([score_dict]).to_excel(writer, sheet_name="Accuracy Scorecard", index=False)
                        comparison_df.to_excel(writer, sheet_name="Distributor Comparison", index=False)
                    return buf.getvalue()

                wb2_bytes = build_stage2_workbook(comparison, score)

                @st.cache_data
                def build_stage2_pdf(comparison_df, score_dict):
                    return pdfrep.build_claim_accuracy_pdf(comparison_df, score_dict)

                pdf2_bytes = build_stage2_pdf(comparison, score)

                dl3, dl4 = st.columns(2)
                with dl3:
                    st.download_button(
                        "Download claim accuracy report (.xlsx)",
                        data=wb2_bytes,
                        file_name="CDMS_Promo_Claim_Accuracy.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                with dl4:
                    st.download_button(
                        "Download claim accuracy report (.pdf, with pie chart)",
                        data=pdf2_bytes,
                        file_name="CDMS_Promo_Claim_Accuracy.pdf",
                        mime="application/pdf",
                    )

# ======================================================================
# HISTORY
# ======================================================================
with tab3:
    st.header("History")
    st.caption(
        "Past saved runs. Note: on the free tier this survives normal day-to-day "
        "use, but is not guaranteed to survive every app redeploy or a very long "
        "period of inactivity — treat it as a convenience, not a permanent archive. "
        "Download the Excel reports for anything you must keep long-term."
    )

    st.subheader("Saved Working runs (Stage 1)")
    working_runs = hs.list_working_runs()
    if working_runs.empty:
        st.info("No Working runs saved yet. Save one from the Stage 1 tab.")
    else:
        st.dataframe(working_runs, use_container_width=True, hide_index=True)
        wr1, wr2, wr3 = st.columns(3)
        with wr1:
            view_id = st.selectbox(
                "View a saved Working", working_runs["id"], key="hist_view_working",
                format_func=lambda i: working_runs.loc[working_runs["id"] == i, "label"].values[0],
            )
            if st.button("Load into Stage 2", key="load_working_to_stage2"):
                st.session_state.working_summary = hs.load_working_run(view_id)
                st.session_state.working_run_id = view_id
                st.success("Loaded — go to Stage 2 to validate a claim against this Working.")
        with wr2:
            del_id = st.selectbox(
                "Delete a saved Working", working_runs["id"], key="hist_del_working",
                format_func=lambda i: working_runs.loc[working_runs["id"] == i, "label"].values[0],
            )
            if st.button("🗑️ Delete", key="delete_working_run"):
                hs.delete_working_run(del_id)
                st.success("Deleted. Refresh to update the list.")
                st.rerun()
        with wr3:
            st.write("")

        with st.expander("Preview a saved Working"):
            preview_df = hs.load_working_run(view_id)
            st.dataframe(preview_df, use_container_width=True, hide_index=True)

    st.subheader("Saved Claim comparisons (Stage 2)")
    claim_runs = hs.list_claim_runs()
    if claim_runs.empty:
        st.info("No claim comparisons saved yet. Save one from the Stage 2 tab.")
    else:
        st.dataframe(claim_runs, use_container_width=True, hide_index=True)
        cr1, cr2 = st.columns(2)
        with cr1:
            cview_id = st.selectbox(
                "View a saved comparison", claim_runs["id"], key="hist_view_claim",
                format_func=lambda i: claim_runs.loc[claim_runs["id"] == i, "label"].values[0],
            )
        with cr2:
            cdel_id = st.selectbox(
                "Delete a saved comparison", claim_runs["id"], key="hist_del_claim",
                format_func=lambda i: claim_runs.loc[claim_runs["id"] == i, "label"].values[0],
            )
            if st.button("🗑️ Delete", key="delete_claim_run"):
                hs.delete_claim_run(cdel_id)
                st.success("Deleted. Refresh to update the list.")
                st.rerun()

        with st.expander("Preview a saved comparison"):
            preview_cmp = hs.load_claim_run(cview_id)
            st.dataframe(preview_cmp, use_container_width=True, hide_index=True)

