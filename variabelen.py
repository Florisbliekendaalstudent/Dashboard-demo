"""
Variabelenregister voor de EDA verkenner.
kleur_richting:
  'eerste_goed'  = eerste categorie groen, laatste rood (bijv. nooit roken = goed)
  'laatste_goed' = eerste categorie rood, laatste groen (bijv. veel stappen = goed)
  'midden_goed'  = uitersten rood, midden groen (bijv. slaapuren)
schaal_factor: vermenigvuldig ruwe waarde voor weergave (bijv. 2.0 voor 0-5 -> 0-10)
"""

VARIABELEN = [

    # ── Demografisch ──────────────────────────────────────────────────────────
    {
        'label':        'Leeftijd',
        'kolom':        'rec_age_current',
        'plot_type':    'histogram',
        'groep':        'Demografisch',
        'omschrijving': 'Verdeling van de leeftijd van deelnemers.',
        'split_gender': True,
        'eenheid':      'jaar',
    },
    {
        'label':        'BMI (ruwe waarde)',
        'kolom':        'rec_med_bmi',
        'plot_type':    'histogram',
        'groep':        'Demografisch',
        'omschrijving': 'Body Mass Index (BMI) verdeling. Normaal gewicht: 18.5-25. Overgewicht: 25-30. Obesitas: >30.',
        'split_gender': True,
        'eenheid':      'kg/m²',
        'referentie':   25.0,
        'referentie_label': 'Grens normaal/overgewicht (25)',
    },
    {
        'label':        'Roken',
        'kolom':        'rec_smoking_answer',
        'plot_type':    'bar',
        'groep':        'Demografisch',
        'omschrijving': 'Verdeling van rookgedrag. Groen = nooit gerookt, rood = dagelijks roken.',
        'split_gender': False,
        'labels': {
            0: 'Nooit gerookt',
            1: 'Gestopt >15 jaar',
            2: 'Gestopt >5 jaar',
            3: 'Gestopt 1-5 jaar',
            4: 'Recent gestopt',
            5: 'Af en toe',
            6: 'Dagelijks',
        },
        'kleur_richting': 'eerste_goed',
        'type': 'numeriek_bar',
    },

    # ── Slaap ─────────────────────────────────────────────────────────────────
    {
        'label':        'Slaapuren per nacht',
        'kolom':        'rec_ls_sleep_psqi_amount_of_hours_slept_text',
        'plot_type':    'bar',
        'groep':        'Slaap',
        'omschrijving': 'Aantal uren slaap per nacht. Optimaal: 7-9 uur.',
        'split_gender': False,
        'type':         'slaap_tekst',
    },
    {
        'label':        'Slaapkwaliteit (PSQI)',
        'kolom':        'rec_ls_sleep_psqi_sum',
        'plot_type':    'histogram',
        'groep':        'Slaap',
        'omschrijving': 'PSQI totaalscore: 0 = uitstekende slaap, 20 = zeer slechte slaap. Score boven 5 wijst op slechte slaapkwaliteit.',
        'split_gender': True,
        'eenheid':      'punten (lager = beter)',
        'referentie':   5.0,
        'referentie_label': 'Grens slechte slaap (>5)',
    },

    # ── Beweging ──────────────────────────────────────────────────────────────
    {
        'label':        'Beweging',
        'kolom':        'rec_ls_exercise_steps_cat',
        'plot_type':    'bar',
        'groep':        'Beweging',
        'omschrijving': 'Aantal stappen per dag in drie categorieën. Meer stappen is beter.',
        'split_gender': False,
        'labels': {
            0: 'Weinig (<5.000)',
            1: 'Matig (5.000-10.000)',
            2: 'Veel (>10.000)',
        },
        'kleur_richting': 'laatste_goed',
    },

    # ── Voeding ───────────────────────────────────────────────────────────────
    {
        'label':        'Fruit (stukjes per dag)',
        'kolom':        'rec_ls_nutrition_fruit_fruit_per_day',
        'plot_type':    'histogram',
        'groep':        'Voeding',
        'omschrijving': 'Gemiddeld aantal stukjes fruit per dag. Aanbevolen: minimaal 2 stuks per dag.',
        'split_gender': True,
        'eenheid':      'stukjes per dag',
        'referentie':   2.0,
        'referentie_label': 'Aanbevolen (2 stuks)',
        'min_score':    0,
        'max_score':    10,
        'labels': {0: 'Weinig (<1/dag)', 1: 'Matig (1-2/dag)', 2: 'Veel (>2/dag)'},
    },
    {
        'label':        'Groenten (gram per dag)',
        'kolom':        'rec_ls_vegetables_gram_per_day',
        'plot_type':    'histogram',
        'groep':        'Voeding',
        'omschrijving': 'Groenteconsumptie in gram per dag. Aanbevolen: minimaal 250 gram per dag.',
        'split_gender': True,
        'eenheid':      'gram per dag',
        'referentie':   250.0,
        'referentie_label': 'Aanbevolen (250g)',
        'labels': {0: 'Laag (<150g)', 1: 'Matig (150-250g)', 2: 'Veel (>250g)'},
    },
    {
        'label':        'Suiker (gram per dag)',
        'kolom':        'rec_ls_nutrition_sugar_per_day',
        'plot_type':    'histogram',
        'groep':        'Voeding',
        'omschrijving': 'Suikerconsumptie in gram per dag. Aanbevolen maximum: 50 gram per dag.',
        'split_gender': True,
        'eenheid':      'gram per dag',
        'referentie':   50.0,
        'referentie_label': 'Maximum (50g)',
        'outlier_max':  300,        'labels': {0: 'Laag (<25g)', 1: 'Matig (25-50g)', 2: 'Hoog (>50g)'},    },
    {
        'label':        'Verzadigd vet (gram per dag)',
        'kolom':        'rec_ls_nutrition_saturated_fat_per_day',
        'plot_type':    'histogram',
        'groep':        'Voeding',
        'omschrijving': 'Verzadigd vet in gram per dag. Aanbevolen maximum: 22 gram per dag.',
        'split_gender': True,
        'eenheid':      'gram per dag',
        'referentie':   22.0,
        'referentie_label': 'Maximum (22g)',
        'outlier_max':  150,
        'labels': {0: 'Laag (<22g)', 1: 'Matig (22-35g)', 2: 'Hoog (>35g)'},
    },
    {
        'label':        'Zout / natrium (mg per dag)',
        'kolom':        'rec_ls_nutrition_natrium_per_day',
        'plot_type':    'histogram',
        'groep':        'Voeding',
        'omschrijving': 'Natriumconsumptie in mg per dag. Aanbevolen maximum: 2400 mg per dag.',
        'split_gender': True,
        'eenheid':      'mg per dag',
        'referentie':   2400.0,
        'referentie_label': 'Maximum (2400mg)',
        'outlier_max':  8000,
        'labels': {0: 'Laag (<2400mg)', 1: 'Matig (2400-3500mg)', 2: 'Hoog (>3500mg)'},
    },
    {
        'label':        'Alcohol (glazen per week)',
        'kolom':        'rec_ls_alcohol_total_per_week',
        'plot_type':    'histogram',
        'groep':        'Voeding',
        'omschrijving': 'Alcoholconsumptie in glazen per week. Aanbevolen maximum: 14 glazen per week.',
        'split_gender': True,
        'eenheid':      'glazen per week',
        'referentie':   14.0,
        'labels': {0: 'Geen/Laag (<1)', 1: 'Matig (1-14)', 2: 'Hoog (>14)'},
        'referentie_label': 'Maximum (14 glazen)',
    },

    # ── Stress ────────────────────────────────────────────────────────────────
    {
        'label':        'Stressniveau totaal',
        'kolom':        'rec_ls_stress_sum',
        'plot_type':    'histogram',
        'groep':        'Stress',
        'omschrijving': 'Totale stressscore. Hoger = meer stress. Score boven 14 wijst op hoog stressniveau.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (0-28, hoger = meer stress)',
        'referentie':   14.0,
        'referentie_label': 'Grens hoog stress',
        'min_score':    None,
        'max_score':    None,
    },
    {
        'label':        'Stresscategorie',
        'kolom':        'rec_ls_stress_cat',
        'plot_type':    'bar',
        'groep':        'Stress',
        'omschrijving': 'Stresscategorie. Groen = weinig stress, rood = veel stress.',
        'split_gender': False,
        'labels': {0: 'Weinig stress (goed)', 1: 'Matig stress', 2: 'Veel stress (slecht)'},
        'kleur_richting': 'eerste_goed',
    },
    {
        'label':        'Piekeren',
        'kolom':        'rec_ls_stress_type_1_worry',
        'plot_type':    'bar',
        'groep':        'Stress',
        'omschrijving': 'Mate van piekeren. 0 = nooit (goed), 1 = soms, 2 = vaak (slecht).',
        'split_gender': False,
        'labels': {0: 'Nooit (goed)', 1: 'Soms', 2: 'Vaak (slecht)'},
        'kleur_richting': 'eerste_goed',
    },
    {
        'label':        'Gespannenheid',
        'kolom':        'rec_ls_stress_type_2_tense',
        'plot_type':    'bar',
        'groep':        'Stress',
        'omschrijving': 'Mate van gespannenheid. 0 = nooit (goed), 1 = soms, 2 = vaak (slecht).',
        'split_gender': False,
        'labels': {0: 'Nooit (goed)', 1: 'Soms', 2: 'Vaak (slecht)'},
        'kleur_richting': 'eerste_goed',
    },

    # ── Psychologisch ─────────────────────────────────────────────────────────
    # DASS-21 officiele grenzen (na omrekening naar onze schaal):
    # Stress:    normaal 0-14, matig 15-18, ernstig 19-25, zeer ernstig >25 (max 42)
    # Angst:     normaal 0-7,  matig 8-9,   ernstig 10-14, zeer ernstig >14 (max 42)
    # Depressie: normaal 0-9,  matig 10-13, ernstig 14-20, zeer ernstig >20 (max 42)
    # Onze data heeft andere maxima, we normaliseren naar 0-10
    {
        'label':        'DASS stress',
        'kolom':        'rec_dass_stress_score',
        'plot_type':    'histogram',
        'groep':        'Stress',
        'omschrijving': 'DASS stressscore op originele schaal. Hoger = meer stress. Score boven 14 wijst op hoog stressniveau.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (0-40, hoger = meer stress)',
        'referentie':   14.0,
        'referentie_label': 'Grens hoog stress',
        'min_score':    0,
        'max_score':    40,
    },
    {
        'label':        'DASS angst',
        'kolom':        'rec_dass_anxiety_score',
        'plot_type':    'histogram',
        'groep':        'Psychologisch',
        'omschrijving': 'DASS angst score op originele schaal. Hoger = meer angst. Score boven 7 wijst op mogelijk klinische angst.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (0-36, hoger = meer angst)',
        'referentie':   7.0,
        'referentie_label': 'Grens mogelijk klinische angst',
        'min_score':    0,
        'max_score':    36,
    },
    {
        'label':        'DASS depressie',
        'kolom':        'rec_dass_depression_score',
        'plot_type':    'histogram',
        'groep':        'Psychologisch',
        'omschrijving': 'DASS depressie score op originele schaal. Hoger = meer depressieve symptomen. Score boven 9 wijst op mogelijk klinische depressie.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (0-42, hoger = meer depressie)',
        'referentie':   9.0,
        'referentie_label': 'Grens mogelijk klinische depressie',
        'min_score':    0,
        'max_score':    42,
    },
    {
        'label':        'Veerkracht',
        'kolom':        'rec_resilience_score',
        'plot_type':    'histogram',
        'groep':        'Psychologisch',
        'omschrijving': 'Veerkrachtscore op originele schaal. Hoger = meer veerkracht.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (0-40, hoger = meer veerkracht)',
        'min_score':    0,
        'max_score':    40,
    },
    {
        'label':        'Welzijn',
        'kolom':        'rec_wellbeing_score',
        'plot_type':    'histogram',
        'groep':        'Psychologisch',
        'omschrijving': 'Welzijnsscore op originele schaal (WHO-5). Hoger = beter welzijn.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (0-100, hoger = beter welzijn)',
        'min_score':    0,
        'max_score':    100,
    },
    {
        'label':        'Zelfeffectiviteit',
        'kolom':        'rec_self_efficacy_score',
        'plot_type':    'histogram',
        'groep':        'Psychologisch',
        'omschrijving': 'Zelfeffectiviteitsscore op originele schaal (Bandura). Hoger = meer zelfvertrouwen.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (10-40, hoger = meer zelfvertrouwen)',
        'min_score':    10,
        'max_score':    40,
    },

    # ── Werkvermogen ──────────────────────────────────────────────────────────
    {
        'label':        'Werkvermogen index',
        'kolom':        'rec_asr_wai_score',
        'plot_type':    'histogram',
        'groep':        'Werkvermogen',
        'omschrijving': 'Work Ability Index op originele schaal. Hoger = beter werkvermogen.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (19-44, hoger = beter werkvermogen)',
        'min_score':    19,
        'max_score':    44,
    },
    {
        'label':        'Burn-out risico (0-10)',
        'kolom':        'rec_asr_burn_out_score',
        'plot_type':    'histogram',
        'groep':        'Werkvermogen',
        'omschrijving': 'Burn-out risico score. Hoger = groter risico op burn-out.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (hoger = meer burn-out risico)',
    },
    {
        'label':        'Vitaliteit (0-10)',
        'kolom':        'rec_asr_vitality_score',
        'plot_type':    'histogram',
        'groep':        'Werkvermogen',
        'omschrijving': 'Vitaliteitsscore op het werk. Hoger = vitaler.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (hoger = vitaler)',
    },
    {
        'label':        'Werktevredenheid (0-10)',
        'kolom':        'rec_asr_job_satisfaction_score',
        'plot_type':    'histogram',
        'groep':        'Werkvermogen',
        'omschrijving': 'Tevredenheid met het werk. Hoger = meer tevreden.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (hoger = meer tevreden)',
    },
    {
        'label':        'Werkdruk',
        'kolom':        'rec_asr_workload_score',
        'plot_type':    'box',
        'groep':        'Werkvermogen',
        'omschrijving': 'Werkdruk score. Hoger = hogere werkdruk. Boxplot toont spreiding per geslacht.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (hoger = hogere werkdruk)',
    },
    {
        'label':        'Uitputting',
        'kolom':        'rec_asr_exhaustion_score',
        'plot_type':    'box',
        'groep':        'Werkvermogen',
        'omschrijving': 'Uitputtingsscore. Hoger = meer uitputting.',
        'split_gender': True,
        'schaal_factor': None,
        'eenheid':      'score (hoger = meer uitputting)',
    },

    # ── Cardiovasculair ───────────────────────────────────────────────────────
    {
        'label':        'Framingham score',
        'kolom':        'rec_framingham_non_invasive',
        'plot_type':    'histogram',
        'groep':        'Cardiovasculair',
        'omschrijving': 'Geschatte 10-jaars kans op hart en vaatziekten via de non-invasieve Framingham score.',
        'split_gender': True,
        'eenheid':      'score',
    },
    {
        'label':        'Bloeddruk (categorie)',
        'kolom':        'rec_med_blood_pressure_cat',
        'plot_type':    'bar',
        'groep':        'Cardiovasculair',
        'omschrijving': 'Bloeddruk ingedeeld in categorieën. Groen = normaal, rood = hoog.',
        'split_gender': False,
        'labels': {0: 'Normaal (goed)', 1: 'Verhoogd', 2: 'Hoog (slecht)'},
        'kleur_richting': 'eerste_goed',
    },
]

