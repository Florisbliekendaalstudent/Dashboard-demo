# Smart Health Data Structure Summary

**Generated:** 25 maart 2026

## 1. Work Environment Categories (ASR Columns)

The work environment data is tracked through **ASR (Arbeids- en Stress Gerelateerde) questions** - a Dutch workplace wellbeing assessment framework.

### Available Work Environment Score Columns:

| Column Name | Label | Scale | Description |
|---|---|---|---|
| `rec_asr_wai_score` | Werkvermogen Index (Work Ability Index) | 0-10 | Originally 7-49. Ranges: <5 Slecht, 5-7 Matig, 7-8.5 Goed, >8.5 Uitstekend |
| `rec_asr_burn_out_score` | Burn-out Risico | 0-10 | Risk of burnout; higher = greater risk |
| `rec_asr_vitality_score` | Vitaliteit | 0-10 | Vitality at work; higher = more vital |
| `rec_asr_job_satisfaction_score` | Werktevredenheid | 0-10 | Job satisfaction; higher = more satisfied |
| `rec_asr_workload_score` | Werkdruk | 0-10 | Workload; higher = higher pressure |
| `rec_asr_exhaustion_score` | Uitputting | 0-10 | Exhaustion level; higher = more exhausted |

### Related Work Environment Burden Columns:

- `asr_burden_workplace` - Physical workplace burden
- `asr_burden_noise` - Noise burden
- `asr_burden_climatic` - Climatic burden
- `rec_asr_absent_at_work_score` - Absenteeism score (currently has only 1 unique value)

### Work Environment Categorical Columns (Not Recommended - Category Versions):

These are derived categories from the scores above and are excluded from primary analysis:
- `rec_asr_work_experience_category`
- `rec_asr_job_satisfaction_category`
- `rec_asr_working_attitude_category`
- `rec_asr_workload_category`
- `rec_asr_worksituation_category`
- `rec_asr_work_ability_category`

### Additional Work-Related Dimensions:

The system also tracks these work-related psychological factors:
- `rec_asr_commitment_organisation_*` - Organizational commitment dimensions
- `rec_asr_job_security_*` - Job security components
- `rec_asr_personal_competences_*` - Personal workplace competencies
- `rec_asr_minor_mental_complaints_*` - Mental health indicators at work
- Individual question aspects (prefixed with `asr_` without `rec_`):
  - Colleagues support, collaboration, communication
  - Manager support and clarity
  - Policy and organizational structure
  - Health and safety climate

---

## 2. All Score Columns Tracking Improvements Over Time

The system tracks 50+ individual scores that show progression and improvement:

### Lifestyle Scores (0-5 scale, higher = better):
- `rec_ls_score_fruit`
- `rec_ls_score_vegetables`
- `rec_ls_score_sugar`
- `rec_ls_score_saturated_fat`
- `rec_ls_score_alcohol`
- `rec_ls_score_natrium` (salt/sodium)
- `rec_ls_score_exercise`
- `rec_ls_score_sleep`

### Aggregate Lifestyle Score:
- `rec_ls_lifestyle_score` - Combined lifestyle score

### Medical/Health Risk Scores:
- `rec_med_bmi` - Body Mass Index (raw value)
- `rec_med_bmi_cat` - BMI category (categorical)
- `rec_heartrisk` - Framingham cardiovascular risk score (continuous)
- `rec_heartrisk_cat` - Heart risk category (0=Laag, 1=Matig, 2=Hoog)
- `rec_framingham_non_invasive` - Non-invasive Framingham score

### Stress & Mental Health Scores:
- `rec_ls_stress_sum` - Total stress score (0-28, scaled to 0-10)
- `rec_ls_stress_cat` - Stress category (0=Weinig, 1=Matig, 2=Veel)
- `rec_ls_stress_type_1_worry` - Worry dimension (0-2)
- `rec_ls_stress_type_2_tense` - Tension dimension (0-2)
- `rec_dass_stress_score` - DASS stress (0-42)
- `rec_dass_anxiety_score` - DASS anxiety (0-36)
- `rec_dass_depression_score` - DASS depression (0-42)

