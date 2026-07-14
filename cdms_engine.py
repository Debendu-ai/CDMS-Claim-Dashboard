"""
cdms_engine.py
==============
Pure calculation logic (no GUI code) behind the CDMS Promo Claim dashboard.
Imported by app.py; can also be unit-tested / run standalone.

Two-stage workflow:

  STAGE 1 -- Build the "Working"
      Input:  a Secondary Sales dump (row per invoice line).
      Output: an independently-derived Prc Off Claim & DB Margin Amt for
              every row, rolled up by distributor. This is "what the claim
              SHOULD be", computed from base fields only -- it does NOT
              trust any pre-existing claim columns that might already sit
              in the dump.

  STAGE 2 -- Validate the actual CDMS Promo Claim
      Input:  the claim file CDMS actually generates downstream, plus the
              Working built in Stage 1.
      Output: a distributor-wise comparison (Working vs Actual claim) with
              variance amounts and an accuracy %.

Formula reference (reverse-engineered from CDMS_Master.xlsb -> 'Cal' sheet):
    qty_eff (return-safe qty)= Billing Quantity, or abs(Net Qty post return)
                                on full-return-only lines (Billing Qty = 0)
    Pur Inv Amt (E)          = MRP Value x (1 - Prim. RM%)
    Tot Prc Off Amt (F)      = Prc Off Amt/Pc x qty_eff
    NetMRP Amount (H)        = MRP Value x (1 - Price Off%)
    MT GSV Amt for Claim (J) = H x (1 - KA RM%)
    Prc Off Claim (K)        = 0                  if F rounds to 0
                              = E - J              otherwise
    DB Margin Amt (L)        = E x 5%              if F > 0
                              = (E x 5%) - (J - E)  otherwise
    DB Tot Claim              = Prc Off Claim + DB Margin Amt
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- Stage 1 --

BASE_COLUMNS = [
    'Distributor Name', 'DB Code', 'Depot Code', 'Depot Name',
    'MRP', 'MRP Value', 'Billing Quantity', 'Net Qty post return',
    'Prim. RM %', 'KA RM %', 'Price Off %', 'Prc Off Amt / Pc',
]

OPTIONAL_COLUMNS = ['Invoice No.', 'Material Desc.']


def check_base_columns(df: pd.DataFrame) -> list:
    """Return any of the base sales columns missing from the uploaded dump."""
    return [c for c in BASE_COLUMNS if c not in df.columns]


def build_working(df: pd.DataFrame) -> pd.DataFrame:
    """Independently compute Pur Inv Amt / Tot Prc Off Amt / Prc Off Claim /
    DB Margin Amt / DB Tot Claim from base sales fields only. This is the
    'Working' -- the benchmark the actual CDMS Promo Claim gets checked
    against in Stage 2.
    """
    qty_eff = np.where(
        df['Billing Quantity'] != 0,
        df['Billing Quantity'],
        df['Net Qty post return'].abs(),
    )

    e_calc = df['MRP Value'] * (1 - df['Prim. RM %'] / 100)     # Pur Inv Amt
    f_calc = (df['Prc Off Amt / Pc'] * qty_eff)                  # Tot Prc Off Amt
    h_calc = df['MRP Value'] * (1 - df['Price Off %'] / 100)     # NetMRP Amount
    j_calc = h_calc * (1 - df['KA RM %'] / 100)                   # MT GSV Amt for Claim

    k_calc = np.where(f_calc.round(2) == 0, 0, e_calc - j_calc)  # Prc Off Claim
    l_calc = np.where(                                             # DB Margin Amt
        f_calc.round(2) > 0,
        e_calc * 0.05,
        (e_calc * 0.05) - (j_calc - e_calc),
    )

    out = df.copy()
    out['Working_Pur_Inv_Amt'] = e_calc.round(2)
    out['Working_Tot_Prc_Off_Amt'] = f_calc.round(2)
    out['Working_Prc_Off_Claim'] = np.round(k_calc, 2)
    out['Working_DB_Margin_Amt'] = np.round(l_calc, 2)
    out['Working_DB_Tot_Claim'] = (out['Working_Prc_Off_Claim'] + out['Working_DB_Margin_Amt']).round(2)

    return out


def working_distributor_summary(df_working: pd.DataFrame) -> pd.DataFrame:
    """Distributor-wise rollup of the Working -- this is 'what the claim
    should be', per DB Code / Distributor Name."""
    return (
        df_working.groupby(['DB Code', 'Distributor Name'], as_index=False)
        .agg(
            Rows=('Working_Prc_Off_Claim', 'size'),
            Working_Tot_Prc_Off_Amt=('Working_Tot_Prc_Off_Amt', 'sum'),
            Working_Prc_Off_Claim=('Working_Prc_Off_Claim', 'sum'),
            Working_DB_Margin_Amt=('Working_DB_Margin_Amt', 'sum'),
            Working_DB_Tot_Claim=('Working_DB_Tot_Claim', 'sum'),
        )
        .round(2)
        .sort_values('Working_DB_Tot_Claim', ascending=False)
        .reset_index(drop=True)
    )


