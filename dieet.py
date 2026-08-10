import pandas as pd
from pathlib import Path

df = pd.read_parquet(Path('/Users/bliekendaal/Desktop/Code/users_met_scores.parquet'))
score_cols = ['rec_ls_score_fruit', 'rec_ls_score_vegetables', 'rec_ls_score_sugar',
              'rec_ls_score_saturated_fat', 'rec_ls_score_alcohol', 'rec_ls_score_natrium']
for col in score_cols:
    if col in df.columns:
        print(f"{col}: min={df[col].min():.1f}, max={df[col].max():.1f}, mean={df[col].mean():.1f}")