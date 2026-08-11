# Dataset Drop-in Guide

Deze repo verwacht een kleine synthetische demo-dataset set die het dashboard kan laden zonder verdere codeaanpassingen.

## Vereiste data bestanden

Zet deze twee CSV-bestanden in de projectdatafolder:

- data/demo_participants.csv
- data/demo_completions.csv

## Optimale schema

### demo_participants.csv

De deelnemersdataset moet minimaal deze kolommen bevatten:

- participant_id
- user_id
- store_id
- rec_user_gender
- rec_age_current
- postal_code
- rec_med_bmi
- rec_med_bmi_cat
- rec_heartrisk
- rec_heartrisk_cat
- rec_ls_stress_sum
- rec_ls_stress_cat
- rec_ls_sleep_psqi_sum
- rec_ls_sleep_cat
- rec_ls_score_exercise
- rec_ls_exercise_steps_per_day
- rec_ls_score_fruit
- rec_ls_score_vegetables
- rec_ls_score_sugar
- rec_ls_score_saturated_fat
- rec_ls_score_natrium
- rec_ls_score_alcohol
- rec_ls_exercise_physical_activity_minutes_total
- rec_ls_lifestyle_score
- rec_dass_stress_score
- rec_dass_anxiety_score
- rec_dass_depression_score
- rec_resilience_score
- rec_wellbeing_score
- rec_self_efficacy_score
- rec_smoking_answer
- rec_health
- latest_completion_at

### demo_completions.csv

De completion-history moet minimaal deze kolommen bevatten:

- id
- participant_id
- user_id
- created_at

## Wat je moet doen

1. Open de `data/` folder in de repo.
2. Verwijder of vervang de bestaande demo CSV's.
3. Plaats je nieuwe CSV's onder bovenstaande namen.
4. Start de app opnieuw.

## Verificatie checklist

Na het plaatsen van de CSV's moet het dashboard kunnen lezen:

- de deelnemersdataset is niet leeg
- het aantal rijen van demo_participants.csv is binnen de gewenste range (ongeveer 300-500)
- demo_completions.csv bevat records die kunnen worden gekoppeld via participant_id
- de kolommen `latest_completion_at` en `created_at` kunnen worden gelezen als datums
