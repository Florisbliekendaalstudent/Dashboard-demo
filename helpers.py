import pandas as pd
import numpy as np

def get_numeric_clean(df, kolom):
    """Zet een kolom om naar numeriek, vervangt 'None' door NaN."""
    if df is None or df.empty or kolom not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[kolom].replace('None', np.nan), errors='coerce')

def filter_by_gender(df, gender):
    """Filtert op geslacht: 'man', 'vrouw', 'beide' of 'totaal'."""
    if df is None or df.empty or gender in ('beide', 'totaal'):
        return df
    # 1=man, 0=vrouw
    val = 1 if gender == 'man' else 0
    return df[pd.to_numeric(df['rec_user_gender'], errors='coerce') == val]

def normalize_to_scale(s, target_max=10):
    """Normaliseert een serie naar een schaal (bijv. 0-10)."""
    if s.empty or s.max() == 0:
        return s
    return s * (target_max / s.max())

def calculate_kpi_count(df, kolom, waarde, op='eq'):
    """Berekent KPI tellingen (aantal, totaal, percentage)."""
    if df is None or df.empty or kolom not in df.columns:
        return 0, 0, 0.0
    s = pd.to_numeric(df[kolom], errors='coerce')
    n_geldig = int(s.notna().sum())
    if n_geldig == 0:
        return 0, 0, 0.0
    count = int(s.ge(waarde).sum() if op == 'ge' else s.eq(waarde).sum())
    pct = count / n_geldig * 100
    return count, n_geldig, pct

def aggregate_by_groups(df, groupby_cols, agg_dict):
    """Groepeert en aggregeert veilig voor analysemodules."""
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        return df.groupby(groupby_cols, dropna=False).agg(agg_dict).reset_index()
    except Exception:
        return pd.DataFrame()

def export_to_csv(df):
    """Converteert dataframe naar CSV bytes voor download."""
    if df is None:
        return b""
    return df.to_csv(index=False).encode('utf-8')


def _maak_net_label(naam: str) -> str:
    """Converteert een interne kolomnaam naar een leesbaar label."""
    vervang = naam
    for prefix in ('rec_', 'ls_', 'med_', 'asr_', 'digital_detox_'):
        vervang = vervang.replace(prefix, '')
    return (
        vervang
        .replace('_', ' ')
        .replace('psqi', 'PSQI')
        .replace('dass', 'DASS')
        .replace('wai', 'WAI')
        .strip()
        .title()
    )
