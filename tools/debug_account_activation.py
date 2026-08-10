from pathlib import Path
import pandas as pd
from visualisaties import _laad_actieve_users, load_my_clic_participants_expanded
from config import DB_URL

base = Path('/Users/bliekendaal/Desktop/Code')

print('Loading users...')
df_users = _laad_actieve_users(base, include_deleted=False)
print('users rows:', len(df_users))
print('users columns:', df_users.columns.tolist())
cols = [c for c in ['id','participant_id','created_at','jaar'] if c in df_users.columns]
print(df_users[cols].head(10))

print('\nLoading scores...')
df_scores = load_my_clic_participants_expanded(DB_URL)
print('scores rows:', len(df_scores))
print('scores columns:', df_scores.columns.tolist())
print(df_scores.head(10))

# determine active ids as in visualisaties
if 'participant_id' in df_scores.columns:
    actieve_ids = set(pd.to_numeric(df_scores['participant_id'], errors='coerce').dropna().astype(int))
else:
    print('No participant_id in scores')
    actieve_ids = set()

print('\nactive ids count:', len(actieve_ids))

# Check latest_completion_at
if 'latest_completion_at' in df_scores.columns:
    completed = df_scores[df_scores['latest_completion_at'].notna()].drop_duplicates(subset='participant_id', keep='first')
    print('scores with latest_completion_at (unique participant_ids):', len(completed))
    completed_ids = set(pd.to_numeric(completed['participant_id'], errors='coerce').dropna().astype(int))
    try:
        user_ids_set = set(pd.to_numeric(df_users['id'], errors='coerce').dropna().astype(int))
        print('intersection users vs completed ids:', len(user_ids_set.intersection(completed_ids)))
    except Exception:
        print('Could not compute intersection with users')
    # For diagnostics, use completed_ids as actieve_ids (mirrors updated logic)
    actieve_ids = completed_ids
else:
    print('No latest_completion_at in scores')

# determine id_column used in visualisaties
id_column = 'id' if 'id' in df_users.columns else 'participant_id' if 'participant_id' in df_users.columns else None
print('id_column used:', id_column)

if id_column is not None:
    df_users['id_num'] = pd.to_numeric(df_users[id_column], errors='coerce')
    df_users['actief_match'] = df_users['id_num'].isin(actieve_ids)
    print('\nSample id_num and actief_match:')
    cols2 = [c for c in ['id', 'participant_id', 'id_num', 'actief_match'] if c in df_users.columns]
    print(df_users[cols2].head(20))
    totaal = len(df_users)
    actief_count = int(df_users['actief_match'].sum())
    print(f'Calculated actief_count={actief_count} / totaal={totaal} -> pct={100*actief_count/totaal if totaal else 0:.1f}%')
else:
    print('No id column in users')

# Show examples where actives are true
if id_column is not None:
    print('\nRows where actief_match is True (sample 20):')
    print(df_users[df_users['actief_match']].head(20))

print('\nDone')
