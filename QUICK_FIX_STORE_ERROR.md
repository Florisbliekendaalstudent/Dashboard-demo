# 🔧 QUICK FIX: "Onvoldoende data beschikbaar per store" Error

## The Problem (One Sentence)
**`participant_id` ≠ `user_id`** — The merge in `visualisaties.py` line 293 joins on mismatched IDs, producing 0% match rate and no data.

---

## Root Cause (Verified)
```
factor_score_histories.participant_id: 4,239 unique values
store_employees.user_id: 5,656 unique values
Overlap: 0 records (0%)  ❌
```

Current merge logic:
```python
df_merged = df_history.merge(
    df_store_emp[['user_id', 'store_id']],
    left_on='participant_id',   # 4,239 values
    right_on='user_id',         # 5,656 values
    how='left'                  # Result: 0 matches
)
# → All 77,017 rows get store_id = NaN
# → After dropna: 0 rows remain ❌
```

---

## Solution: Query the Database for participant→user Mapping

The `participants` table in your database contains the missing connection:

```sql
SELECT id as participant_id, user_id FROM participants;
```

### Updated visualisaties.py - Function maak_store_scoreverbetering_plot

**Location:** Line 258+ (replace entire function or patch the merge section)

```python
def maak_store_scoreverbetering_plot(base_pad: Path, db_url: str, 
                                      score_type: str = 'job_satisfaction',
                                      maanden_window: int = 3) -> go.Figure:
    """Fixed version with proper participant→user mapping"""
    
    # 1. Load data
    df_history = laad_longitudinale_data(base_pad, db_url)
    df_history = df_history[df_history['slug'] == score_type].copy()
    
    if len(df_history) == 0:
        fig = go.Figure()
        fig.add_annotation(text=f"Geen data beschikbaar voor score-type '{score_type}'.", 
                          showarrow=False, font=dict(size=14))
        return fig
    
    # 2. Get participant→user mapping from database ✨ FIX
    engine = create_engine(db_url)
    df_participant_mapping = pd.read_sql(
        "SELECT id as participant_id, user_id FROM participants",
        engine
    )
    
    # 3. Store-employees mapping laden
    df_store_emp = pd.read_parquet(base_pad / 'store_employees.parquet')
    
    # 4. Score waarden numeriek maken
    df_history['score_value'] = pd.to_numeric(df_history['score_value'], errors='coerce')
    df_history = df_history.dropna(subset=['score_value', 'completion_created_at'])
    
    # 5. FIXED MERGE: participant_id → user_id → store_id ✨
    df_merged = (
        df_history.merge(df_participant_mapping, on='participant_id', how='left')
        .merge(
            df_store_emp[['user_id', 'store_id']],
            on='user_id',
            how='left'
        )
    )
    df_merged = df_merged.dropna(subset=['store_id'])
    
    # 6. Diagnostic: Check if merge worked
    if len(df_merged) == 0:
        fig = go.Figure()
        fig.add_annotation(
            text=f"Onvoldoende data beschikbaar (participants misschien niet gekoppeld).",
            showarrow=False, font=dict(size=14)
        )
        import logging
        logging.error(f"Merge failed for {score_type}:")
        logging.error(f"  - factor_score_histories records: {len(df_history)}")
        logging.error(f"  - participants found in mapping: {df_merged.shape[0]}")
        logging.error(f"  - records with store_id: {df_merged['store_id'].notna().sum()}")
        return fig
    
    # 7. Per store en maand gemiddelde score berekenen
    # [Rest of function remains the same...]
    df_merged['jaar_maand'] = df_merged['completion_created_at'].dt.to_period('M')
    
    df_agg = df_merged.groupby(['jaar_maand', 'store_id']).agg({
        'score_value': ['mean', 'count'],
    }).reset_index()
    df_agg.columns = ['jaar_maand', 'store_id', 'score_mean', 'n_metingen']
    df_agg = df_agg[df_agg['n_metingen'] >= 3]
    
    df_agg['timestamp'] = df_agg['jaar_maand'].dt.to_timestamp()
    df_agg = df_agg.sort_values('timestamp')
    
    store_id_map = {
        1: 'Zeeman NL', 2: 'Zeeman BE', 3: 'Zeeman FR', 4: 'Zeeman DE', 5: 'Zeeman AT', 
        6: 'Zeeman CZ', 7: 'Zeeman HU', 8: 'Zeeman PL', 9: 'Zeeman RO',
    }
    df_agg['store_naam'] = df_agg['store_id'].map(store_id_map).fillna('Store ' + df_agg['store_id'].astype(str))
    
    store_counts = df_agg.groupby('store_naam').size()
    grote_stores = store_counts[store_counts >= 6].index.tolist()
    df_agg = df_agg[df_agg['store_naam'].isin(grote_stores)]
    
    if len(df_agg) == 0:
        fig = go.Figure()
        fig.add_annotation(text="Onvoldoende data beschikbaar (minder dan 6 maanden per store).", 
                          showarrow=False, font=dict(size=14))
        return fig
    
    # [Continue with original plotting code...]
    fig = go.Figure()
    kleuren = [HOOFD_KLEUR, GENDER_COLORS['Man'], GENDER_COLORS['Vrouw'], 
               RISICO_COLORS[0], RISICO_COLORS[1], RISICO_COLORS[2], 
               '#9B59B6', '#16A085', '#F39C12', '#34495E']
    
    for i, store_naam in enumerate(sorted(grote_stores)):
        df_store = df_agg[df_agg['store_naam'] == store_naam].sort_values('timestamp')
        df_store = df_store.copy()
        df_store['score_smooth'] = df_store['score_mean'].rolling(
            window=maanden_window, center=True, min_periods=1
        ).mean()
        
        fig.add_trace(go.Scatter(
            x=df_store['timestamp'],
            y=df_store['score_smooth'],
            mode='lines+markers',
            name=store_naam,
            line=dict(width=2, color=kleuren[i % len(kleuren)]),
            marker=dict(size=6),
            hovertemplate=(
                f'<b>{store_naam}</b><br>Datum: %{x|%b %Y}<br>Gemiddelde score: %{y:.2f}<extra></extra>'
            ),
        ))
    
    score_labels = {
        'job_satisfaction': 'Werktevredenheid',
        'stress': 'Stressniveau',
        'wellbeing': 'Welzijn',
        'work_life_balance': 'Work-life balans',
        'workload': 'Werkdruk',
        'working_attitude': 'Werkhouding',
        'exercise': 'Beweging',
        'bmi': 'BMI',
        'dass_stress': 'DASS Stress',
        'dass_anxiety': 'DASS Angst',
        'dass_depression': 'DASS Depressie',
        'resilience': 'Veerkracht',
    }
    
    score_label_nl = score_labels.get(score_type, score_type)
    
    fig.update_layout(
        title=f'Score verbetering over tijd per werkomgeving: {score_label_nl}',
        xaxis=dict(title='Periode', tickformat='%b %Y'),
        yaxis=dict(title=f'Gemiddelde {score_label_nl.lower()} ({maanden_window} mnd. voortschrijdend gemiddelde)'),
        hovermode='x unified',
        height=500,
        template='plotly_white',
        legend=dict(orientation='v', yanchor='top', y=0.99, xanchor='left', x=0.01, 
                   bgcolor='rgba(255, 255, 255, 0.8)'),
    )
    
    return fig
```