def working_depot_summary(df_working: pd.DataFrame) -> pd.DataFrame:
    """Depot-wise rollup of the Working, for the dashboard's secondary cut."""
    return (
        df_working.groupby(['Depot Code', 'Depot Name'], as_index=False)
        .agg(
            Rows=('Working_Prc_Off_Claim', 'size'),
            Working_Tot_Prc_Off_Amt=('Working_Tot_Prc_Off_Amt', 'sum'),
            Working_Prc_Off_Claim=('Working_Prc_Off_Claim', 'sum'),
            Working_DB_Margin_Amt=('Working_DB_Margin_Amt', 'sum'),
            Working_DB_Tot_Claim=('Working_DB_Tot_Claim', 'sum'),
        )
        .round(2)
        .sort_values('Working_DB_Tot_Claim', ascending=False)
        .reset_index(drop=True)
    )


def self_check(df_working: pd.DataFrame, tol: float = 0.01) -> pd.DataFrame:
    """OPTIONAL QA layer: if the uploaded dump already contains its own
    Pur Inv Amt / Prc Off Claim / DB Margin Amt columns (as CDMS RAW dumps
    typically do), compare them against the independently-built Working as
    an extra sense-check. Returns None if those columns aren't present.
    """
    needed = ['Pur Inv Amt', 'Prc Off Claim', 'DB Margin Amt']
    if any(c not in df_working.columns for c in needed):
        return None

    out = df_working.copy()
    out['Diff_Pur_Inv_Amt'] = (out['Pur Inv Amt'] - out['Working_Pur_Inv_Amt']).round(2)
    out['Diff_Prc_Off_Claim'] = (out['Prc Off Claim'] - out['Working_Prc_Off_Claim']).round(2)
    out['Diff_DB_Margin_Amt'] = (out['DB Margin Amt'] - out['Working_DB_Margin_Amt']).round(2)

    out['Pur_Inv_Amt_Status'] = np.where(out['Diff_Pur_Inv_Amt'].abs() <= tol, 'MATCH', 'MISMATCH')
    out['Prc_Off_Claim_Status'] = np.where(out['Diff_Prc_Off_Claim'].abs() <= tol, 'MATCH', 'MISMATCH')
    out['DB_Margin_Status'] = np.where(out['Diff_DB_Margin_Amt'].abs() <= tol, 'MATCH', 'MISMATCH')
    return out