### Psychological Well-being Scores:
- `rec_resilience_score` - Resilience/Veerkracht (0-40, scaled to 0-10)
- `rec_wellbeing_score` - Wellbeing/Welzijn (0-10)
- `rec_self_efficacy_score` - Self-efficacy/Zelfeffectiviteit (0-40, scaled to 0-10)

### Sleep Quality:
- `rec_ls_sleep_psqi_sum` - PSQI total score (0-20, higher = worse sleep)
- `rec_ls_sleep_psqi_component_3_sleep_duration` - Duration component

### Physical Activity:
- `rec_ls_exercise_cat` - Exercise category (0=Laag, 1=Matig, 2=Hoog)
- `rec_ls_exercise_minutes_cat` - Exercise minutes category
- `rec_ls_exercise_steps_cat` - Steps per day category (0=<5K, 1=5-10K, 2=>10K)

### Dietary Components (gram/day or count):
- `rec_ls_nutrition_fruit_fruit_per_day` - Fruits per day
- `rec_ls_vegetables_gram_per_day` - Vegetables (grams/day)
- `rec_ls_nutrition_sugar_per_day` - Sugar (grams/day, max filter: 300)
- `rec_ls_nutrition_saturated_fat_per_day` - Saturated fat (grams/day, max filter: 150)
- `rec_ls_nutrition_natrium_per_day` - Sodium (mg/day, max filter: 8000)
- `rec_ls_alcohol_total_per_week` - Alcohol (glasses/week)

### Work-Related Scores (see Section 1):
- `rec_asr_wai_score` - Work Ability Index
- `rec_asr_burn_out_score` - Burnout risk
- `rec_asr_vitality_score` - Vitality
- `rec_asr_job_satisfaction_score` - Job satisfaction
- `rec_asr_workload_score` - Workload/pressure
- `rec_asr_exhaustion_score` - Exhaustion

### Digital Health:
- `rec_digital_detox_stress_score` - Stress related to digital use

---

## 3. Data Structure & File Formats

### Main Data Sources:

#### Primary User Scores File:
- **Path:** `users_met_scores.parquet`
- **Format:** Apache Parquet (columnar format)
- **Records:** 15,226+ unique users (after deduplication by user_id)
- **Structure:** One row per unique user with most recent scores
- **Key Field:** `user_id`
- **Note:** Users can appear in multiple rows if connected to multiple stores/models; use `drop_duplicates(subset='user_id', keep='first')` for unique users

#### Other Major Files:
- `factor_score_histories.parquet` - Historical score tracking (for longitudinal analysis)
- `completions.parquet` - Survey completions metadata
- `participants.parquet` - Participant information
- `users_mysql.parquet` - MySQL user records
- `my_clic_participants.parquet` - CLIC program participants
- `store_employees.parquet` - Store employee relationships
- `addresses.parquet` - Location data (users, stores, models)
- `pmo_werkbaar.parquet` - PMO workplace assessment data
- `completion_scores.parquet` - Scores per completion event
- `latest_scores.parquet` - Most recent scores per participant

### Data Types:
- **Parquet files:** Compressed binary format, optimized for analytics
- **CSV files:** Only `users_mysql.csv` in the tabellen/ directory
- **GeoJSON:** Map data in HTML folder for spatial analysis

---

## 4. Time/Date Structure in Data

### Date Columns Available:

#### In Cross-Sectional Data (`users_met_scores.parquet`):
- **No explicit date field** - Data represents the most recent snapshot
- Timestamps are embedded in the creation of the composite dataset

#### In Longitudinal Data (`factor_score_histories.parquet`):
- `completion_created_at` - When the assessment was completed (timestamp)
- **Format:** DateTime (YYYY-MM-DD HH:MM:SS)
- **Range:** 2019-2025 (Primary focus: 2019-2025)
- **Granularity:** Per completion event (user can have multiple assessments)

#### In Completion Records:
- `completions.created_at` - When survey was started/created
- Can be linked to `factor_score_histories` via `completion_id`

### Tracking Improvements Over Time:

**Current Approach (from `bereken_verandering()` function):**

```python
# In factor_score_histories:
# 1. Group by participant_id + slug (score type)
# 2. Sort by completion_created_at
# 3. Calculate change: current_score - first_score
# 4. Track days elapsed since first assessment
# 5. Bin into periods:
#    - 0-6 months
#    - 6-12 months
#    - 1-2 years
#    - 2-3 years
#    - 3+ years
```

