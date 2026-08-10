# 🔴 DEBUG REPORT: "Onvoldoende data beschikbaar per store" Error

**Date:** 25 maart 2026  
**Error Location:** `visualisaties.py` line 329  
**Error Message:** "Onvoldoende data beschikbaar (minder dan 6 maanden per store)"

---

## Executive Summary

The error occurs because **participant_id and user_id are completely different ID systems with 0% overlap**. The code attempts to merge:
- `factor_score_histories` (keyed by `participant_id`) 
- `store_employees` (keyed by `user_id`)

By equating `participant_id == user_id`, which creates all NULL store_ids. After dropping NULLs, there's zero data remaining.

---

## 📊 Data Structure Analysis

### 1. CRITICAL ID MISMATCH

| Source | Count | Overlap | Note |
|--------|-------|---------|------|
| factor_score_histories.participant_id | 4,239 unique | 0% | Raw health scores |
| store_employees.user_id | 5,656 unique | 0% overlap with participant_id! | Employee->store mapping |
| users_met_scores.user_id | 3,948 unique | 0% overlap with participant_id | Computed scores |
| completions.participant_id | Matches factor_score_histories | - | Completion records |

**Conclusion:** `participant_id ≠ user_id` — These are separate systems that **are not directly connected in the parquet files**.

---

### 2. File-by-File Analysis

#### factor_score_histories.parquet
```
Shape: 77,017 rows × 9 columns
Columns: id, participant_id, questionnaire_factor_id, completion_id, 
         score_value, score_category_value, completion_created_at, created_at, updated_at

Key Stats:
  • 4,239 unique participant_ids
  • 35 unique questionnaire_factor_ids (score types)
  • Date range: 2018-05-28 → 2026-03-13
  • Zero NULL values
  
❌ Missing: user_id, store_id (the merge will fail!)
```

**Sample Factor IDs:**
- 1 → user_gender
- 7 → resilience_humorous
- 20 → hr_blood_pressure_non_invasive
- 29 → weight
- 5835 records for factor_id=7

---

#### store_employees.parquet  
```
Shape: 9,123 rows × 10 columns
Columns: id, public_id, user_id, store_id, email, employee_number, 
         accepted_terms_at, created_at, updated_at, deleted_at

Key Stats:
  • 5,656 unique user_ids (non-NULL: only 5,835 records)
  • 35 unique store_ids
  • ⚠️ 3,288 NULL user_ids (36% of data!)
  • ⚠️ 7,944 deleted records (87% marked as deleted)
  
❌ Missing: participant_id (no way to link to scores!)
```

**Store ID Distribution:**
- store_id=8: 2,002 employees
- store_id=35: 1,542 employees  
- store_id=34: 1,482 employees
- (35 stores total)

---

#### completions.parquet
```
Shape: 19,113 rows × 6 columns
Columns: id, participant_id, questionnaire_id, public_id, created_at, updated_at

Key Stats:
  • Bridges: completion_id ↔ participant_id
  • 19,113 unique completion records
  
❌ Missing: user_id, store_id
```

**Connection:** `completions.id` = `factor_score_histories.completion_id`

---

#### users_met_scores.parquet
```
Shape: 4,105 rows × 504 columns  
Key ID Columns: user_id, store_id, model_id

Key Stats:
  • 3,948 unique user_ids
  • 35 unique store_ids (!!!)
  • Contains 500+ computed score/recommendation columns
  
✓ HAS store_id
✓ HAS user_id
❌ Missing: participant_id (cannot connect to factor_score_histories!)
```

**This is the USER-STORE mapping table, but NOT linked to scores!**

---

#### questionnaire_elements.parquet
```
Shape: 611 rows × 14 columns
Columns: id, internal_name, slug, type, question, ...

Maps factor_id → slug:
  1 → user_gender
  7 → resilience_humorous  
  20 → hr_blood_pressure_non_invasive
  
Note: IDs 15, 16, 33, 35, 37 missing/unknown mappings
```

---

### 3. The Merge Failure Point

**visualisaties.py line 293-299:**
```python
df_merged = df_history.merge(
    df_store_emp[['user_id', 'store_id']],
    left_on='participant_id',           # ❌ 4,239 unique values
    right_on='user_id',                 # ❌ 5,656 unique values  
    how='left'                          # Only NULLs match!
)
df_merged = df_merged.dropna(subset=['store_id'])  # ❌ ALL rows dropped!
```

**Result:** 
- Merge produces 77,017 rows with store_id = NaN (0% match rate)
- After dropna: 0 rows remain
- No data to group by store/month → error triggered

---

## 🔗 Missing Connection: How to Link participant_id to user_id?

The database likely contains:

### Hypothesis 1: participants table (in database)
```sql
SELECT participant_id, user_id FROM participants;
```
Would provide the missing `participant_id → user_id` mapping.

### Hypothesis 2: Check if mapping is in pmo_werkbaar.parquet
- 2,456 rows × 647 columns
- Has `completion_id` column (links to completions.id)
- Need to check if it contains user/participant info