def self_check_scorecard(check_df: pd.DataFrame) -> pd.DataFrame:
    n = len(check_df)
    rows = []
    for field, status_col in [
        ('Pur Inv Amt', 'Pur_Inv_Amt_Status'),
        ('Prc Off Claim', 'Prc_Off_Claim_Status'),
        ('DB Margin Amt', 'DB_Margin_Status'),
    ]:
        matched = int((check_df[status_col] == 'MATCH').sum())
        rows.append({
            'Field': field, 'Rows Checked': n, 'Matched': matched,
            'Mismatched': n - matched,
            'Match %': round(100 * matched / n, 2) if n else 0.0,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- Stage 2 --

PORTAL_REPORT_COLUMNS = {'Parent No', 'Claim Disc.', 'Claim Amount'}


def is_portal_report_format(df: pd.DataFrame) -> bool:
    """Detect the real CDMS Portal Report export: one row per claim type
    per distributor (Parent No / Claim Disc. / Claim Amount), rather than
    one row per distributor with separate amount columns."""
    return PORTAL_REPORT_COLUMNS.issubset(set(df.columns))


def pivot_portal_report(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot the long-format Portal Report into one row per distributor
    with 'DB Code', 'Prc Off Claim', 'DB Margin Amt' columns, ready for
    compare_with_claim().
    """
    pivot = (
        df.pivot_table(index='Parent No', columns='Claim Disc.', values='Claim Amount', aggfunc='sum')
        .reset_index()
    )
    pivot.columns.name = None
    pivot = pivot.rename(columns={'Parent No': 'DB Code'})
    for c in ['DB Margin Amt', 'Prc Off Claim']:
        if c not in pivot.columns:
            pivot[c] = 0.0
    return pivot.fillna(0)


def compare_with_claim(
    working_summary: pd.DataFrame,
    claim_df: pd.DataFrame,
    db_code_col: str,
    prc_off_claim_col: str,
    db_margin_col: str,
    distributor_col: str = None,
    tol: float = 1.0,
) -> pd.DataFrame:
    """Compare the Working (Stage 1 output, distributor-wise) against the
    actual CDMS Promo Claim file (Stage 2 upload). Merges on DB Code.

    tol: absolute currency tolerance for treating a distributor as MATCH.
    """
    claim = claim_df.rename(columns={
        db_code_col: 'DB Code',
        prc_off_claim_col: 'Actual_Prc_Off_Claim',
        db_margin_col: 'Actual_DB_Margin_Amt',
    })
    if distributor_col and distributor_col in claim_df.columns:
        claim = claim.rename(columns={distributor_col: 'Distributor Name (Claim)'})

    keep_cols = ['DB Code', 'Actual_Prc_Off_Claim', 'Actual_DB_Margin_Amt']
    if 'Distributor Name (Claim)' in claim.columns:
        keep_cols.append('Distributor Name (Claim)')

    claim_agg = (
        claim[keep_cols]
        .groupby('DB Code', as_index=False)
        .agg({
            'Actual_Prc_Off_Claim': 'sum',
            'Actual_DB_Margin_Amt': 'sum',
            **({'Distributor Name (Claim)': 'first'} if 'Distributor Name (Claim)' in keep_cols else {}),
        })
    )

    merged = working_summary.merge(claim_agg, on='DB Code', how='outer', indicator=True)

    merged['Working_Prc_Off_Claim'] = merged['Working_Prc_Off_Claim'].fillna(0)
    merged['Working_DB_Margin_Amt'] = merged['Working_DB_Margin_Amt'].fillna(0)
    merged['Actual_Prc_Off_Claim'] = merged['Actual_Prc_Off_Claim'].fillna(0)
    merged['Actual_DB_Margin_Amt'] = merged['Actual_DB_Margin_Amt'].fillna(0)

    merged['Diff_Prc_Off_Claim'] = (merged['Actual_Prc_Off_Claim'] - merged['Working_Prc_Off_Claim']).round(2)
    merged['Diff_DB_Margin_Amt'] = (merged['Actual_DB_Margin_Amt'] - merged['Working_DB_Margin_Amt']).round(2)
    merged['Working_DB_Tot_Claim'] = merged['Working_Prc_Off_Claim'] + merged['Working_DB_Margin_Amt']
    merged['Actual_DB_Tot_Claim'] = merged['Actual_Prc_Off_Claim'] + merged['Actual_DB_Margin_Amt']
    merged['Diff_DB_Tot_Claim'] = (merged['Actual_DB_Tot_Claim'] - merged['Working_DB_Tot_Claim']).round(2)

    def status(row):
        if row['_merge'] == 'left_only':
            return 'MISSING IN CLAIM FILE'
        if row['_merge'] == 'right_only':
            return 'NOT IN WORKING (unexpected DB Code)'
        if abs(row['Diff_DB_Tot_Claim']) <= tol:
            return 'MATCH'
        return 'OVER-CLAIMED' if row['Diff_DB_Tot_Claim'] > 0 else 'UNDER-CLAIMED'

    merged['Status'] = merged.apply(status, axis=1)

    if 'Distributor Name' not in merged.columns:
        merged['Distributor Name'] = None
    if 'Distributor Name (Claim)' in merged.columns:
        merged['Distributor Name'] = merged['Distributor Name'].fillna(merged['Distributor Name (Claim)'])
        merged = merged.drop(columns=['Distributor Name (Claim)'])

    cols = [
        'DB Code', 'Distributor Name',
        'Working_Prc_Off_Claim', 'Actual_Prc_Off_Claim', 'Diff_Prc_Off_Claim',
        'Working_DB_Margin_Amt', 'Actual_DB_Margin_Amt', 'Diff_DB_Margin_Amt',
        'Working_DB_Tot_Claim', 'Actual_DB_Tot_Claim', 'Diff_DB_Tot_Claim',
        'Status',
    ]
    return merged[cols].sort_values('DB Code').reset_index(drop=True)


def claim_accuracy_scorecard(comparison: pd.DataFrame) -> dict:
    n = len(comparison)
    matched = int((comparison['Status'] == 'MATCH').sum())
    total_working = comparison['Working_DB_Tot_Claim'].sum()
    total_actual = comparison['Actual_DB_Tot_Claim'].sum()
    total_variance = comparison['Diff_DB_Tot_Claim'].sum()
    return {
        'Distributors Checked': n,
        'Matched': matched,
        'Mismatched': n - matched,
        'Accuracy %': round(100 * matched / n, 2) if n else 0.0,
        'Total Working Claim': round(total_working, 2),
        'Total Actual Claim': round(total_actual, 2),
        'Total Variance': round(total_variance, 2),
    }