**Measurement Frequency:**
- Variable: Users complete assessments at different intervals
- Some have multiple measurements per year; others have single measurements
- Data covers 2019-2025 (7 years of historical data available)

### Geographic & Temporal Distribution:

**User Locations:**
- `postal_code` field in `users_met_scores.parquet`
- Can extract PC3 (first 3 digits) for regional analysis
- Top cities: Venlo, Utrecht, Amersfoort, Rotterdam, Roermond, Leusden, etc.

**Store Information:**
- Stores have addresses with `lat`/`long` coordinates
- Stored in `addresses.parquet` with `model_type='store'`
- Can track which store is associated with users for organizational comparisons

---

## 5. Key Relationships & Linkage Structure

### User ↔ Score Links:

```
users_met_scores.parquet
    ├── user_id (primary identifier)
    ├── store_id (which employer/store)
    ├── model_id (which organization)
    └── All scores (rec_* columns)

factor_score_histories.parquet (longitudinal)
    ├── participant_id
    ├── questionnaire_factor_id → questionnaire_factors.slug
    ├── completion_id
    ├── score_value
    └── completion_created_at
```

### Cross-linking Data:

**Store Employee → User → Scores:**
- `store_employees.parquet`: `store_id` + `user_id`
- Links employees to workplaces
- Allows analysis by employer

**Participant → Completion → Score:**
- `participants.id` linked to `completions.participant_id`
- `completions.id` linked to `factor_score_histories.completion_id`
- Provides chronological tracking

**User → Address:**
- `addresses.parquet` uses `model_type='user'` + `model_id=user_id`
- Contains `lat`/`long` for mapping

---

## 6. Data Quality Notes

### Missing Data Patterns:

**Well-populated columns (>90% non-null):**
- `rec_med_bmi_cat`: 14,414 values
- `rec_heartrisk_cat`: 13,429 values
- `rec_ls_exercise_*`: 13,442+ values

**Moderately populated (50-90% non-null):**
- Most lifestyle scores and DASS scores
- Work-related ASR scores

**Sparse columns (<20% non-null):**
- Category columns (use primary score columns instead)
- Digital detox scores: 162 values
- Menopause scores: 30 values (women-specific)

### Outlier Handling:

Pre-defined outlier thresholds for common columns:
- Sodium: `8000 mg/day` max
- Sugar: `300 g/day` max
- Saturated fat: `150 g/day` max
- Vegetables: `800 g/day` max
- Alcohol: `56 glasses/week` max

---

## 7. Analysis Functions Available

### Key Functions (in `visualisaties.py`):

```python
laad_data(base_pad)                           # Load primary cross-sectional data
laad_longitudinale_data(base_pad, db_url)     # Load historical scores
bereken_verandering(df_history)               # Calculate score changes over time
bereken_datakwaliteit(df)                     # Data quality assessment
```

### Score Categories for Stratified Analysis:

**By Demographic:**
- `rec_user_gender` (0=Female, 1=Male)
- `rec_age_current` (age in years)

**By Organization:**
- `store_id` - Associate with store/employer
- Organization-level score comparisons available

---

## Summary Table

| Dimension | Information |
|---|---|
| **Work Environment Categories** | 6 primary ASR scores (WAI, Burnout, Vitality, Job Satisfaction, Workload, Exhaustion) + 12+ additional burden/commitment dimensions |
| **Score Columns Total** | 50+ individual scores tracking lifestyle, health, stress, work capacity, wellbeing |
| **Time Tracking** | Longitudinal data covers 2019-2025; historical scores available via factor_score_histories |
| **Primary Data File** | `users_met_scores.parquet` (15,226 unique users) |
| **Longitudinal File** | `factor_score_histories.parquet` (multiple measurements per user) |
| **Date Granularity** | Per completion event (variable frequency, tracking from 2019-2025) |
| **Geographic Data** | Postal codes (PC3 available), latitude/longitude for stores and users |
| **Format** | Parquet (compressed columnar), linked via PostgreSQL database |
| **Key Linkage** | user_id → store_id → participant_id → completion_id → factor_score_histories |