### Hypothesis 3: user_meta or participant_meta tables
- May exist in database with id mappings
- Not present in parquet files

---

## ✅ Available Score Types (questionnaire_factor_ids)

From factor_score_histories.parquet:

| ID  | Slug | Records | Category |
|-----|------|---------|----------|
| 1   | user_gender | 1,337 | Demographics |
| 5-14 | resilience_* | ~4,500 ea | Mental Health |
| 17  | user_gender_inclusive | 4,314 | Demographics |
| 18-28 | hr_* | 2,000-5,000 | Health Risk |
| 29  | weight | 585 | Health |
| 31-32 | ls_exercise_* | 819+ | Lifestyle |

**Total:** 35 distinct score types available

---

## 🚨 Data Quality Issues

### store_employees.parquet
- ⚠️ **36% NULL user_ids** (3,288 / 9,123)
- ⚠️ **87% deleted records** (7,944 / 9,123)
- Only ~5,835 "valid" records
- Major data integrity concern!

### factor_score_histories.parquet
- ✓ No NULLs
- ✓ Clean data
- ❌ No store mapping

---

## 🔧 Recommended Solutions

### Option 1: Query Database for participant→user Mapping ⭐ BEST
```python
engine = create_engine(db_url)
df_participant_user = pd.read_sql(
    "SELECT id as participant_id, user_id FROM participants",
    engine
)

# Then merge:
df_merged = df_history.merge(df_participant_user, on='participant_id', how='left')
df_merged = df_merged.merge(
    df_store_emp[['user_id', 'store_id']], 
    on='user_id', 
    how='left'
)
df_merged = df_merged.dropna(subset=['store_id'])
```

### Option 2: Create Mapping from Available Data
- Query: `SELECT DISTINCT completion_id, user_id FROM store_employee_question_answers`
- Join with completions to get participant_id
- Build mapping table

### Option 3: Use completion_scores.parquet
- completion_scores has completion_id
- Merge with completions to get participant_id
- Check if completion_scores has user/store info

### Option 4: Cache the Mapping
Once mapping is found, save as parquet:
```
participant_id,user_id,store_id
16910,XXX,8
16911,YYY,35
...
```

---

## ✋ Stop-Gap Fix

Modify `maak_store_scoreverbetering_plot()` to check for mapping availability:

```python
# NEW: Load participant->user mapping from database
df_participant_mapping = pd.read_sql(
    "SELECT id as participant_id, user_id FROM participants",
    engine  # Add db_url parameter
)

# Merge scores with mapping
df_with_user = df_history.merge(df_participant_mapping, 
                                 on='participant_id', how='left')

# Then merge with store employees
df_merged = df_with_user.merge(
    df_store_emp[['user_id', 'store_id']],
    on='user_id',
    how='left'
)
df_merged = df_merged.dropna(subset=['store_id'])

# Check for data before proceeding
if len(df_merged) == 0:
    # Diagnostic message
    logging.error(f"No participants found in store_employees!")
    logging.error(f"participant_ids: {df_history['participant_id'].nunique()}")
    logging.error(f"user_ids in store_employees: {df_store_emp['user_id'].nunique()}")
    # Return error chart
```

---

## 📋 Summary Table: Data Availability

| File | Records | participant_id | user_id | store_id | Usable for Merging |
|------|---------|---|---|---|---|
| factor_score_histories | 77,017 | ✓ (4,239) | ✗ | ✗ | Partial ❌ |
| store_employees | 9,123 | ✗ | ✓ (5,656) | ✓ (35) | Partial ❌ |
| completions | 19,113 | ✓ (4,239) | ✗ | ✗ | Bridging only |
| users_met_scores | 4,105 | ✗ | ✓ (3,948) | ✓ (35) | No scores ❌ |
| completion_scores | 4.3M | ✗ | ✗ | ✗ | No ID fields ❌ |
| latest_scores | 1M | ✓ | ✗ | ✗ | Scores only ❌ |

**Needed:** `participants` table from database with `participant_id` ↔ `user_id` mapping

---

## Next Steps

1. **Query the database:**
   ```sql
   SELECT * FROM participants LIMIT 5;
   SELECT * FROM information_schema.tables WHERE table_schema = 'your_db';
   ```

2. **Check for stored mapping in pmo_werkbaar:**
   - Does it have user_id column? Check columns beyond first 647
   - Can it bridge completion_id → user_id?

3. **Verify:** After getting the mapping, test:
   ```python
   fsh = pd.read_parquet('factor_score_histories.parquet')
   mapping = pd.read_sql(...) 
   ums = pd.read_parquet('users_met_scores.parquet')
   
   # Should get >0 records
   result = fsh.merge(mapping, on='participant_id').merge(
       ums[['user_id', 'store_id']], on='user_id'
   )
   assert len(result) > 0, "Still no data!"
   ```