---

## Key Changes Summary

| Line | Change | Reason |
|------|--------|--------|
| ~267 | Add `engine = create_engine(db_url)` | Enable database access |
| ~269-272 | Query `participants` table | Get participant_id→user_id mapping |
| ~282-287 | Chain two merges: first by participant_id, then by user_id | Proper ID linkage |
| ~289-300 | Add diagnostic logging | Detect future failures early |

---

## Validation Script

Run this to confirm the fix works:

```python
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine

BASE = Path("/Users/bliekendaal/Desktop/Code")
DB_URL = "your_database_url_here"

# Load data
fsh = pd.read_parquet(BASE / "factor_score_histories.parquet")
se = pd.read_parquet(BASE / "store_employees.parquet")

# Get mapping from database
engine = create_engine(DB_URL)
df_mapping = pd.read_sql("SELECT id as participant_id, user_id FROM participants", engine)

# Test the merge chain
df_merged = fsh.merge(df_mapping, on='participant_id', how='left')
df_merged = df_merged.merge(se[['user_id', 'store_id']], on='user_id', how='left')

print(f"Total records: {len(df_merged)}")
print(f"Records with store_id: {df_merged['store_id'].notna().sum()}")
print(f"Match rate: {df_merged['store_id'].notna().sum() / len(df_merged) * 100:.1f}%")

# Should show > 0%  ✅
assert df_merged['store_id'].notna().sum() > 0, "Merge still returns 0 records!"
print("\n✅ Fix validated successfully!")
```

---

## Alternative: Verify Database Query Works

Before applying the fix, test the database connection:

```python
from sqlalchemy import create_engine
import pandas as pd

DB_URL = "mysql+pymysql://user:password@host:3306/database"
engine = create_engine(DB_URL)

# Quick test
result = pd.read_sql("SELECT COUNT(*) as cnt FROM participants", engine)
print(f"Participants table has {result['cnt'][0]} rows")

# Sample mapping
sample = pd.read_sql("SELECT id, user_id FROM participants LIMIT 5", engine)
print("\nSample participant→user mapping:")
print(sample)
```

---

## Files Provided

1. **DEBUG_REPORT_STORE_ERROR.md** — Full diagnostic report with all data analysis
2. **diagnose_store_error.py** — Python diagnostic script
3. **This file** — Quick fix guide with code

---

## Next Steps

1. ✅ Verify the database query returns data:
   ```sql
   SELECT COUNT(*) FROM participants;
   ```

2. ✅ Apply the fix to visualisaties.py (3-chain merge)

3. ✅ Test with: `python diagnose_store_error.py` 

4. ✅ Run dashboard and verify scores display per store