# Handige lookups
VARIABELEN_PER_GROEP = {}
for v in VARIABELEN:
    VARIABELEN_PER_GROEP.setdefault(v['groep'], []).append(v)

VARIABELEN_DICT = {v['label']: v for v in VARIABELEN}

# Slaap tekst mapping (meertalig -> Nederlands)
SLAAP_TEKST_MAP = {
    'Minder dan 6 uur of meer dan 10 uur':              'Minder dan 6 uur',
    'Less than 6 hours or more than 10 hours':          'Minder dan 6 uur',
    'Menos de 6 horas o más de 10 horas':               'Minder dan 6 uur',
    'Weniger als 6 Stunden oder mehr als 10 Stunden':   'Minder dan 6 uur',
    '6-7 uur':              '6-7 uur',
    '6-7 hours':            '6-7 uur',
    '6-7 Stunden':          '6-7 uur',
    'De 6 a 7 horas':       '6-7 uur',
    'Entre 6 et 7 heures':  '6-7 uur',
    '7-9 uur':              '7-9 uur',
    '7-9 hours':            '7-9 uur',
    'De 7 a 9 horas':       '7-9 uur',
    'Entre 7 et 9 heures':  '7-9 uur',
    '9-10 uur':             '9-10 uur',
    '9-10 hours':           '9-10 uur',
    'Entre 9 et 10 heures': '9-10 uur',
}
SLAAP_VOLGORDE = ['Minder dan 6 uur', '6-7 uur', '7-9 uur', '9-10 uur']
SLAAP_KLEUREN  = {
    'Minder dan 6 uur': '#E74C3C',
    '6-7 uur':          '#E87722',
    '7-9 uur':          '#2ECC71',
    '9-10 uur':         '#E87722',
}

SLAAP_LABELS = { # PSQI score categories
    0: 'Goed', # PSQI 0-5
    1: 'Matig', # PSQI 6-10
    2: 'Slecht', # PSQI >10
}

SLAAP_LABELS = { # PSQI score categories
    0: 'Goed', # PSQI 0-5
    1: 'Matig', # PSQI 6-10
    2: 'Slecht', # PSQI >10
}
