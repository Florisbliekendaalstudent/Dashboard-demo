from pathlib import Path
import pandas as pd
import numpy as np
from matplotlib import pyplot as plt
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
import logging
from helpers import get_numeric_clean, filter_by_gender

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from scipy import stats
from config import DB_URL
from data_ingestion import (
    generate_consolidated_scores_in_db,
    load_table_from_database,
    load_factor_score_histories,
    load_completions,
    load_users_met_scores,
    load_participants,
    load_my_clic_participants,
    load_my_clic_participants_expanded,
    load_store_employees,
    load_stores,
    load_orders,
    get_user_purchases,
    add_app_user_ids_and_addresses,
)
from helpers import _maak_net_label
logger = logging.getLogger(__name__)

# Import variabelen EENMALIG hier, niet in functies!
try:
    import statsmodels.api as sm
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False
    logger.warning("Statsmodels niet geïnstalleerd. Trendlijnen in scatterplots zijn uitgeschakeld.")

try:
    import variabelen as _variabelen
    SLAAP_TEKST_MAP = getattr(_variabelen, 'SLAAP_TEKST_MAP', {})
    SLAAP_VOLGORDE = getattr(_variabelen, 'SLAAP_VOLGORDE', [])
    SLAAP_KLEUREN = getattr(_variabelen, 'SLAAP_KLEUREN', {})
    VARIABELEN_DICT = getattr(_variabelen, 'VARIABELEN_DICT', {})
    VARIABELEN_PER_GROEP = getattr(_variabelen, 'VARIABELEN_PER_GROEP', {})
    # Deze variabelen zijn gedefinieerd in analyses.py, niet in variabelen.py
    from analyses import LEEFSTIJL_SCORES, RUWE_WAARDEN
    logger.info("✓ Variabelen module imported")
except ImportError as e:
    SLAAP_TEKST_MAP = {}
    SLAAP_VOLGORDE = []
    SLAAP_KLEUREN = {}
    VARIABELEN_DICT = {}
    VARIABELEN_PER_GROEP = {}
    LEEFSTIJL_SCORES = {}
    RUWE_WAARDEN = {}
    logger.error(f"Error importing variabelen: {e}")

# Globale fontgrootte voor alle Plotly grafieken
pio.templates["smarthealth"] = go.layout.Template(
    layout=go.Layout(
        font=dict(size=14),
        title=dict(font=dict(size=16)),
        xaxis=dict(title=dict(font=dict(size=13)), tickfont=dict(size=12)),
        yaxis=dict(title=dict(font=dict(size=13)), tickfont=dict(size=12)),
        legend=dict(font=dict(size=13)),
    )
)
pio.templates.default = "plotly+smarthealth"

from sqlalchemy import create_engine
from kleuren import (
    HOOFD_KLEUR, GENDER_COLORS, GENDER_LABELS,
    RISICO_COLORS, HEARTRISK_LABELS, STRESS_LABELS,
    BMI_LABELS, BMI_COLORS,
)
from i18n import tr


# Drempels die voor de snapshotweergave beschikbaar zijn. De leefstijlscore
# heeft in de huidige bron geen vastgelegde categoriegrenzen; die drie grenzen
# zijn daarom een expliciete, te valideren aanname.
SCORE_CATEGORIEEN = {
    'rec_ls_lifestyle_score': {
        'bins': [-np.inf, 3.5, 7.5, np.inf],
        'labels': ['Slecht', 'Matig', 'Goed'],
        'kleuren': {'Slecht': '#E74C3C', 'Matig': '#E87722', 'Goed': '#2ECC71'},
        'toelichting': 'Aanname: leefstijlscore 1-3 = slecht, 4-7 = matig, 8-10 = goed.',
    },
    'rec_med_bmi': {
        'bins': [-np.inf, 18.5, 25.0, np.inf],
        'labels': ['Matig', 'Goed', 'Slecht'],
        'kleuren': {'Slecht': '#E74C3C', 'Matig': '#E87722', 'Goed': '#2ECC71'},
        'toelichting': 'Gebaseerd op de bestaande BMI-grenzen 18,5 en 25.',
    },
    'rec_ls_stress_sum': {
        'bins': [-np.inf, 5.0, 14.0, np.inf],
        'labels': ['Goed', 'Matig', 'Slecht'],
        'kleuren': {'Slecht': '#E74C3C', 'Matig': '#E87722', 'Goed': '#2ECC71'},
        'toelichting': 'Gebaseerd op de bestaande stressgrenzen 5 en 14.',
    },
    'rec_ls_sleep_psqi_sum': {
        'bins': [-np.inf, 5.0, 10.0, np.inf],
        'labels': ['Goed', 'Matig', 'Slecht'],
        'kleuren': {'Slecht': '#E74C3C', 'Matig': '#E87722', 'Goed': '#2ECC71'},
        'toelichting': 'Gebaseerd op de bestaande PSQI-grenzen 5 en 10.',
    },
    'rec_dass_stress_score': {
        'bins': [-np.inf, 14.0, 18.0, np.inf],
        'labels': ['Goed', 'Matig', 'Slecht'],
        'kleuren': {'Slecht': '#E74C3C', 'Matig': '#E87722', 'Goed': '#2ECC71'},
        'toelichting': 'Gebaseerd op de bestaande DASS-stressgrenzen 14 en 18.',
    },
    'rec_dass_anxiety_score': {
        'bins': [-np.inf, 7.0, 9.0, np.inf],
        'labels': ['Goed', 'Matig', 'Slecht'],
        'kleuren': {'Slecht': '#E74C3C', 'Matig': '#E87722', 'Goed': '#2ECC71'},
        'toelichting': 'Gebaseerd op de bestaande DASS-angstgrenzen 7 en 9.',
    },
    'rec_dass_depression_score': {
        'bins': [-np.inf, 9.0, 13.0, np.inf],
        'labels': ['Goed', 'Matig', 'Slecht'],
        'kleuren': {'Slecht': '#E74C3C', 'Matig': '#E87722', 'Goed': '#2ECC71'},
        'toelichting': 'Gebaseerd op de bestaande DASS-depressiegrenzen 9 en 13.',
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _laad_users_tabel(base_pad: Path) -> pd.DataFrame:
    """Laad users tabel uit database."""
    return load_table_from_database('participants', DB_URL) # Deze functie is al correct


def _laad_actieve_users(base_pad: Path, include_deleted: bool = False) -> pd.DataFrame:
    """Laad users en voeg jaar toe. Optioneel inclusief verwijderde accounts."""
    df_users = _laad_users_tabel(base_pad) # Roep de database-ladende functie aan
    if not include_deleted and 'deleted_at' in df_users.columns:
        df_users = df_users[df_users['deleted_at'].isna()].copy()

    if 'created_at' in df_users.columns:
        df_users['jaar'] = pd.to_datetime(df_users['created_at'], errors='coerce').dt.year
    else:
        df_users['jaar'] = pd.NA
    return df_users


def _numeriek(df, kolom):
    """Zet een kolom om naar int, dropt NaN rijen."""
    s = pd.to_numeric(df[kolom], errors='coerce')
    return s.dropna().astype(int)


def _has_valid_db_url(db_url: str | None) -> bool:
    return isinstance(db_url, str) and "://" in db_url


def _laad_actieve_stores(base_pad: Path, include_deleted: bool = True) -> pd.DataFrame:
    stores_df = load_stores(DB_URL).copy()
    if stores_df.empty:
        return pd.DataFrame(columns=['id', 'name'])
    if 'id' not in stores_df.columns:
        stores_df['id'] = pd.NA
    if 'name' not in stores_df.columns:
        stores_df['name'] = 'Onbekend'
    stores_df['id'] = pd.to_numeric(stores_df['id'], errors='coerce')
    if not include_deleted and 'deleted_at' in stores_df.columns:
        stores_df['deleted_at'] = stores_df['deleted_at'].replace({'NULL': pd.NA, 'None': pd.NA, '': pd.NA})
        stores_df = stores_df[stores_df['deleted_at'].isna()].copy()
    if not include_deleted and 'is_active' in stores_df.columns:
        actieve_mask = ~stores_df['is_active'].astype(str).str.strip().str.lower().isin({'0', 'false', 'nan', 'none'})
        stores_df = stores_df[actieve_mask].copy()
    return stores_df.dropna(subset=['id']).drop_duplicates(subset='id')


def _laad_actieve_store_links(base_pad: Path) -> pd.DataFrame:
    opdrachtgever_links = _laad_opdrachtgever_links(DB_URL)
    if not opdrachtgever_links.empty:
        return (
            opdrachtgever_links[['user_id', 'store_id']]
            .dropna(subset=['user_id', 'store_id'])
            .sort_values(['user_id', 'store_id'])
            .drop_duplicates(subset=['user_id'], keep='first')
        )

    df_store = load_store_employees(DB_URL).copy()
    if df_store.empty or not {'user_id', 'store_id'}.issubset(df_store.columns):
        return pd.DataFrame(columns=['user_id', 'store_id'])

    df_store['user_id'] = pd.to_numeric(df_store['user_id'], errors='coerce')
    df_store['store_id'] = pd.to_numeric(df_store['store_id'], errors='coerce')
    if 'deleted_at' in df_store.columns:
        df_store['deleted_at'] = df_store['deleted_at'].replace({'NULL': pd.NA, 'None': pd.NA, '': pd.NA})
        df_store = df_store[df_store['deleted_at'].isna()].copy()
    if 'archived_at' in df_store.columns:
        df_store['archived_at'] = df_store['archived_at'].replace({'NULL': pd.NA, 'None': pd.NA, '': pd.NA})
        df_store = df_store[df_store['archived_at'].isna()].copy()

    geldige_store_ids = set(_laad_actieve_stores(base_pad, include_deleted=True)['id'].dropna().astype(int))
    if geldige_store_ids:
        df_store = df_store[df_store['store_id'].isin(geldige_store_ids)].copy()

    return (
        df_store[['user_id', 'store_id']]
        .dropna(subset=['user_id', 'store_id'])
        .drop_duplicates(subset=['user_id'], keep='first')
    )

def _laad_opdrachtgever_links(db_url: str | None = None) -> pd.DataFrame:
    """
    Koppel QE participants aan echte opdrachtgevers.

    De betrouwbare route in deze database is:
    public.participants.public_id -> smart_health.my_clic_participants.qe_participant_id
    -> smart_health.store_employees.user_id -> public.stores.id/name.
    """
    db_url = db_url or DB_URL
    if not _has_valid_db_url(db_url):
        return pd.DataFrame(columns=['participant_id', 'user_id', 'store_id', 'store_name'])

    is_sqlite = 'sqlite' in str(db_url)
    concat_clause = "('Store ' || s.id)" if is_sqlite else "CONCAT('Store ', s.id)"
    
    query = text(f"""
        SELECT DISTINCT
            p.id AS participant_id,
            m.user_id AS user_id,
            s.id AS store_id,
            COALESCE(NULLIF(s.name, ''), {concat_clause}) AS store_name
        FROM participants p
        JOIN my_clic_participants m
          ON m.qe_participant_id = p.public_id
        JOIN store_employees se
          ON se.user_id = m.user_id
        JOIN stores s
          ON s.id = se.store_id
        WHERE se.deleted_at IS NULL
          AND s.id IS NOT NULL
    """)
    try:
        engine = create_engine(db_url)
        df_links = pd.read_sql(query, engine)
    except Exception as e:
        logger.warning(f"Kon opdrachtgeverkoppeling niet laden: {e}")
        return pd.DataFrame(columns=['participant_id', 'user_id', 'store_id', 'store_name'])

    for col in ['participant_id', 'user_id', 'store_id']:
        if col in df_links.columns:
            df_links[col] = pd.to_numeric(df_links[col], errors='coerce')

    df_links = (
        df_links
        .dropna(subset=['participant_id', 'store_id'])
        .drop_duplicates(subset=['participant_id', 'store_id'])
        .sort_values(['participant_id', 'store_id'])
    )

    dubbele_participants = df_links.duplicated(subset=['participant_id'], keep=False).sum()
    if dubbele_participants:
        logger.warning(
            "Meerdere opdrachtgeverkoppelingen gevonden voor %s participant-rijen; "
            "eerste store_id per participant wordt gebruikt.",
            dubbele_participants,
        )

    return df_links.drop_duplicates(subset=['participant_id'], keep='first')


def _dashboard_score_to_history_slug(score_slug: str) -> str:
    """Vertaal dashboardkolommen naar factorhistorie-slugs voor opdrachtgevertrends."""
    return {
        'rec_med_bmi': 'bmi',
        'rec_heartrisk': 'heartrisk',
        'rec_framingham_non_invasive': 'heartrisk',
        'rec_ls_stress_sum': 'stress',
        'rec_ls_sleep_psqi_sum': 'sleep',
        'rec_ls_alcohol_total_per_week': 'alcohol',
        'rec_ls_score_alcohol': 'alcohol',
        'rec_ls_score_exercise': 'exercise',
        'rec_ls_exercise_physical_activity_minutes_total': 'exercise',
        'rec_ls_exercise_steps_per_day': 'steps',
        'rec_ls_nutrition_fruit_fruit_per_day': 'fruit',
        'rec_ls_score_fruit': 'fruit',
        'rec_ls_vegetables_gram_per_day': 'vegetables',
        'rec_ls_score_vegetables': 'vegetables',
        'rec_ls_nutrition_sugar_per_day': 'sugar',
        'rec_ls_score_sugar': 'sugar',
        'rec_ls_nutrition_saturated_fat_per_day': 'fat',
        'rec_ls_score_saturated_fat': 'fat',
        'rec_ls_nutrition_natrium_per_day': 'salt',
        'rec_ls_score_natrium': 'salt',
        'rec_smoking_answer': 'smoking',
        # De huidige scorehistorie bevat geen aparte 'lifestyle'-slug.
        # Gebruik de beschikbare 'wellbeing'-historie als bruikbare fallback
        # voor de trendweergave van de dashboard-leefstijlscore.
        'rec_ls_lifestyle_score': 'wellbeing',
        'rec_resilience_score': 'resilience',
        'rec_wellbeing_score': 'wellbeing',
        'rec_self_efficacy_score': 'selfefficacy',
        'rec_dass_stress_score': 'dass_stress',
        'rec_dass_anxiety_score': 'dass_anxiety',
        'rec_dass_depression_score': 'dass_depression',
        'rec_asr_job_satisfaction_score': 'job_satisfaction',
        'rec_asr_working_attitude_score': 'working_attitude',
        'rec_asr_workload_score': 'workload',
        'rec_asr_work_ability_score': 'work_life_balance',
        'rec_asr_wai_score': 'work_life_balance',
        'rec_asr_burn_out_score': 'health',
        'rec_asr_personal_competences_score': 'competences',
        'rec_asr_minor_mental_complaints_score': 'mental_complaints',
    }.get(score_slug, score_slug)



def _tel_percentages(series, labels: dict) -> pd.DataFrame:
    counts = series.value_counts(normalize=True).mul(100).reset_index()
    counts.columns = ['code', 'percentage']
    counts['label'] = counts['code'].map(labels)
    counts = counts.dropna(subset=['label'])
    return counts


def laad_data(base_pad: Path, db_url: str | None = None) -> pd.DataFrame:
    """
    Centrale functie voor het inladen van de geconsolideerde gebruikersdata.
    Probeert eerst de database (users_met_scores), daarna lokale fallback.
    """
    if not isinstance(db_url, str):
        from config import DB_URL
        db_url = DB_URL

    if not db_url:
        logger.warning("Geen database URL geconfigureerd, probeer lokale fallback.")
        try:
            return load_users_met_scores(DB_URL)
        except Exception:
            return pd.DataFrame()

    try:
        engine = create_engine(db_url)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        
        # Controleer of de tabel bestaat, anders proberen op te bouwen
        if 'users_met_scores' not in table_names:
            logger.warning("De tabel 'users_met_scores' ontbreekt. Poging tot genereren...")
            ok, _ = generate_consolidated_scores_in_db(engine)
            if not ok:
                return load_users_met_scores(db_url)

        df = pd.read_sql("SELECT * FROM users_met_scores", engine)
        df = df.drop_duplicates(subset='user_id', keep='first').reset_index(drop=True)
        
        # Garandeer numerieke user_id
        df['user_id'] = pd.to_numeric(df['user_id'], errors='coerce')
        return df
    except Exception as e:
        logger.warning(f"Database-ingestie mislukt ({e}), probeer lokale fallback.")
        try:
            return load_users_met_scores(db_url or DB_URL)
        except Exception:
            return pd.DataFrame()


# ── Demografisch ──────────────────────────────────────────────────────────────
def maak_geslacht_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    s = _numeriek(df, 'rec_user_gender')
    gender_labels = {k: tr(v, lang) for k, v in GENDER_LABELS.items()}
    counts = _tel_percentages(s, gender_labels)
    kleur_map = {v: GENDER_COLORS[k] for k, v in gender_labels.items()}
    fig = px.bar(
        counts, x='label', y='percentage',
        color='label',
        color_discrete_map=kleur_map,
        labels={'label': '', 'percentage': tr('Percentage (%)', lang)},
        title=tr('Verdeling geslacht', lang),
        category_orders={'label': [tr('Man', lang), tr('Vrouw', lang)]},
    )
    fig.update_layout(showlegend=False)
    return fig


def maak_leeftijd_plot(df: pd.DataFrame, geslacht: str = 'beide', lang: str = 'nl') -> go.Figure:
    df2 = df.copy()
    df2['rec_age_current'] = pd.to_numeric(df2['rec_age_current'], errors='coerce')
    df2 = df2.dropna(subset=['rec_age_current'])

    if geslacht == 'beide':
        gender_labels = {k: tr(v, lang) for k, v in GENDER_LABELS.items()}
        df2['geslacht_label'] = pd.to_numeric(df2['rec_user_gender'], errors='coerce').map(gender_labels)
        df2 = df2.dropna(subset=['geslacht_label'])
        kleur_map = {gender_labels[1]: GENDER_COLORS['Man'], gender_labels[0]: GENDER_COLORS['Vrouw']}
        fig = px.histogram(
            df2, x='rec_age_current',
            color='geslacht_label',
            color_discrete_map=kleur_map,
            barmode='overlay',
            opacity=0.75,
            labels={'rec_age_current': tr('Leeftijd', lang), 'count': tr('Aantal', lang), 'geslacht_label': tr('Geslacht', lang)},
            title=tr('Leeftijdsverdeling naar geslacht', lang),
            category_orders={'geslacht_label': [tr('Man', lang), tr('Vrouw', lang)]},
        )
        fig.update_layout(legend_title_text=tr('Geslacht', lang))
    else:
        fig = px.histogram(
            df2, x='rec_age_current',
            nbins=30,
            color_discrete_sequence=[HOOFD_KLEUR],
            labels={'rec_age_current': tr('Leeftijd', lang), 'count': tr('Aantal', lang)},
            title=tr('Leeftijdsverdeling', lang),
        )

    return fig


# ── Cardiovasculair risico ─────────────────────────────────────────────────────
def maak_heartrisk_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    s = _numeriek(df, 'rec_heartrisk_cat')
    labels = {k: tr(v, lang) for k, v in HEARTRISK_LABELS.items()}
    counts = _tel_percentages(s, labels)
    kleur_map = {v: RISICO_COLORS[k] for k, v in labels.items()}
    fig = px.bar(
        counts, x='label', y='percentage',
        color='label',
        color_discrete_map=kleur_map,
        labels={'label': '', 'percentage': tr('Percentage (%)', lang)},
        title=tr('Cardiovasculair risico', lang),
        category_orders={'label': [tr('Laag', lang), tr('Matig', lang), tr('Hoog', lang)]},
    )
    fig.update_layout(showlegend=False)
    return fig


def maak_heartrisk_naar_geslacht_plot(df: pd.DataFrame, lang: str = 'nl', geslacht: str = 'beide') -> go.Figure:
    df2 = df.copy()
    df2['heartrisk_code'] = pd.to_numeric(df2['rec_heartrisk_cat'], errors='coerce')
    risk_labels = {k: tr(v, lang) for k, v in HEARTRISK_LABELS.items()}
    df2['risico_label'] = df2['heartrisk_code'].map(risk_labels)
    df2 = df2.dropna(subset=['risico_label'])

    if geslacht == 'beide':
        gender_labels = {k: tr(v, lang) for k, v in GENDER_LABELS.items()}
        df2['geslacht_label'] = pd.to_numeric(df2['rec_user_gender'], errors='coerce').map(gender_labels)
        df2 = df2.dropna(subset=['geslacht_label'])
        counts = df2.groupby(['geslacht_label', 'risico_label']).size().reset_index(name='aantal')
        totaal = counts.groupby('geslacht_label')['aantal'].transform('sum')
        counts['percentage'] = counts['aantal'] / totaal * 100

        kleur_map = {gender_labels[1]: GENDER_COLORS['Man'], gender_labels[0]: GENDER_COLORS['Vrouw']}
        fig = px.bar(
            counts, x='risico_label', y='percentage',
            color='geslacht_label',
            barmode='group',
            color_discrete_map=kleur_map,
            labels={'risico_label': tr('Risicocategorie', lang), 'percentage': tr('Percentage (%)', lang), 'geslacht_label': tr('Geslacht', lang)},
            title=tr('Cardiovasculair risico naar geslacht', lang),
            category_orders={
                'risico_label':   [tr('Laag', lang), tr('Matig', lang), tr('Hoog', lang)],
                'geslacht_label': [tr('Man', lang), tr('Vrouw', lang)],
            },
        )
    else:
        counts = df2['risico_label'].value_counts(normalize=True).mul(100).reset_index()
        counts.columns = ['risico_label', 'percentage']
        kleur_map = {tr(v, lang): RISICO_COLORS[k] for k, v in HEARTRISK_LABELS.items()}
        fig = px.bar(
            counts, x='risico_label', y='percentage',
            color='risico_label',
            color_discrete_map=kleur_map,
            labels={'risico_label': tr('Risicocategorie', lang), 'percentage': tr('Percentage (%)', lang)},
            title=tr('Cardiovasculair risico', lang),
            category_orders={'risico_label': [tr('Laag', lang), tr('Matig', lang), tr('Hoog', lang)]},
        )
        fig.update_layout(showlegend=False)

    return fig


# ── BMI ────────────────────────────────────────────────────────────────────────
def maak_bmi_plot(df: pd.DataFrame, lang: str = 'nl', geslacht: str = 'totaal') -> go.Figure:
    bmi_labels = {k: tr(v, lang) for k, v in BMI_LABELS.items()}
    volgorde = [bmi_labels[k] for k in sorted(bmi_labels)]

    # Bij de vergelijking: man en vrouw naast elkaar tonen (gegroepeerde bar chart).
    if geslacht == 'beide':
        df2 = df.copy()
        df2['bmi_code'] = _numeriek(df, 'rec_med_bmi_cat')
        df2['geslacht_code'] = pd.to_numeric(df2['rec_user_gender'], errors='coerce')
        df2 = df2.dropna(subset=['bmi_code', 'geslacht_code'])
        df2['bmi_label'] = df2['bmi_code'].map(bmi_labels)
        gender_labels = {k: tr(v, lang) for k, v in GENDER_LABELS.items()}
        df2['geslacht_label'] = df2['geslacht_code'].map(gender_labels)
        df2 = df2.dropna(subset=['bmi_label', 'geslacht_label'])

        counts = df2.groupby(['geslacht_label', 'bmi_label']).size().reset_index(name='aantal')
        totaal = counts.groupby('geslacht_label')['aantal'].transform('sum')
        counts['percentage'] = counts['aantal'] / totaal * 100

        kleur_map = {gender_labels[1]: GENDER_COLORS['Man'], gender_labels[0]: GENDER_COLORS['Vrouw']}
        fig = px.bar(
            counts, x='bmi_label', y='percentage',
            color='geslacht_label',
            barmode='group',
            color_discrete_map=kleur_map,
            labels={'bmi_label': '', 'percentage': tr('Percentage (%)', lang), 'geslacht_label': tr('Geslacht', lang)},
            title=tr('BMI categorie verdeling', lang),
            category_orders={
                'bmi_label': volgorde,
                'geslacht_label': [tr('Man', lang), tr('Vrouw', lang)],
            },
        )
        return fig

    # Anders: huidige weergave (enkele groep)
    s = _numeriek(df, 'rec_med_bmi_cat')
    counts = _tel_percentages(s, bmi_labels)
    kleur_map = {v: BMI_COLORS[k] for k, v in bmi_labels.items()}
    fig = px.bar(
        counts, x='label', y='percentage',
        color='label',
        color_discrete_map=kleur_map,
        labels={'label': '', 'percentage': tr('Percentage (%)', lang)},
        title=tr('BMI categorie verdeling', lang),
        category_orders={'label': volgorde},
    )
    fig.update_layout(showlegend=False)
    return fig


# ── Stress ─────────────────────────────────────────────────────────────────────
def maak_stress_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    s = _numeriek(df, 'rec_ls_stress_cat')
    labels = {k: tr(v, lang) for k, v in STRESS_LABELS.items()}
    counts = _tel_percentages(s, labels)
    kleur_map = {v: RISICO_COLORS[k] for k, v in labels.items()}
    fig = px.bar(
        counts, x='label', y='percentage',
        color='label',
        color_discrete_map=kleur_map,
        labels={'label': '', 'percentage': tr('Percentage (%)', lang)},
        title=tr('Stresscategorie verdeling', lang),
        category_orders={'label': [tr('Laag', lang), tr('Matig', lang), tr('Hoog', lang)]},
    )
    fig.update_layout(showlegend=False)
    return fig


# ── Leefstijlscore ─────────────────────────────────────────────────────────────
def maak_leefstijl_score_plot(df: pd.DataFrame, geslacht: str = 'beide', lang: str = 'nl') -> go.Figure:
    """Genereert de leefstijlscore als groen/oranje/rode categorieën."""
    df2 = df.copy()
    df2['rec_ls_lifestyle_score'] = pd.to_numeric(df2['rec_ls_lifestyle_score'], errors='coerce')
    df2 = df2.dropna(subset=['rec_ls_lifestyle_score'])

    config = SCORE_CATEGORIEEN['rec_ls_lifestyle_score']
    labels = [tr(label, lang) for label in config['labels']]
    kleuren = {tr(label, lang): kleur for label, kleur in config['kleuren'].items()}
    df2['leefstijl_cat'] = pd.cut(
        df2['rec_ls_lifestyle_score'],
        bins=config['bins'],
        labels=labels,
        include_lowest=True,
    )

    if geslacht == 'beide':
        gender_labels = {k: tr(v, lang) for k, v in GENDER_LABELS.items()}
        df2['geslacht_label'] = pd.to_numeric(df2['rec_user_gender'], errors='coerce').map(gender_labels)
        df2 = df2.dropna(subset=['geslacht_label'])
        fig = px.histogram(
            df2,
            x='leefstijl_cat',
            color='leefstijl_cat',
            color_discrete_map=kleuren,
            facet_col='geslacht_label',
            labels={'leefstijl_cat': tr('Leefstijlscore categorie', lang), 'count': tr('Aantal', lang), 'geslacht_label': tr('Geslacht', lang)},
            title=tr('Verdeling leefstijlscore naar geslacht', lang),
            category_orders={'leefstijl_cat': labels, 'geslacht_label': [gender_labels[1], gender_labels[0]]},
        )
        fig.update_layout(legend_title_text=tr('Categorie', lang))
    else:
        fig = px.histogram(
            df2, x='leefstijl_cat',
            color='leefstijl_cat',
            color_discrete_map=kleuren,
            labels={'leefstijl_cat': tr('Leefstijlscore categorie', lang), 'count': tr('Aantal', lang)},
            title=tr('Verdeling leefstijlscore', lang),
        )

    fig.update_layout(bargap=0.1)
    return fig


# ── Longitudinale data ─────────────────────────────────────────────────────────
def laad_longitudinale_data(base_pad: Path, db_url: str) -> pd.DataFrame:
    df_history    = load_factor_score_histories(db_url or DB_URL)
    if df_history.empty:
        return pd.DataFrame(columns=[
            'id', 'participant_id', 'questionnaire_factor_id', 'completion_id',
            'score_value', 'score_category_value', 'completion_created_at',
            'created_at', 'updated_at', 'slug', 'user_gender', 'store_id', 'jaar'
        ])
    df_completions = load_completions(db_url or DB_URL)
    df_scores_latest = load_my_clic_participants_expanded(db_url or DB_URL)
    # Ensure participant_id column exists
    if 'participant_id' not in df_scores_latest.columns:
        df_scores_latest = df_scores_latest.rename(columns={'user_id': 'participant_id'})
    df_scores_latest = df_scores_latest.drop_duplicates(subset='participant_id', keep='first')
    df_scores_latest = df_scores_latest[df_scores_latest['participant_id'].notna()]
    df_store_employees = _laad_actieve_store_links(base_pad)  # Used for store_id linking
    # Gebruik participants als primaire bron en my_clic_participants als fallback/bridge.
    df_participants = load_participants(db_url or DB_URL)
    try:
        df_my_clic = load_my_clic_participants(db_url or DB_URL)
    except Exception:
        df_my_clic = pd.DataFrame()

    # Load questionnaire factors
    df_factors = None
    if _has_valid_db_url(db_url):
        try:
            engine = create_engine(db_url)
            df_factors = pd.read_sql("SELECT id, slug FROM questionnaire_factors", engine)
        except Exception:
            df_factors = None
    if df_factors is None or not _has_valid_db_url(db_url):
        # Harmonized factor mapping met deduplicatie
        # - Wellbeing vragen (23-27) → 1 "Wellbeing" factor
        # - Resilience vragen (28-29) → 1 "Resilience" factor
        # Fallback mapping voor lokale analyse zonder questionnaire_factors uit de DB.
        # Deze ids zijn afgeleid uit de bestaande scorehistorie en huidige kolomdistributies.
        df_factors = pd.DataFrame([
            {'id': 1, 'slug': 'bmi'}, {'id': 2, 'slug': 'alcohol'}, {'id': 3, 'slug': 'exercise'},
            {'id': 4, 'slug': 'fruit'}, {'id': 5, 'slug': 'vegetables'}, {'id': 6, 'slug': 'smoking'},
            {'id': 7, 'slug': 'stress'}, {'id': 8, 'slug': 'sugar'}, {'id': 9, 'slug': 'fat'},
            {'id': 10, 'slug': 'salt'}, {'id': 11, 'slug': 'blood_pressure'}, {'id': 12, 'slug': 'diabetes'},
            {'id': 13, 'slug': 'resilience'}, {'id': 14, 'slug': 'wellbeing'}, {'id': 15, 'slug': 'selfefficacy'},
            {'id': 16, 'slug': 'dass_stress'}, {'id': 17, 'slug': 'dass_anxiety'}, {'id': 18, 'slug': 'dass_depression'},
            {'id': 19, 'slug': 'bmi'}, {'id': 20, 'slug': 'age'}, {'id': 21, 'slug': 'alcohol'},
            {'id': 22, 'slug': 'smoking'}, {'id': 23, 'slug': 'wellbeing'}, {'id': 24, 'slug': 'wellbeing'},
            {'id': 25, 'slug': 'wellbeing'}, {'id': 26, 'slug': 'wellbeing'}, {'id': 27, 'slug': 'wellbeing'},
            {'id': 28, 'slug': 'resilience'}, {'id': 29, 'slug': 'resilience'}, {'id': 32, 'slug': 'digital_detox_stress'},
            {'id': 33, 'slug': 'selfefficacy'}, {'id': 34, 'slug': 'digital_detox_addiction_risk'},
            {'id': 35, 'slug': 'menopause_somatic'}, {'id': 36, 'slug': 'menopause_psychological'},
            {'id': 37, 'slug': 'menopause_genitourinary'},
        ])

    # Defensieve kolomverwerking voor score historie
    if 'completion_created_at' in df_history.columns:
        df_history['completion_created_at'] = pd.to_datetime(df_history['completion_created_at'], errors='coerce')
    if 'score_value' in df_history.columns:
        df_history['score_value'] = pd.to_numeric(df_history['score_value'], errors='coerce')
    if 'questionnaire_factor_id' in df_history.columns:
        df_history['questionnaire_factor_id'] = pd.to_numeric(df_history['questionnaire_factor_id'], errors='coerce')
    df_factors['id'] = pd.to_numeric(df_factors['id'], errors='coerce')

    # Koppel slug via factor id
    df = df_history.merge(df_factors[['id', 'slug']], left_on='questionnaire_factor_id', right_on='id', how='left')

    # Voeg BMI-waarden uit users_met_scores toe als aanvullende longitudinaledata.
    # Dit voegt BMI-uit andere metingen toe (inclusief berekening via gewicht/lengte) zodat
    # bmi-trends vollediger worden weergegeven.
    df_bmi_from_latest = pd.DataFrame()
    if {'participant_id', 'rec_med_bmi'}.issubset(df_scores_latest.columns):
        df_bmi_from_latest = df_scores_latest[['participant_id', 'rec_med_bmi']].copy()
        df_bmi_from_latest['participant_id'] = pd.to_numeric(df_bmi_from_latest['participant_id'], errors='coerce')
        df_bmi_from_latest['score_value'] = pd.to_numeric(df_bmi_from_latest['rec_med_bmi'], errors='coerce')
        df_bmi_from_latest = df_bmi_from_latest.dropna(subset=['participant_id', 'score_value']).drop_duplicates('participant_id')

        # Get latest completion date for each participant to use as 'completion_created_at' for these BMI records
        latest_completion_dates = df_completions.groupby('participant_id')['created_at'].max().reset_index()
        latest_completion_dates.rename(columns={'created_at': 'completion_created_at'}, inplace=True)

        df_bmi_from_latest = df_bmi_from_latest.merge(latest_completion_dates, on='participant_id', how='left')

        # Assign other required columns to match df_history structure
        df_bmi_from_latest['id'] = pd.NA # No specific ID for these synthetic history records
        df_bmi_from_latest['questionnaire_factor_id'] = pd.NA # No specific factor ID
        df_bmi_from_latest['completion_id'] = pd.NA # No specific completion ID
        df_bmi_from_latest['slug'] = 'bmi'
        df_bmi_from_latest['score_category_value'] = pd.NA
        df_bmi_from_latest['created_at'] = df_bmi_from_latest['completion_created_at']
        df_bmi_from_latest['updated_at'] = df_bmi_from_latest['completion_created_at']

        needed_cols = [
            'id', 'participant_id', 'questionnaire_factor_id', 'completion_id',
            'score_value', 'score_category_value', 'completion_created_at',
            'created_at', 'updated_at', 'slug'
        ]
        df_bmi_from_latest = df_bmi_from_latest[needed_cols] # Select and order columns

        df = pd.concat([df, df_bmi_from_latest], ignore_index=True, sort=False)

    # Koppel gender via de geconsolideerde latest scores.
    gender_per_participant = pd.DataFrame(columns=['participant_id', 'user_gender'])
    if {'participant_id', 'rec_user_gender'}.issubset(df_scores_latest.columns):
        gender_per_participant = (
            df_scores_latest[['participant_id', 'rec_user_gender']]
            .rename(columns={'rec_user_gender': 'user_gender'})
            .dropna(subset=['participant_id'])
            .drop_duplicates(subset='participant_id', keep='first')
        )
    gender_per_participant['user_gender'] = pd.to_numeric(gender_per_participant['user_gender'], errors='coerce')

    df = df.merge(gender_per_participant, on='participant_id', how='left')
    
    # Koppel store_id: participant_id -> user_id -> store_id (via store_employees)
    # Initialiseer store_id als NA om KeyErrors in latere functies te voorkomen.
    if 'store_id' not in df.columns:
        df['store_id'] = pd.NA

    # Normaliseer store_employees: sommige versies gebruiken employee_id ipv user_id
    if 'employee_id' in df_store_employees.columns and 'user_id' not in df_store_employees.columns:
        df_store_employees = df_store_employees.rename(columns={'employee_id': 'user_id'})

    participant_store_maps: list[pd.DataFrame] = []
    if 'user_id' in df_store_employees.columns and 'store_id' in df_store_employees.columns:
        df_store_link = df_store_employees[['user_id', 'store_id']].copy()
        df_store_link['user_id'] = pd.to_numeric(df_store_link['user_id'], errors='coerce').astype('Int64')
        df_store_link['store_id'] = pd.to_numeric(df_store_link['store_id'], errors='coerce').astype('Int64')
        df_store_link = df_store_link.dropna(subset=['user_id', 'store_id']).drop_duplicates()

        # Route 1: participants bevat direct user_id.
        if {'id', 'user_id'}.issubset(df_participants.columns):
            direct_map = df_participants[['id', 'user_id']].copy()
            direct_map['id'] = pd.to_numeric(direct_map['id'], errors='coerce')
            direct_map['user_id'] = pd.to_numeric(direct_map['user_id'], errors='coerce')
            direct_map = ( # type: ignore
                direct_map.dropna(subset=['id', 'user_id'])
                .merge(df_store_link, on='user_id', how='left')
                .rename(columns={'id': 'participant_id'})
            )
            participant_store_maps.append(direct_map[['participant_id', 'store_id']])

        # Route 2: participants.public_id -> my_clic.public_id -> user_id.
        if not df_my_clic.empty and {'id', 'public_id'}.issubset(df_participants.columns) and {'public_id', 'user_id'}.issubset(df_my_clic.columns):
            public_map = df_participants[['id', 'public_id']].copy()
            public_map = public_map.dropna(subset=['id', 'public_id'])
            my_clic_public = df_my_clic[['public_id', 'user_id']].copy()
            my_clic_public['user_id'] = pd.to_numeric(my_clic_public['user_id'], errors='coerce')
            public_map = ( # type: ignore
                public_map.merge(my_clic_public.dropna(subset=['public_id', 'user_id']), on='public_id', how='left')
                .merge(df_store_link, on='user_id', how='left')
                .rename(columns={'id': 'participant_id'})
            )
            participant_store_maps.append(public_map[['participant_id', 'store_id']])

        # Route 3: participants.pmo_id -> my_clic.id -> user_id.
        if not df_my_clic.empty and {'id', 'pmo_id'}.issubset(df_participants.columns) and {'id', 'user_id'}.issubset(df_my_clic.columns):
            pmo_map = df_participants[['id', 'pmo_id']].copy()
            pmo_map['pmo_id'] = pd.to_numeric(pmo_map['pmo_id'], errors='coerce')
            my_clic_id = df_my_clic[['id', 'user_id']].copy()
            my_clic_id['id'] = pd.to_numeric(my_clic_id['id'], errors='coerce')
            my_clic_id['user_id'] = pd.to_numeric(my_clic_id['user_id'], errors='coerce')
            pmo_map = ( # type: ignore
                pmo_map.dropna(subset=['id', 'pmo_id'])
                .merge(my_clic_id.dropna(subset=['id', 'user_id']), left_on='pmo_id', right_on='id', how='left')
                .merge(df_store_link, on='user_id', how='left')
                .rename(columns={'id_x': 'participant_id'})
            )
            participant_store_maps.append(pmo_map[['participant_id', 'store_id']])

    participant_store_map = (
        pd.concat(participant_store_maps, ignore_index=True)
        if participant_store_maps
        else pd.DataFrame(columns=['participant_id', 'store_id'])
    )
    participant_store_map['participant_id'] = pd.to_numeric(participant_store_map['participant_id'], errors='coerce')
    participant_store_map['store_id'] = pd.to_numeric(participant_store_map['store_id'], errors='coerce')
    participant_store_map = participant_store_map.dropna(subset=['participant_id', 'store_id'])
    participant_store_map = participant_store_map.drop_duplicates(subset=['participant_id'], keep='first')

    if not participant_store_map.empty:
        df = df.merge(participant_store_map[['participant_id', 'store_id']], on='participant_id', how='left', suffixes=('', '_new'))
        if 'store_id_new' in df.columns:
            df['store_id'] = df['store_id_new'].combine_first(df['store_id'])
            df = df.drop(columns=['store_id_new'])
    
    df['completion_created_at'] = pd.to_datetime(df['completion_created_at'], errors='coerce')
    df = df.dropna(subset=['completion_created_at'])
    df['jaar'] = df['completion_created_at'].dt.year
    # Use all available years (based on data), but keep 2019 and onwards
    jaren_geldig = sorted(df['jaar'].dropna().unique())
    jaren_geldig = [y for y in jaren_geldig if y >= 2019]
    return df[df['jaar'].isin(jaren_geldig)]


def bereken_verandering(df_history_geldig: pd.DataFrame) -> pd.DataFrame:
    df_sorted = df_history_geldig.sort_values(['participant_id', 'slug', 'completion_created_at'])
    df_eerste = (
        df_sorted.groupby(['participant_id', 'slug']).first().reset_index()
        [['participant_id', 'slug', 'score_value', 'completion_created_at']]
        .rename(columns={'score_value': 'eerste_score', 'completion_created_at': 'eerste_datum'})
    )
    df = df_sorted.merge(df_eerste, on=['participant_id', 'slug'], how='left')
    df['verandering'] = df['score_value'] - df['eerste_score']
    df = df[df['completion_created_at'] > df['eerste_datum']]
    df['dagen'] = (df['completion_created_at'] - df['eerste_datum']).dt.days
    df['periode'] = pd.cut(
        df['dagen'],
        bins=[0, 180, 365, 730, 1095, 99999],
        labels=['0-6 mnd', '6-12 mnd', '1-2 jaar', '2-3 jaar', '3+ jaar']
    )
    df_per_participant = (
        df.dropna(subset=['periode'])
        .groupby(['participant_id', 'slug', 'periode'], observed=False)
        .agg(verandering_per_participant=('verandering', 'mean'))
        .reset_index()
    )
    df_trend = df_per_participant.groupby(['periode', 'slug'], observed=False).agg(
        mean=('verandering_per_participant', 'mean'),
        count=('verandering_per_participant', 'count'),
        n_participanten=('participant_id', 'nunique'),
    ).reset_index()
    return df_trend[df_trend['n_participanten'] >= 1]


def _weighted_average(values, weights):
    """
    Bereken gewogen gemiddelde.
    
    Parameters:
    -----------
    values : array-like
        De waarden om gemiddelde van te berekenen
    weights : array-like
        De gewichten (bijv. aantal deelnemers per meetpunt)
    
    Returns:
    --------
    float
        Het gewogen gemiddelde
    """
    if len(values) == 0:
        return pd.NA
    values_arr = pd.to_numeric(values, errors='coerce')
    weights_arr = pd.to_numeric(weights, errors='coerce')
    # Verwijder missende of niet-positieve gewichten
    mask = ~(values_arr.isna() | weights_arr.isna()) & (weights_arr > 0)
    if not mask.any():
        return pd.NA
    total_weight = weights_arr[mask].sum()
    if total_weight <= 0:
        return pd.NA
    return (values_arr[mask] * weights_arr[mask]).sum() / total_weight


def get_available_stores(base_pad: Path, db_url: str) -> pd.DataFrame:
    """
    Get all stores that have score history data.
    
    Returns:
    --------
    pd.DataFrame
        DataFrame met store_id en store_name kolommen, sorted by store_name
    """
    # Load data with store_id
    df_history = laad_longitudinale_data(base_pad, db_url)
    
    # Get unique store IDs with data
    stores_with_data = df_history['store_id'].dropna().unique()
    
    if len(stores_with_data) == 0:
        return pd.DataFrame({'store_id': [], 'store_name': []})
    
    stores_df = load_stores(db_url or DB_URL)
    if stores_df.empty:
        return pd.DataFrame({'store_id': [], 'store_name': []})
        
    stores_df = stores_df[stores_df['id'].isin(stores_with_data)].copy()
    
    stores_df = stores_df.rename(columns={'id': 'store_id', 'name': 'store_name'})
    stores_df = stores_df.sort_values('store_name').reset_index(drop=True)
    
    return stores_df


def laad_store_average_scores(base_pad: Path) -> pd.DataFrame:
    """
    Laad gemiddelde scores per store uit parquet en koppel store-namen.
    Laad gemiddelde scores per store uit database en koppel store-namen.
    """
    df_scores = load_table_from_database('store_average_scores', DB_URL)

    if df_scores.empty:
        return pd.DataFrame(columns=['store_id', 'store_name', 'average', 'date', 'participants_count', 'score_slug'])
    
    df_stores = load_stores(DB_URL).copy()
    
    # Zorg dat id en name kolommen bestaan voordat we dropna doen
    if 'id' not in df_stores.columns: df_stores['id'] = pd.NA
    if 'name' not in df_stores.columns: df_stores['name'] = 'Onbekend'
    df_stores = df_stores.dropna(subset=['id']).drop_duplicates(subset='id')[['id', 'name']].copy()
    df_stores = df_stores.rename(columns={'id': 'store_id', 'name': 'store_name'})
    df_stores['store_id'] = pd.to_numeric(df_stores['store_id'], errors='coerce')

    # Defensieve verwerking van scores kolommen om KeyErrors te voorkomen
    for col in ['store_id', 'average', 'participants_count']:
        if col in df_scores.columns:
            df_scores[col] = pd.to_numeric(df_scores[col], errors='coerce')
        else:
            df_scores[col] = pd.NA

    if 'date' in df_scores.columns:
        # Probeer datums robuust te parsen. dayfirst=True helpt bij NL/database formaten
        df_scores['date'] = pd.to_datetime(df_scores['date'], errors='coerce', dayfirst=True)
    else:
        df_scores['date'] = pd.NaT

    if 'score_slug' not in df_scores.columns:
        df_scores['score_slug'] = pd.NA

    df_scores = df_scores.merge(df_stores, on='store_id', how='left')
    if 'store_name' in df_scores.columns:
        fallback_names = df_scores['store_id'].apply(
            lambda store_id: f"Store #{int(store_id)}" if pd.notna(store_id) else "Onbekend"
        )
        df_scores['store_name'] = df_scores['store_name'].fillna(fallback_names)

    # NIEUW: Koppel partners aan de scores om op opdrachtgeverniveau te kunnen aggregeren
    df_partners = load_table_from_database('partners', DB_URL)
    if not df_partners.empty and 'partner_id' in df_stores.columns:
        df_store_meta = df_stores.merge(
            df_partners[['id', 'name']].rename(columns={'id': 'partner_id', 'name': 'partner_name'}),
            on='partner_id', how='left'
        )
        df_scores = df_scores.merge(
            df_store_meta[['store_id', 'partner_name']], 
            on='store_id', how='left'
        )
        # Gebruik Partner naam als primaire groepering, fallback naar Store naam
        df_scores['store_name'] = df_scores['partner_name'].fillna(df_scores['store_name'])

    return df_scores.dropna(subset=['store_id', 'average', 'date'])


def _transform_store_score_values(df_scores: pd.DataFrame, score_slug: str) -> tuple[pd.DataFrame, str]:
    """
    Zet scorewaarden om naar beter interpreteerbare schaal waar nodig.
    Geeft getransformeerde dataframe en een suffix voor labels terug.
    """
    df_scores = df_scores.copy()
    label_suffix = ''

    if score_slug == 'rec_ls_exercise_steps_per_day':
        # Deze score is opgeslagen in duizenden stappen per dag.
        df_scores['average'] = df_scores['average'] * 1000

    return df_scores, label_suffix


def get_available_stores_from_average_scores(base_pad: Path) -> pd.DataFrame:
    """
    Geef stores terug waarvoor gemiddelde scorehistorie beschikbaar is.
    """
    df_scores = laad_store_average_scores(base_pad)
    stores_df = (
        df_scores[['store_id', 'store_name']]
        .drop_duplicates()
        .sort_values('store_name')
        .reset_index(drop=True)
    )
    return stores_df


def get_available_stores_with_score_changes(base_pad: Path, score_slug: str,
                                            min_deelnemers: int = 1) -> pd.DataFrame:
    """
    Geef alleen stores terug die voor de gekozen score minstens één bruikbaar
    veranderingspunt hebben na filtering op minimum deelnemers.
    """
    df_trends = _prepare_store_score_trends(
        base_pad=base_pad,
        score_slug=score_slug,
        min_deelnemers=min_deelnemers,
        store_id=None,
        aggregate_all=False,
    )
    if df_trends.empty:
        return pd.DataFrame(columns=['store_id', 'store_name'])

    geldige_store_ids = (
        df_trends.groupby(['store_id', 'store_name'])['gemiddelde_score']
        .apply(lambda s: s.notna().any())
        .reset_index(name='heeft_data')
    )
    geldige_store_ids = geldige_store_ids[geldige_store_ids['heeft_data']]

    return (
        geldige_store_ids[['store_id', 'store_name']]
        .sort_values('store_name')
        .reset_index(drop=True)
    )


def _prepare_store_score_trends(base_pad: Path, score_slug: str,
                                min_deelnemers: int = 1,
                                store_id: int = None,
                                aggregate_all: bool = False) -> pd.DataFrame:
    history_slug = _dashboard_score_to_history_slug(score_slug)
    df_history = laad_longitudinale_data(base_pad, DB_URL)
    df_scores = df_history[df_history['slug'] == history_slug].copy()

    links = _laad_opdrachtgever_links(DB_URL)
    if not links.empty and 'participant_id' in df_scores.columns:
        df_scores = df_scores.drop(columns=[c for c in ['store_id', 'store_name'] if c in df_scores.columns])
        df_scores = df_scores.merge(
            links[['participant_id', 'store_id', 'store_name']],
            on='participant_id',
            how='inner',
        )

    if df_scores.empty:
        empty = pd.DataFrame(columns=[
            'store_id', 'store_name', 'jaar_maand', 'gemiddelde_score',
            'gem_deelnemers', 'n_dagen', 'gemiddelde_verandering'
        ])
        empty.attrs['label_suffix'] = ''
        return empty

    df_scores = df_scores.rename(columns={'score_value': 'average'})
    df_scores['participants_count'] = 1
    df_scores, label_suffix = _transform_store_score_values(df_scores, score_slug)

    if store_id is not None:
        df_scores = df_scores[df_scores['store_id'] == store_id]

    df_scores['average'] = pd.to_numeric(df_scores['average'], errors='coerce')
    df_scores['completion_created_at'] = pd.to_datetime(df_scores['completion_created_at'], errors='coerce')
    df_scores = df_scores.dropna(subset=['store_id', 'store_name', 'average', 'completion_created_at'])
    if df_scores.empty:
        # Voorkom KeyError door de kolom alsnog (leeg) aan te maken
        df_scores['gemiddelde_verandering'] = pd.Series(dtype=float)
        return df_scores

    df_scores['jaar_maand'] = df_scores['completion_created_at'].dt.to_period('M').dt.to_timestamp()

    df_per_deelnemer = (
        df_scores.groupby(['store_id', 'store_name', 'jaar_maand', 'participant_id'], as_index=False)
        .agg(
            score_per_deelnemer=('average', 'mean'),
            n_metingen=('average', 'count'),
            eerste_meting=('completion_created_at', 'min'),
        )
    )

    df_maand = (
        df_per_deelnemer.groupby(['store_id', 'store_name', 'jaar_maand'], as_index=False)
        .agg(
            gemiddelde_score=('score_per_deelnemer', 'mean'),
            n_deelnemers=('participant_id', 'nunique'),
            n_metingen=('n_metingen', 'sum'),
            n_dagen=('eerste_meting', lambda s: s.dt.date.nunique())
        )
    )

    # Bereken totaalgemiddelde over alle data voor de referentielijn
    df_totaal = df_per_deelnemer.groupby('jaar_maand').agg(
        totaal_gemiddelde=('score_per_deelnemer', 'mean')
    ).reset_index()

    min_deelnemers = max(1, int(min_deelnemers))
    df_maand = df_maand[df_maand['n_deelnemers'] >= min_deelnemers].copy()
    df_maand = df_maand.merge(df_totaal, on='jaar_maand', how='left')

    if df_maand.empty:
        return df_maand

    df_maand = df_maand.sort_values(['store_name', 'jaar_maand']).reset_index(drop=True)

    if df_maand.empty:
        return df_maand

    df_maand['gemiddelde_verandering'] = (
        df_maand
        .groupby('store_id')['gemiddelde_score']
        .diff()
        .fillna(0.0)
    )

    df_maand.attrs['label_suffix'] = label_suffix
    return df_maand


def _empty_store_plot(melding: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=melding, showarrow=False, font=dict(size=13))
    fig.update_layout(template='plotly_white', height=450)
    return fig


def maak_store_gemiddelde_scores_plot(base_pad: Path, score_slug: str,
                                      score_label: str, min_deelnemers: int = 1,
                                      store_id: int = None,
                                      richting_label: str = '') -> go.Figure:
    df_plot = _prepare_store_score_trends(
        base_pad=base_pad,
        score_slug=score_slug,
        min_deelnemers=min_deelnemers,
        store_id=store_id,
    )

    if df_plot.empty:
        return _empty_store_plot("Geen scoredata beschikbaar voor deze selectie.")

    label_suffix = df_plot.attrs.get('label_suffix', '')
    y_label = f'Gemiddelde {score_label.lower()}{label_suffix}'

    fig = px.line(
        df_plot,
        x='jaar_maand',
        y='gemiddelde_score',
        color='store_name',
        markers=True,
        custom_data=['gemiddelde_score', 'n_deelnemers', 'n_metingen', 'n_dagen'],
        labels={
            'jaar_maand': 'Periode',
            'gemiddelde_score': y_label,
            'store_name': 'Selectie',
        },
        title=f'{y_label} over tijd',
    )
    fig.update_traces(
        hovertemplate=(
            '<b>%{fullData.name}</b><br>' +
            'Periode: %{x|%b %Y}<br>' +
            'Maandgemiddelde: %{y:,.0f}<br>' if score_slug == 'rec_ls_exercise_steps_per_day'
            else 'Maandgemiddelde: %{y:.2f}<br>'
        ) + (
            'Werknemers: %{customdata[1]}<br>' +
            'Metingen: %{customdata[2]}<br>' +
            'Dagen met data: %{customdata[3]}<extra></extra>'
        )
    )
    if score_slug == 'rec_ls_exercise_steps_per_day':
        fig.update_yaxes(tickformat=',.0f')

    # Voeg referentielijn toe bij selectie van één bedrijf
    if store_id is not None and not df_plot.empty:
        fig.add_trace(go.Scatter(
            x=df_plot['jaar_maand'],
            y=df_plot['totaal_gemiddelde'],
            name=tr('Totaalgemiddelde (alle)', 'nl'),
            line=dict(color='gray', dash='dash', width=2),
            opacity=0.6,
            hovertemplate='Totaal: %{y:.2f}<extra></extra>'
        ))

    if richting_label:
        fig.add_annotation(
            text=richting_label,
            xref='paper', yref='paper', x=0.01, y=1.12,
            showarrow=False, font=dict(size=12, color='dimgray')
        )
    fig.update_layout(
        template='plotly_white',
        hovermode='x unified',
        height=500,
        legend_title_text='Selectie',
    )
    return fig


def maak_store_gemiddelde_verandering_plot(base_pad: Path, score_slug: str,
                                           score_label: str, min_deelnemers: int = 1,
                                           store_id: int = None,
                                           richting_label: str = '') -> go.Figure:
    df_plot = _prepare_store_score_trends(
        base_pad=base_pad,
        score_slug=score_slug,
        min_deelnemers=min_deelnemers,
        store_id=store_id,
    )

    df_plot = df_plot.copy()
    if 'gemiddelde_verandering' not in df_plot.columns:
        return _empty_store_plot("Nog onvoldoende meetmomenten om verandering te tonen.")
    df_plot['gemiddelde_verandering'] = pd.to_numeric(df_plot['gemiddelde_verandering'], errors='coerce').fillna(0.0)
    if df_plot.empty:
        return _empty_store_plot("Nog onvoldoende meetmomenten om verandering te tonen.")

    label_suffix = df_plot.attrs.get('label_suffix', '')
    y_label = f'Gemiddelde verandering in {score_label.lower()}{label_suffix}'

    fig = px.line(
        df_plot,
        x='jaar_maand',
        y='gemiddelde_verandering',
        color='store_name',
        markers=True,
        custom_data=['gemiddelde_verandering', 'n_deelnemers', 'n_metingen', 'n_dagen'],
        labels={
            'jaar_maand': 'Periode',
            'gemiddelde_verandering': y_label,
            'store_name': 'Selectie',
        },
        title=f'{y_label} over tijd',
    )
    fig.update_traces(
        hovertemplate=(
            '<b>%{fullData.name}</b><br>' +
            'Periode: %{x|%b %Y}<br>' +
            'Maandverandering: %{y:,.0f}<br>' if score_slug == 'rec_ls_exercise_steps_per_day'
            else 'Maandverandering: %{y:.2f}<br>'
        ) + (
            'Werknemers: %{customdata[1]}<br>' +
            'Metingen: %{customdata[2]}<br>' +
            'Dagen met data: %{customdata[3]}<extra></extra>'
        )
    )
    if score_slug == 'rec_ls_exercise_steps_per_day':
        fig.update_yaxes(tickformat=',.0f')
    fig.add_hline(y=0, line_dash='dash', line_color='black')
    if richting_label:
        fig.add_annotation(
            text=richting_label,
            xref='paper', yref='paper', x=0.01, y=1.12,
            showarrow=False, font=dict(size=12, color='dimgray')
        )
    fig.update_layout(
        template='plotly_white',
        hovermode='x unified',
        height=500,
        legend_title_text='Selectie',
    )
    return fig


def maak_store_scoreverbetering_plot(base_pad: Path, db_url: str, score_type: str = 'job_satisfaction',
                                      maanden_window: int = 3, store_id: int = None) -> go.Figure:
    """
    Toont score trend over tijd per maand, optioneel gefilterd per store.
    
    Parameters:
    -----------
    base_pad : Path
        Pad naar de data directory
    db_url : str
        Database URL
    score_type : str
        Welke score weergeven (bijv. 'job_satisfaction', 'stress', 'wellbeing')
    maanden_window : int
        Venstergrootte voor rolling average in maanden
    store_id : int, optional
        Store ID om te filteren. Als None, tonen alle stores samen.
    
    Returns:
    --------
    go.Figure
        Plotly line chart met trend over tijd
    """
    # Longitudinale data laden
    df_history = laad_longitudinale_data(base_pad, db_url)
    
    # Alleen de gekozen score-type
    df_history = df_history[df_history['slug'] == score_type].copy()
    if len(df_history) == 0:
        fig = go.Figure()
        fig.add_annotation(text=f"❌ Geen data beschikbaar voor '{score_type}'.", 
                          showarrow=False, font=dict(size=12))
        return fig
    
    # Filter op store_id als opgegeven
    store_name = "alle deelnemers"
    if store_id is not None and store_id > 0:
        df_history = df_history[df_history['store_id'] == store_id]
        if len(df_history) == 0:
            fig = go.Figure()
            fig.add_annotation(text=f"❌ Geen data beschikbaar voor store {store_id} en score '{score_type}'.", 
                              showarrow=False, font=dict(size=12))
            return fig
        # Get store name from the database
        try:
            if _has_valid_db_url(db_url):
                engine = create_engine(db_url)
                with engine.connect() as conn:
                    result = pd.read_sql(f"SELECT name FROM stores WHERE id = {store_id}", conn)
            else:
                result = load_stores(DB_URL)[['id', 'name']]
                result = result[result['id'] == store_id]
            if len(result) > 0:
                store_name = result['name'].iloc[0]
            else:
                store_name = f"Store {store_id}"
        except:
            store_name = f"Store {store_id}"
    
    # Score waarden numeriek maken en opschonen
    df_history['score_value'] = pd.to_numeric(df_history['score_value'], errors='coerce')
    df_history = df_history.dropna(subset=['score_value', 'completion_created_at'])
    
    if len(df_history) == 0:
        fig = go.Figure()
        fig.add_annotation(text="❌ Geen geldige score data.", 
                          showarrow=False, font=dict(size=12))
        return fig
    
    # Eerst per deelnemer per maand middelen, zodat frequente invullers niet zwaarder tellen.
    df_history['jaar_maand'] = df_history['completion_created_at'].dt.to_period('M')
    df_participant_maand = (
        df_history.groupby(['participant_id', 'jaar_maand'])
        .agg(score_per_participant=('score_value', 'mean'))
        .reset_index()
    )

    # Aggregatie per maand
    df_agg = df_participant_maand.groupby('jaar_maand').agg(
        score_mean=('score_per_participant', 'mean'),
        score_std=('score_per_participant', 'std'),
        n_metingen=('score_per_participant', 'count'),
        n_participants=('participant_id', 'nunique'),
    ).reset_index()
    
    # Filter: minimaal 2 deelnemers per maand
    df_agg = df_agg[df_agg['n_participants'] >= 2]
    
    if len(df_agg) < 2:
        fig = go.Figure()
        fig.add_annotation(
            text=f"⚠️ Onvoldoende data<br>Slechts {len(df_agg)} maanden met genoeg metingen", 
            showarrow=False, font=dict(size=12)
        )
        return fig
    
    # Timestamp voor plotting
    df_agg['timestamp'] = df_agg['jaar_maand'].dt.to_timestamp()
    df_agg = df_agg.sort_values('timestamp')
    
    # Voortschrijdend gemiddelde
    df_agg['score_smooth'] = df_agg['score_mean'].rolling(
        window=maanden_window, center=True, min_periods=1
    ).mean()
    df_agg['score_std_smooth'] = df_agg['score_std'].rolling(
        window=maanden_window, center=True, min_periods=1
    ).mean()
    
    # Plotly figure
    fig = go.Figure()
    
    # Main line
    fig.add_trace(go.Scatter(
        x=df_agg['timestamp'],
        y=df_agg['score_smooth'],
        mode='lines+markers',
        name='Gemiddelde score',
        line=dict(width=3, color=HOOFD_KLEUR),
        marker=dict(size=8),
        hovertemplate=(
            '<b>Periode</b><br>' +
            'Datum: %{x|%b %Y}<br>' +
            'Gemiddelde: %{y:.2f}<br>' +
            'Metingen: %{customdata[0]}<br>' +
            'Deelnemers: %{customdata[1]}<extra></extra>'
        ),
        customdata=df_agg[['n_metingen', 'n_participants']].astype(int).values,
    ))
    
    # Std band
    fig.add_trace(go.Scatter(
        x=df_agg['timestamp'],
        y=df_agg['score_smooth'] + df_agg['score_std_smooth'],
        mode='lines',
        line=dict(width=0),
        showlegend=False,
        hoverinfo='skip',
    ))
    fig.add_trace(go.Scatter(
        x=df_agg['timestamp'],
        y=df_agg['score_smooth'] - df_agg['score_std_smooth'],
        mode='lines',
        line=dict(width=0),
        name='±1 Std Dev',
        fillcolor='rgba(232, 119, 34, 0.2)',
        fill='tonexty',
        hoverinfo='skip',
    ))
    
    # Labels
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
        title=f'{score_label_nl} trend over tijd<br><sub>Voortschrijdend gemiddelde ({maanden_window} mnd), {store_name}</sub>',
        xaxis_title='Periode',
        yaxis_title=f'Gemiddelde {score_label_nl.lower()}',
        hovermode='x unified',
        height=500,
        template='plotly_white',
        legend=dict(x=0.01, y=0.99, bgcolor='rgba(255,255,255,0.8)'),
    )
    
    return fig


def maak_bmi_beweging_plot(df: pd.DataFrame, geslacht: str = 'beide', lang: str = 'nl'):
    """
    Line plot van BMI en Bewegingsminuten per week over tijd.
    Gebruikt jaargemiddelden. Dubbele y-as: BMI links, beweging rechts.
    """
    df_bmi_exercise = df[df['slug'].isin(['bmi', 'exercise'])].copy()
    if 'user_gender' in df_bmi_exercise.columns and geslacht in ('man', 'vrouw'):
        geslacht_code = 1 if geslacht == 'man' else 0
        df_bmi_exercise = df_bmi_exercise[df_bmi_exercise['user_gender'] == geslacht_code]

    df_bmi_exercise['score_value'] = pd.to_numeric(df_bmi_exercise['score_value'], errors='coerce')
    df_bmi_exercise = df_bmi_exercise.dropna(subset=['score_value', 'completion_created_at', 'participant_id'])
    df_bmi_exercise['jaar'] = df_bmi_exercise['completion_created_at'].dt.year
    jaren_geldig = sorted(df_bmi_exercise['jaar'].dropna().unique())
    jaren_geldig = [y for y in jaren_geldig if y >= 2019]
    df_bmi_exercise = df_bmi_exercise[df_bmi_exercise['jaar'].isin(jaren_geldig)]

    # Middel eerst per deelnemer per jaar per domein
    df_bmi_exercise = (
        df_bmi_exercise.groupby(['participant_id', 'jaar', 'slug'])
        .agg(score_per_participant=('score_value', 'mean'))
        .reset_index()
    )

    # Aantallen per jaar voor annotatie
    n_per_jaar = df_bmi_exercise.groupby('jaar')['participant_id'].nunique()

    df_pivot = df_bmi_exercise.groupby(['jaar', 'slug'])['score_per_participant'].mean().unstack()

    fig, ax_bmi = plt.subplots(figsize=(10, 5))
    ax_exercise = ax_bmi.twinx()

    if 'bmi' in df_pivot.columns:
        ax_bmi.plot(df_pivot.index, df_pivot['bmi'], marker='o',
                    color='salmon', linewidth=2, markersize=7, label='BMI')
        # Waarde annotaties bij elk punt
        for jaar, val in df_pivot['bmi'].items():
            ax_bmi.annotate(f'{val:.1f}', (jaar, val),
                            textcoords='offset points', xytext=(0, 8),
                            ha='center', fontsize=8, color='salmon')

    if 'exercise' in df_pivot.columns:
        ax_exercise.plot(df_pivot.index, df_pivot['exercise'], marker='o',
                         color='steelblue', linewidth=2, markersize=7, label='Bewegingsminuten/week')
        for jaar, val in df_pivot['exercise'].items():
            ax_exercise.annotate(f'{val:.0f}', (jaar, val),
                                 textcoords='offset points', xytext=(0, 8),
                                 ha='center', fontsize=8, color='steelblue')

    # N per jaar onderaan als secundaire x-as label
    ax_bmi.set_xticks(df_pivot.index)
    ax_bmi.set_xticklabels([
        f"{int(j)}\n(n={n_per_jaar.get(j, 0)})" for j in df_pivot.index
    ], fontsize=9)

    ax_bmi.set_xlabel('Jaar')
    ax_bmi.set_ylabel('Gemiddelde BMI', color='salmon')
    ax_exercise.set_ylabel('Gemiddelde bewegingsminuten per week', color='steelblue')

    ax_bmi.tick_params(axis='y', labelcolor='salmon')
    ax_exercise.tick_params(axis='y', labelcolor='steelblue')

    titel_suffix = {
        'man': f" — {tr('mannen', lang)}",
        'vrouw': f" — {tr('vrouwen', lang)}",
        'beide': '',
    }.get(geslacht, '')
    ax_bmi.set_title(f'BMI vs Beweging over tijd{titel_suffix}')
    ax_bmi.legend(loc='upper left', fontsize=9)
    ax_exercise.legend(loc='upper right', fontsize=9)
    ax_bmi.grid(axis='y', linestyle='--', alpha=0.4)

    plt.tight_layout()
    return fig

def maak_gemiddelde_score_over_tijd_plot(df_long: pd.DataFrame, slug: str, lang: str = 'nl', geslacht: str = 'beide') -> go.Figure:
    """
    Toont de gemiddelde score van een specifieke factor over tijd, plus
    gewogen gemiddelden per jaar waarbij maanden met meer deelnemers zwaarder meetellen.
    """
    df_factor = df_long[df_long['slug'] == slug].copy()

    if geslacht == 'man':
        df_factor = df_factor[df_factor['user_gender'] == 1]
    elif geslacht == 'vrouw':
        df_factor = df_factor[df_factor['user_gender'] == 0]

    df_factor['completion_created_at'] = pd.to_datetime(df_factor['completion_created_at'], errors='coerce')
    df_factor = df_factor.dropna(subset=['score_value', 'completion_created_at'])

    if df_factor.empty:
        fig = go.Figure()
        fig.add_annotation(text=tr("Geen data beschikbaar voor deze factor en selectie.", lang), showarrow=False, font=dict(size=14))
        fig.update_layout(template='plotly_white', height=450)
        return fig

    # Aggregeer per maand - bereken eerst per participant, dan gemiddelde
    df_factor['jaar_maand'] = df_factor['completion_created_at'].dt.to_period('M').dt.to_timestamp()
    
    # Per participant per maand: gemiddelde score
    df_participant_maand = df_factor.groupby(['participant_id', 'jaar_maand']).agg(
        score_per_participant=('score_value', 'mean'),
    ).reset_index()
    
    # Aantal unieke deelnemers per maand
    df_agg = df_participant_maand.groupby('jaar_maand').agg(
        gemiddelde_score=('score_per_participant', 'mean'),  # Gemiddelde van participantgemiddelden
        n_deelnemers=('participant_id', 'nunique'),
    ).reset_index()

    df_agg = df_agg[df_agg['n_deelnemers'] >= 1]

    if df_agg.empty:
        fig = go.Figure()
        fig.add_annotation(text=tr("Onvoldoende deelnemers per periode om een trend te tonen.", lang), showarrow=False, font=dict(size=14))
        fig.update_layout(template='plotly_white', height=450)
        return fig

    df_agg['jaar'] = df_agg['jaar_maand'].dt.year
    df_jaar = pd.DataFrame([
        {
            'jaar': jaar,
            'gewogen_gemiddelde': _weighted_average(group['gemiddelde_score'], group['n_deelnemers']),
            'start_datum': group['jaar_maand'].min(),
            'eind_datum': group['jaar_maand'].max(),
        }
        for jaar, group in df_agg.groupby('jaar')
    ])

    # Get factor label from variabelen.py or use slug
    factor_label = slug
    for group_vars in VARIABELEN_PER_GROEP.values():
        for var_spec in group_vars:
            if var_spec.get('kolom') == slug:
                factor_label = var_spec.get('label', slug)
                break
        if factor_label != slug:
            break
    
    # Translate label
    factor_label = tr(factor_label, lang)

    fig = px.line(
        df_agg,
        x='jaar_maand',
        y='gemiddelde_score',
        markers=True,
        custom_data=['n_deelnemers'],
        labels={
            'jaar_maand': tr('Datum', lang),
            'gemiddelde_score': tr(f'Gemiddelde {factor_label.lower()}', lang),
        },
        title=tr(f'Gemiddelde {factor_label} over tijd', lang),
        color_discrete_sequence=[HOOFD_KLEUR]
    )
    fig.update_traces(
        hovertemplate=(
            '<b>%{x|%b %Y}</b><br>' +
            tr('Gemiddelde', lang) + ': %{y:.2f}<br>' +
            tr('Deelnemers', lang) + ': %{customdata[0]}<extra></extra>'
        )
    )
    for i, jaar_row in df_jaar.iterrows():
        gewogen_gemiddelde = jaar_row['gewogen_gemiddelde']
        if pd.isna(gewogen_gemiddelde):
            continue
        fig.add_trace(
            go.Scatter(
                x=[jaar_row['start_datum'], jaar_row['eind_datum']],
                y=[float(gewogen_gemiddelde), float(gewogen_gemiddelde)],
                mode='lines',
                name=tr('Gewogen gemiddelde per jaar', lang),
                line=dict(color='dimgray', dash='dash', width=2),
                hovertemplate=(
                    f"{jaar_row['jaar']}<br>" +
                    tr('Gewogen gemiddelde', lang) + ': %{y:.2f}<br>' +
                    tr('Gewogen op aantal deelnemers per maand', lang) +
                    '<extra></extra>'
                ),
                showlegend=(i == 0),
            )
        )
    fig.update_layout(
        template='plotly_white',
        hovermode='x unified',
        height=500,
    )
    return fig

def maak_scoreverandering_plot(df_trend: pd.DataFrame, lang: str = 'nl'):
    alle_factoren = sorted(df_trend['slug'].dropna().unique())
    factor_labels = {
        'age': tr('Leeftijd', lang),
        'bmi': 'BMI',
        'alcohol': tr('Alcohol', lang),
        'exercise': tr('Beweging', lang),
        'fruit': tr('Fruit', lang),
        'vegetables': tr('Groenten', lang),
        'smoking': tr('Roken', lang),
        'stress': tr('Stress', lang),
        'sugar': tr('Suiker', lang),
        'fat': tr('Vet', lang),
        'salt': tr('Zout', lang), 
        'blood_pressure': tr('Bloeddruk', lang),
        'diabetes': tr('Diabetes', lang), 
        'diabetes': tr('Diabetes', lang),
        'dass_stress': 'DASS Stress',
        'dass_anxiety': tr('DASS Angst', lang),
        'dass_depression': tr('DASS Depressie', lang),
        'sleep': tr('Slaap', lang),
        'steps': tr('Stappen', lang),
        'resilience': tr('Veerkracht', lang),
        'wellbeing': tr('Welzijn', lang),
        'selfefficacy': tr('Zelfeffectiviteit', lang),
        'health': tr('Gezondheid', lang),
        'digital_detox_stress': tr('Digitale detox stress', lang),
        'digital_detox_addiction_risk': tr('Smartphone verslaving', lang),
        'menopause_somatic': tr('Menopauze (somatisch)', lang),
        'menopause_psychological': tr('Menopauze (psychologisch)', lang),
        'menopause_genitourinary': tr('Menopauze (genitourinair)', lang),
    }
    # For unknown factors, use the slug as label
    for f in alle_factoren:
        if f not in factor_labels:
            factor_labels[f] = f.replace('_', ' ').title()
    
    lager_is_beter = [
        'alcohol', 'smoking', 'stress', 'bmi', 'sugar', 'fat', 'salt', 'blood_pressure', 'diabetes',
        'dass_stress', 'dass_anxiety', 'dass_depression', 'sleep',
        'digital_detox_stress', 'digital_detox_addiction_risk',
        'menopause_somatic', 'menopause_psychological', 'menopause_genitourinary',
    ]
    factoren_aanwezig = alle_factoren

    cols = 3
    rows = (len(factoren_aanwezig) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(18, rows * 5))
    axes = axes.flatten()

    for i, factor in enumerate(factoren_aanwezig):
        df_factor = df_trend[df_trend['slug'] == factor]
        if factor in lager_is_beter:
            kleuren  = [RISICO_COLORS[0] if x <= 0 else RISICO_COLORS[2] for x in df_factor['mean']]
            richting = f"({tr('Lager = beter', lang).lower()})"
        else:
            kleuren  = [RISICO_COLORS[0] if x >= 0 else RISICO_COLORS[2] for x in df_factor['mean']]
            richting = f"({tr('Hoger = beter', lang).lower()})"

        axes[i].bar(df_factor['periode'].astype(str), df_factor['mean'], color=kleuren)
        axes[i].axhline(y=0, color='black', linestyle='--', linewidth=0.8)
        axes[i].set_title(f"{factor_labels.get(factor, factor)}\n{richting}", fontsize=9)
        axes[i].set_xlabel(tr('Periode na eerste meting', lang), fontsize=8)
        axes[i].set_ylabel(tr('Gemiddelde verandering', lang), fontsize=8)
        axes[i].tick_params(axis='x', rotation=45, labelsize=7)

    for j in range(len(factoren_aanwezig), len(axes)):
        axes[j].set_visible(False)

    plt.suptitle(tr('Scoreverandering ten opzichte van eerste meting per factor', lang), fontsize=14)
    plt.tight_layout()
    return fig


# ── Dieet score ────────────────────────────────────────────────────────────────
DIEET_SCORE_COLS = [
    'rec_ls_score_fruit', 'rec_ls_score_vegetables', 'rec_ls_score_sugar',
    'rec_ls_score_saturated_fat', 'rec_ls_score_alcohol', 'rec_ls_score_natrium'
]
DIEET_GRENZEN = [0, 2.0, 2.8, 3.4, 4.2, 5.01]
DIEET_LABELS  = ['Slecht', 'Matig', 'Voldoende', 'Goed', 'Uitstekend']
DIEET_COLORS  = {
    'Slecht':     '#E74C3C',
    'Matig':      '#E87722',
    'Voldoende':  '#F4D03F',
    'Goed':       '#2ECC71',
    'Uitstekend': '#1A8A4A',
}


def voeg_dieet_score_toe(df: pd.DataFrame) -> pd.DataFrame:
    """Voegt dieet_score en dieet_cat kolommen toe aan het dataframe."""
    df = df.copy()
    beschikbaar = [c for c in DIEET_SCORE_COLS if c in df.columns]
    df['dieet_score'] = df[beschikbaar].mean(axis=1)
    df['dieet_cat'] = pd.cut(
        df['dieet_score'],
        bins=DIEET_GRENZEN,
        labels=DIEET_LABELS,
        include_lowest=True,
    )
    return df


def maak_dieet_verdeling_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    """Staafdiagram van de verdeling van dieet categorieën."""
    df = voeg_dieet_score_toe(df)
    counts = df['dieet_cat'].value_counts(normalize=True).mul(100).reset_index()
    counts.columns = ['categorie', 'percentage']
    labels_t = [tr(label, lang) for label in DIEET_LABELS]
    kleur_map = {tr(label, lang): kleur for label, kleur in DIEET_COLORS.items()}
    counts['categorie'] = counts['categorie'].astype(str).map(lambda x: tr(x, lang))
    counts['categorie'] = pd.Categorical(counts['categorie'], categories=labels_t, ordered=True)
    counts = counts.sort_values('categorie')

    fig = px.bar(
        counts, x='categorie', y='percentage',
        color='categorie',
        color_discrete_map=kleur_map,
        labels={'categorie': '', 'percentage': tr('Percentage (%)', lang)},
        title=tr('Verdeling dieetkwaliteit', lang),
        category_orders={'categorie': labels_t},
    )
    fig.update_layout(showlegend=False)
    return fig


def maak_dieet_bmi_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    """Gegroepeerd staafdiagram: dieet categorie vs BMI categorie."""
    df = voeg_dieet_score_toe(df)
    df['bmi_label'] = pd.to_numeric(df['rec_med_bmi_cat'], errors='coerce').map(
        {k: tr(v, lang) for k, v in BMI_LABELS.items()}
    )
    df2 = df.dropna(subset=['dieet_cat', 'bmi_label']).copy()
    df2['dieet_cat'] = df2['dieet_cat'].astype(str).map(lambda x: tr(x, lang))

    counts = df2.groupby(['dieet_cat', 'bmi_label']).size().reset_index(name='aantal')
    totaal = counts.groupby('dieet_cat')['aantal'].transform('sum')
    counts['percentage'] = counts['aantal'] / totaal * 100
    counts['n_diet_cat'] = totaal.astype(int)
    dieet_labels_t = [tr(label, lang) for label in DIEET_LABELS]
    counts['dieet_cat'] = pd.Categorical(counts['dieet_cat'], categories=dieet_labels_t, ordered=True)
    counts = counts.sort_values('dieet_cat')

    bmi_volgorde = [tr(BMI_LABELS[k], lang) for k in sorted(BMI_LABELS.keys())]
    bmi_kleuren  = {tr(v, lang): BMI_COLORS[k] for k, v in BMI_LABELS.items()}
    n_per_dieet = (
        counts[['dieet_cat', 'n_diet_cat']]
        .drop_duplicates()
        .sort_values('dieet_cat')
    )
    x_labels = {
        row['dieet_cat']: f"{row['dieet_cat']}<br>(n={int(row['n_diet_cat'])})"
        for _, row in n_per_dieet.iterrows()
    }
    counts['dieet_cat_label'] = counts['dieet_cat'].map(x_labels)

    fig = px.bar(
        counts,
        x='dieet_cat_label', y='percentage',
        color='bmi_label',
        barmode='stack',
        color_discrete_map=bmi_kleuren,
        custom_data=['aantal', 'n_diet_cat'],
        labels={
            'dieet_cat_label': tr('Dieetkwaliteit', lang),
            'percentage': tr('Percentage (%)', lang),
            'bmi_label': tr('BMI categorie', lang),
        },
        title=tr('BMI verdeling per dieetkwaliteit', lang),
        category_orders={
            'dieet_cat_label': [x_labels[label] for label in dieet_labels_t if label in x_labels],
            'bmi_label': bmi_volgorde,
        },
    )
    fig.update_traces(
        hovertemplate=(
            '<b>%{x}</b><br>' +
            tr('BMI categorie', lang) + ': %{fullData.name}<br>' +
            tr('Percentage', lang) + ': %{y:.1f}%<br>' +
            tr('Aantal', lang) + ': %{customdata[0]}<br>' +
            'n: %{customdata[1]}<extra></extra>'
        )
    )
    return fig


def maak_dieet_score_histogram(df: pd.DataFrame, geslacht: str = 'beide', lang: str = 'nl') -> go.Figure:
    """Verdeling van de ruwe dieet score, uitgesplitst naar geslacht."""
    df = voeg_dieet_score_toe(df)
    df2 = df.dropna(subset=['dieet_score'])
    if df2.empty:
        fig = go.Figure()
        fig.add_annotation(text=tr("Geen data beschikbaar voor deze selectie.", lang), showarrow=False)
        fig.update_layout(template='plotly_white', height=430)
        return fig

    if geslacht == 'beide':
        gender_labels = {k: tr(v, lang) for k, v in GENDER_LABELS.items()}
        df2['geslacht_label'] = pd.to_numeric(df2['rec_user_gender'], errors='coerce').map(gender_labels)
        df2 = df2.dropna(subset=['geslacht_label'])
        kleur_map = {gender_labels[k]: GENDER_COLORS[k] for k in gender_labels}
        volgorde = [gender_labels[1], gender_labels[0]]
        summary = (
            df2.groupby('geslacht_label', as_index=False)
            .agg(
                gemiddelde=('dieet_score', 'mean'),
                mediaan=('dieet_score', 'median'),
                n=('dieet_score', 'count'),
            )
        )

        fig = px.box(
            df2,
            x='geslacht_label',
            y='dieet_score',
            color='geslacht_label',
            color_discrete_map=kleur_map,
            points='all',
            labels={
                'dieet_score': tr('Dieet score (0-5)', lang),
                'geslacht_label': tr('Geslacht', lang),
            },
            title=tr('Dieet score naar geslacht', lang),
            category_orders={'geslacht_label': volgorde},
        )
        fig.update_traces(
            jitter=0.28,
            pointpos=0,
            marker=dict(size=4, opacity=0.28),
            line=dict(width=2),
        )
        fig.add_trace(
            go.Scatter(
                x=summary['geslacht_label'],
                y=summary['gemiddelde'],
                mode='markers+text',
                marker=dict(color='black', size=11, symbol='diamond'),
                text=summary.apply(
                    lambda row: f"{row['gemiddelde']:.2f}", axis=1),
                textposition='top center',
                showlegend=False,
            )
        )
    else:
        fig = px.box(
            df2,
            y='dieet_score',
            color_discrete_sequence=[HOOFD_KLEUR],
            points='all',
            labels={'dieet_score': tr('Dieet score (0-5)', lang)},
            title=tr('Dieet score', lang),
        )
        fig.update_traces(
            jitter=0.28,
            pointpos=0,
            marker=dict(size=4, opacity=0.28),
            line=dict(width=2),
        )

    fig.update_layout(template='plotly_white', height=430)
    return fig


# ── Variabelen verkenner ──────────────────────────────────────────────────────
def _kleur_voor_bar(labels_dict: dict, kleur_richting: str) -> dict:
    """
    Genereert kleurenmap voor bar plots op basis van richting.
    eerste_goed: eerste = groen, laatste = rood
    laatste_goed: eerste = rood, laatste = groen
    midden_goed:  uitersten rood, midden groen
    """
    volgorde = [labels_dict[k] for k in sorted(labels_dict.keys())]
    n = len(volgorde)
    if n == 1:
        return {volgorde[0]: HOOFD_KLEUR}

    # Kleurgradiënt van groen naar rood of omgekeerd
    groen, oranje, rood = '#2ECC71', '#E87722', '#E74C3C'

    if kleur_richting == 'eerste_goed':
        if n == 2:   kleuren = [groen, rood]
        elif n == 3: kleuren = [groen, oranje, rood]
        else:
            import numpy as np
            kleuren = []
            for i in range(n):
                t = i / (n - 1)
                if t < 0.5:
                    kleuren.append(groen if t < 0.25 else oranje)
                else:
                    kleuren.append(rood if t > 0.75 else oranje)
    elif kleur_richting == 'laatste_goed':
        if n == 2:   kleuren = [rood, groen]
        elif n == 3: kleuren = [rood, oranje, groen]
        else:
            kleuren = []
            for i in range(n):
                t = i / (n - 1)
                if t > 0.75: kleuren.append(groen)
                elif t > 0.25: kleuren.append(oranje)
                else: kleuren.append(rood)
    elif kleur_richting == 'midden_goed':
        midden = n // 2
        kleuren = []
        for i in range(n):
            dist = abs(i - midden) / midden if midden > 0 else 0
            if dist < 0.3: kleuren.append(groen)
            elif dist < 0.6: kleuren.append(oranje)
            else: kleuren.append(rood)
    else:
        kleuren = [HOOFD_KLEUR] * n

    return {v: kleuren[i] for i, v in enumerate(volgorde)}


def maak_verkenner_plot(df: pd.DataFrame, variabele: dict, geslacht_filter: str = 'beide', lang: str = 'nl') -> go.Figure:
    """Genereert de beste plot voor een variabele uit het register."""
    import sys

    kolom           = variabele['kolom']
    label           = variabele['label']
    plot_type       = variabele['plot_type']
    gender_ok       = variabele.get('split_gender', False)
    labels_map      = variabele.get('labels', None)
    schaal          = variabele.get('schaal_factor', None)
    eenheid         = variabele.get('eenheid', '')
    referentie      = variabele.get('referentie', None)
    ref_label       = variabele.get('referentie_label', '')
    outlier_max     = variabele.get('outlier_max', None)
    vtype           = variabele.get('type', None)
    kleur_richting  = variabele.get('kleur_richting', 'eerste_goed')
    min_score       = variabele.get('min_score', None)
    max_score       = variabele.get('max_score', None)

    if kolom not in df.columns:
        fig = go.Figure()
        fig.add_annotation(
            text=tr("Kolom '{kolom}' niet beschikbaar.", lang, kolom=kolom),
            showarrow=False,
            font=dict(size=14),
        )
        return fig

    df2 = df.copy()

    # Geslacht filter
    gender_labels = {k: tr(v, lang) for k, v in GENDER_LABELS.items()}
    df2['geslacht_label'] = pd.to_numeric(df2['rec_user_gender'], errors='coerce').map(gender_labels)
    if geslacht_filter == 'man':
        df2 = df2[df2['geslacht_label'] == gender_labels[1]]
    elif geslacht_filter == 'vrouw':
        df2 = df2[df2['geslacht_label'] == gender_labels[0]]
    elif geslacht_filter in {'beide', 'totaal', None}:
        df2 = df2.dropna(subset=['geslacht_label'])

    x_label = f"{label}" + (f" ({eenheid})" if eenheid else "")

    # ── Slaaptekst speciaal geval ──────────────────────────────────────────────
    if vtype == 'slaap_tekst':
        slaap_map_t = {k: tr(v, lang) for k, v in SLAAP_TEKST_MAP.items()}
        slaap_volgorde_t = [tr(v, lang) for v in SLAAP_VOLGORDE]
        slaap_kleuren_t = {tr(k, lang): v for k, v in SLAAP_KLEUREN.items()}
        df2['_label'] = df2[kolom].map(slaap_map_t)
        df2 = df2[df2['_label'].notna() & (df2['_label'] != 'None')]
        counts = df2['_label'].value_counts().reset_index()
        counts.columns = ['categorie', 'aantal']
        counts['pct'] = counts['aantal'] / counts['aantal'].sum() * 100
        counts['categorie'] = pd.Categorical(counts['categorie'], categories=slaap_volgorde_t, ordered=True)
        counts = counts.sort_values('categorie')
        fig = px.bar(counts, x='categorie', y='pct',
                     color='categorie', color_discrete_map=slaap_kleuren_t,
                     labels={'categorie': '', 'pct': tr('Percentage (%)', lang)},
                     title=label, category_orders={'categorie': slaap_volgorde_t})
        fig.update_layout(showlegend=False)
        return fig

    # ── Numerieke waarde ───────────────────────────────────────────────────────
    s = pd.to_numeric(df2[kolom], errors='coerce')

    # Schaalfactor toepassen — gebruik round om float precision issues te voorkomen
    if schaal:
        s = (s * schaal).round(1)

    # Outliers afkappen
    if outlier_max:
        masker = s <= outlier_max
        s  = s[masker]
        df2 = df2.loc[s.index]

    df2['_waarde'] = s

    # ── Histogram ─────────────────────────────────────────────────────────────
    if plot_type == 'histogram':
        df2 = df2.dropna(subset=['_waarde'])
        split_by_gender = gender_ok and geslacht_filter == 'beide'
        if split_by_gender:
            df2 = df2.dropna(subset=['geslacht_label'])
            kleur_map = {gender_labels[k]: GENDER_COLORS[k] for k in gender_labels}
            fig = px.histogram(
                df2, x='_waarde', color='geslacht_label',
                color_discrete_map=kleur_map,
                barmode='overlay', opacity=0.75, nbins=30,
                labels={'_waarde': x_label, 'count': tr('Aantal', lang), 'geslacht_label': tr('Geslacht', lang)},
                title=label,
                category_orders={'geslacht_label': [gender_labels[1], gender_labels[0]]},
            )
            # Vastzetten van bins op 0.5 voor scores
            if schaal or max_score:
                fig.update_traces(xbins=dict(
                    start=min_score if min_score is not None else 0.0,
                    end=max_score if max_score is not None else 10.0,
                    size=0.5
                ))
            fig.update_layout(legend_title_text=tr('Geslacht', lang))
        else:
            fig = px.histogram(
                df2, x='_waarde', nbins=30,
                color_discrete_sequence=[HOOFD_KLEUR],
                labels={'_waarde': x_label, 'count': tr('Aantal', lang)},
                title=label,
            )
        if referentie is not None:
            # Referentie staat altijd al op de weergaveschaal (0-10 of originele eenheid)
            # Nooit extra schaalfactor toepassen
            fig.add_vline(x=referentie, line_dash='dash', line_color='red',
                          annotation_text=ref_label, annotation_position='top right')

        # X-as bij 0 laten beginnen als schaal bekend is
        if min_score is not None and max_score is not None:
            fig.update_xaxes(range=[min_score, max_score])
        elif schaal is not None:
            # Geschaalde variabelen zijn altijd 0-10 tenzij expliciet anders ingesteld
            fig.update_xaxes(range=[0, 10])

    # ── Bar ───────────────────────────────────────────────────────────────────
    elif plot_type == 'bar':
        if labels_map:
            # Verwijder 'None' strings en converteer naar numeriek
            s_int = df2[kolom].replace('None', pd.NA)
            s_int = pd.to_numeric(s_int, errors='coerce')
            df2['_label'] = s_int.map(labels_map)
            df2 = df2.dropna(subset=['_label'])
            counts = df2['_label'].value_counts(normalize=True).mul(100).reset_index()
            counts.columns = ['categorie', 'percentage']
            counts['categorie'] = counts['categorie'].map(lambda x: tr(x, lang))
            aanwezige = set(counts['categorie'].astype(str).tolist())
            volgorde = [tr(labels_map[k], lang) for k in sorted(labels_map.keys()) if tr(labels_map[k], lang) in aanwezige]
            kleur_map = _kleur_voor_bar(
                {k: tr(v, lang) for k, v in labels_map.items() if tr(v, lang) in volgorde},
                kleur_richting
            )
            fig = px.bar(counts, x='categorie', y='percentage',
                         color='categorie', color_discrete_map=kleur_map,
                         labels={'categorie': '', 'percentage': tr('Percentage (%)', lang)},
                         title=label, category_orders={'categorie': volgorde})
        else:
            df2 = df2.dropna(subset=['_waarde'])
            counts = df2['_waarde'].value_counts(normalize=True).mul(100).reset_index()
            counts.columns = ['waarde', 'percentage']
            fig = px.bar(counts, x='waarde', y='percentage',
                         color_discrete_sequence=[HOOFD_KLEUR],
                         labels={'waarde': x_label, 'percentage': tr('Percentage (%)', lang)},
                         title=label)
        fig.update_layout(showlegend=False)

    # ── Pie ───────────────────────────────────────────────────────────────────
    elif plot_type == 'pie':
        if labels_map:
            s_int = pd.to_numeric(df2[kolom], errors='coerce')
            df2['_label'] = s_int.map(labels_map)
            df2 = df2.dropna(subset=['_label'])
            counts = df2['_label'].value_counts().reset_index()
            counts.columns = ['categorie', 'aantal']
            counts['categorie'] = counts['categorie'].map(lambda x: tr(x, lang))
            kleur_map = _kleur_voor_bar(
                {k: tr(v, lang) for k, v in labels_map.items() if tr(v, lang) in counts['categorie'].values},
                kleur_richting
            )
            fig = px.pie(counts, names='categorie', values='aantal',
                         title=label, color='categorie', color_discrete_map=kleur_map)
        else:
            df2 = df2.dropna(subset=['_waarde'])
            counts = df2['_waarde'].value_counts().reset_index()
            counts.columns = ['categorie', 'aantal']
            fig = px.pie(counts, names='categorie', values='aantal', title=label,
                         color_discrete_sequence=px.colors.qualitative.Set2)

    # ── Box ───────────────────────────────────────────────────────────────────
    elif plot_type == 'box':
        df2 = df2.dropna(subset=['_waarde'])
        split_by_gender = gender_ok and geslacht_filter == 'beide'
        if split_by_gender:
            df2 = df2.dropna(subset=['geslacht_label'])
            kleur_map = {gender_labels[k]: GENDER_COLORS[k] for k in gender_labels}
            fig = px.box(df2, x='geslacht_label', y='_waarde',
                         color='geslacht_label', color_discrete_map=kleur_map,
                         labels={'geslacht_label': tr('Geslacht', lang), '_waarde': x_label},
                         title=label, category_orders={'geslacht_label': [gender_labels[1], gender_labels[0]]})
            fig.update_layout(showlegend=False)
        else:
            fig = px.box(df2, y='_waarde', color_discrete_sequence=[HOOFD_KLEUR],
                         labels={'_waarde': x_label}, title=label)
    else:
        fig = go.Figure()

    return fig


# ── Platform groei ─────────────────────────────────────────────────────────────
def maak_platform_groei_plot(base_pad, participant_ids: list | set | pd.Series | None = None) -> go.Figure:
    """
    Toont nieuwe accounts en ingevulde vragenlijsten per jaar als gecombineerde grafiek.
    Aligned met account_activatie: "ingevuld" betekent "heeft scores in users_met_scores".
    """
    from pathlib import Path
    import pandas as pd

    base_pad = Path(base_pad)

    # Nieuwe accounts per jaar — zelfde definitie als accountactivatie
    df_users = _laad_actieve_users(base_pad, include_deleted=False)
    if participant_ids is not None:
        pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
        df_users['id_num'] = pd.to_numeric(df_users['id'], errors='coerce')
        df_users = df_users[df_users['id_num'].isin(pids)].copy()
    
    # Laad scores om actieve accounts te bepalen (consistent met account_activatie)
    df_scores_expanded = load_my_clic_participants_expanded(DB_URL)
    
    # Zorg dat participant_id kolom aanwezig is (dit is de juiste linkage!)
    if df_scores_expanded.empty:
        logger.warning("⚠️ df_scores_expanded is leeg - kan geen actieve accounts bepalen")
        actieve_ids = set()
    else: # Use participant_id for matching (this is the correct linkage!)
        df_scores_expanded = df_scores_expanded.drop_duplicates(subset='participant_id', keep='first')
        if 'latest_completion_at' in df_scores_expanded.columns:
            completed = df_scores_expanded[df_scores_expanded['latest_completion_at'].notna()]
            actieve_ids = set(pd.to_numeric(completed['participant_id'], errors='coerce').dropna().astype(int))
        else:
            actieve_ids = set(pd.to_numeric(df_scores_expanded['participant_id'], errors='coerce').dropna().astype(int))
    
    if 'id_num' not in df_users.columns:
        df_users['id_num'] = pd.to_numeric(df_users['id'], errors='coerce')
    df_users['jaar'] = pd.to_datetime(df_users['created_at'], errors='coerce').dt.year
    df_users['actief'] = df_users['id_num'].isin(actieve_ids)
    
    # Accounts per jaar (totaal en actief)
    accounts_per_jaar = (
        df_users[df_users['jaar'].between(2018, 2030)] # Filter years
        .groupby('jaar').size().reset_index(name='nieuwe_accounts')
    )

    # Actieve accounts per jaar (met ingevulde vragenlijst)
    actieve_per_jaar = (
        df_users[df_users['actief'] & df_users['jaar'].between(2018, 2030)] # Filter years
        .groupby('jaar').size().reset_index(name='ingevulde_vragenlijsten')
    )

    # Combineer
    df = accounts_per_jaar.merge(actieve_per_jaar, on='jaar', how='outer').sort_values('jaar')
    df['ingevulde_vragenlijsten'] = df['ingevulde_vragenlijsten'].fillna(0).astype(int)

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Bar(
        x=df['jaar'], y=df['nieuwe_accounts'],
        name='Nieuwe accounts',
        marker_color='#1F6FBF',
        opacity=0.85,
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=df['jaar'], y=df['ingevulde_vragenlijsten'],
        name='Ingevulde vragenlijsten',
        mode='lines+markers',
        line=dict(color='#E87722', width=2),
        marker=dict(size=8),
    ), secondary_y=True)

    fig.update_layout(
        title='Platformgroei: nieuwe accounts en ingevulde vragenlijsten per jaar',
        xaxis=dict(title='Jaar', tickmode='linear', dtick=1),
        yaxis=dict(title=dict(text='Nieuwe accounts', font=dict(color='#1F6FBF'))),
        yaxis2=dict(
            title=dict(text='Ingevulde vragenlijsten', font=dict(color='#E87722')),
            overlaying='y',
            side='right',
        ),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        barmode='group',
    )
    fig.add_annotation(
        text='Alleen niet-verwijderde accounts. Aligned met accountactivatie: "ingevuld" = heeft scores in users_met_scores',
        xref='paper', yref='paper', x=0.01, y=1.12,
        showarrow=False, font=dict(size=12, color='dimgray')
    )
    return fig


def maak_update_verificatie_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    """
    Toont de cumulatieve groei van het aantal deelnemers over de tijd.
    Dit is een goede manier om te verifiëren of een data-import effect heeft gehad.
    """
    if df is None or df.empty or 'created_at' not in df.columns:
        return _empty_store_plot(tr("Geen tijddata beschikbaar voor controle.", lang))
    
    df_plot = df.copy()
    df_plot['created_at'] = pd.to_datetime(df_plot['created_at'], errors='coerce')
    df_plot = df_plot.dropna(subset=['created_at']).sort_values('created_at')
    
    # Filter op reële data (vanaf 2019)
    df_plot = df_plot[df_plot['created_at'].dt.year >= 2019]
    
    if df_plot.empty:
        return _empty_store_plot(tr("Geen data na 2019 gevonden.", lang))

    # Telling per dag
    df_plot['datum'] = df_plot['created_at'].dt.date
    dag_counts = df_plot.groupby('datum').size().reset_index(name='n_nieuw')
    dag_counts['totaal_cumulatief'] = dag_counts['n_nieuw'].cumsum()

    fig = px.line(
        dag_counts, x='datum', y='totaal_cumulatief',
        title=tr('Verificatie: Totaal aantal deelnemers over tijd (Cumulatief)', lang),
        labels={'datum': tr('Datum', lang), 'totaal_cumulatief': tr('Totaal aantal deelnemers', lang)},
    )
    fig.update_traces(line_shape='hv', line_color='#2ECC71') # Step plot in groen
    
    # Markeer de laatste update datum
    laatste_datum = dag_counts['datum'].max()
    max_count = int(dag_counts['totaal_cumulatief'].max()) if not dag_counts.empty else 0
    fig.add_annotation(
        x=laatste_datum, y=dag_counts['totaal_cumulatief'].max(),
        text=f"{tr('Huidige stand', lang)}: {max_count:,}",
        showarrow=True, arrowhead=1
    )
    
    fig.update_layout(template='plotly_white', height=450)
    return fig


# ── Account activatie ──────────────────────────────────────────────────────────
def maak_account_activatie_plot(base_pad, participant_ids: list | set | pd.Series | None = None) -> go.Figure:
    """
    Toont per jaar:
    - Nieuwe accounts aangemaakt
    - Daarvan hebben vragenlijst ingevuld (actief)
    - Daarvan hebben GEEN vragenlijst ingevuld (inactief)
    """
    from pathlib import Path
    import pandas as pd

    base_pad = Path(base_pad)

    df_users  = _laad_actieve_users(base_pad, include_deleted=False)
    if participant_ids is not None:
        pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
        df_users['id_num'] = pd.to_numeric(df_users['id'], errors='coerce')
        df_users = df_users[df_users['id_num'].isin(pids)].copy()
    df_scores_expanded = load_my_clic_participants_expanded(DB_URL)
    
    # Use participant_id for matching (this is the correct linkage!)
    if 'participant_id' not in df_scores_expanded.columns:
        logger.warning("⚠️ participant_id kolom niet gevonden in df_scores_expanded")
        df_scores_expanded['participant_id'] = pd.NA
    
    df_scores_expanded = df_scores_expanded.drop_duplicates(subset='participant_id', keep='first')

    if 'latest_completion_at' in df_scores_expanded.columns:
        completed = df_scores_expanded[df_scores_expanded['latest_completion_at'].notna()]
        actieve_ids = set(pd.to_numeric(completed['participant_id'], errors='coerce').dropna().astype(int))
    else:
        actieve_ids = set(pd.to_numeric(df_scores_expanded['participant_id'], errors='coerce').dropna().astype(int))

    id_column = 'id' if 'id' in df_users.columns else 'participant_id' if 'participant_id' in df_users.columns else None
    if id_column is None:
        logger.warning("⚠️ Geen id-kolom gevonden in users/participants voor accountactivatie")
        id_column = 'id'
        df_users['id'] = pd.NA

    df_users['id_num'] = pd.to_numeric(df_users[id_column], errors='coerce')
    df_users['actief'] = df_users['id_num'].isin(actieve_ids)

    # Zorg dat jaar-kolom bestaat en filter op plausibele jaren
    df_users['jaar'] = pd.to_datetime(df_users.get('created_at'), errors='coerce').dt.year

    # Aggregeer per jaar (beperk tot realistische jaren)
    groep = (
        df_users[df_users['jaar'].between(2018, 2030)]
        .groupby('jaar')
        .agg(
            totaal=('id', 'count'),
            actief=('actief', 'sum'),
        )
        .reset_index()
    )
    groep['inactief'] = groep['totaal'] - groep['actief']
    groep['pct_actief'] = (groep['actief'] / groep['totaal'] * 100).round(1)

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=groep['jaar'], y=groep['actief'],
        name='Vragenlijst ingevuld',
        marker_color='#2ECC71',
    ))
    fig.add_trace(go.Bar(
        x=groep['jaar'], y=groep['inactief'],
        name='Geen vragenlijst ingevuld',
        marker_color='#E74C3C',
    ))
    fig.add_trace(go.Scatter(
        x=groep['jaar'], y=groep['pct_actief'],
        name='Activatiegraad (%)',
        mode='lines+markers',
        line=dict(color='#1F6FBF', width=2, dash='dot'),
        marker=dict(size=8),
        yaxis='y2',
    ))

    fig.update_layout(
        title='Accountactivatie per jaar',
        xaxis=dict(title='Jaar', tickmode='linear', dtick=1),
        yaxis=dict(title='Aantal accounts'),
        yaxis2=dict(
            title=dict(text='Activatiegraad (%)', font=dict(color='#1F6FBF')),
            overlaying='y',
            side='right',
            range=[0, 100],
        ),
        barmode='stack',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )
    fig.add_annotation(
        text='Actief = minstens 1 ingevulde vragenlijst met scoredata',
        xref='paper', yref='paper', x=0.01, y=1.12,
        showarrow=False, font=dict(size=12, color='dimgray')
    )
    return fig, groep


# ── Vragenlijst invulpercentage ────────────────────────────────────────────────
def maak_vragenlijst_plot(base_pad, db_url: str, participant_ids: list | set | pd.Series | None = None):
    """
    Toont per vragenlijst:
    - Wanneer deze voor het eerst werd ingevuld
    - Hoeveel unieke deelnemers hem hebben ingevuld
    - Invulpercentage ten opzichte van totaal aantal deelnemers
    """
    import json
    import pandas as pd
    from pathlib import Path
    base_pad = Path(base_pad)

    # Alleen de in deze visualisatie bekende vragenlijsten tonen.
    # De database kan extra technische/legacy records bevatten, die we hier bewust uitsluiten.
    known_questionnaire_ids = {1, 2, 3, 4, 5, 6, 7, 8}
    naam_map = {
        1: 'Smart Health Test',
        2: 'Smart Work Test',
        3: 'Resilience',
        4: 'Well-being',
        5: 'Positive Health',
        6: 'Self-efficacy',
        7: 'Negative emotions',
        8: 'Smartphone and stress',
    }
    # Dynamisch ophalen van vragenlijstnamen, maar alleen voor de bekende IDs uit deze visualisatie.
    naam_map = {q_id: naam for q_id, naam in naam_map.items() if q_id in known_questionnaire_ids}
    try:
        from sqlalchemy import create_engine
        engine = create_engine(db_url or DB_URL)
        df_q = pd.read_sql("SELECT id, internal_name, name::text AS name, slug FROM questionnaires", engine)
        for _, row in df_q.iterrows():
            q_id = int(row['id'])
            if q_id not in known_questionnaire_ids:
                continue
            name = row.get('internal_name') or row.get('name') or row.get('slug')

            # Filter "bloeddruk" en technische records die geen echte vragenlijst zijn
            if name:
                name_low = str(name).lower()
                if any(x in name_low for x in ['bloeddruk', 'blood_pressure', 'bloodpressure', 'test_']):
                    continue
                naam_map[q_id] = str(name)
    except Exception as e:
        logger.warning(f"Kon vragenlijstnamen niet uit DB laden: {e}")
        naam_map = {
            1: 'Smart Health Test', 2: 'Smart Work Test', 3: 'Resilience',
            4: 'Well-being', 5: 'Positive Health', 6: 'Self-efficacy',
            7: 'Negative emotions', 8: 'Smartphone and stress'
        }

    # Completions laden
    df_comp = load_completions(db_url or DB_URL)
    if participant_ids is not None:
        pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
        df_comp = df_comp[pd.to_numeric(df_comp['participant_id'], errors='coerce').isin(pids)]

    df_comp['created_at'] = pd.to_datetime(df_comp['created_at'], errors='coerce')
    n_totaal = int(df_comp['participant_id'].nunique())

    # Totaal unieke deelnemers
    # Filter completions: gebruik alleen echte vragenlijsten (geen bloeddruk etc)
    df_comp['questionnaire_id'] = pd.to_numeric(df_comp['questionnaire_id'], errors='coerce')
    df_comp = df_comp[df_comp['questionnaire_id'].isin(naam_map.keys())].copy()

    # Per vragenlijst aggregeren
    agg = df_comp.groupby('questionnaire_id').agg(
        eerste_invulling=('created_at', 'min'),
        laatste_invulling=('created_at', 'max'),
        n_ingevuld=('participant_id', 'nunique'),
    ).reset_index()

    # Voeg questionnaire naam toe
    agg['naam'] = agg['questionnaire_id'].map(naam_map)
    
    # Filter out legacy/unknown questionnaires (those without entries in naam_map)
    agg = agg[agg['naam'].notna()].copy()
    # Filter records zonder naam
    agg = agg.dropna(subset=['naam']).copy()
    
    deelnemers_per_vragenlijst = []
    for _, row in agg.iterrows():
        eerste_invulling = row['eerste_invulling']
        n_eligible = df_comp.loc[df_comp['created_at'] >= eerste_invulling, 'participant_id'].nunique()
        deelnemers_per_vragenlijst.append(n_eligible)
    agg['n_eligible'] = deelnemers_per_vragenlijst
    agg['pct'] = (agg['n_ingevuld'] / agg['n_eligible'] * 100).round(1)
    agg['eerste_jaar'] = agg['eerste_invulling'].dt.year

    # Sorteer op percentage
    agg = agg.sort_values('pct', ascending=True).reset_index(drop=True)

    # Kleur op basis van invulpercentage - nu met zwart voor >=50%
    from kleuren import VRAGENLIJST_COLORS
    kleuren = [
        VRAGENLIJST_COLORS[0] if p >= 50 else
        VRAGENLIJST_COLORS[1] if p >= 20 else
        VRAGENLIJST_COLORS[2]
        for p in agg['pct']
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=agg['pct'],
        y=agg['naam'],
        orientation='h',
        marker_color=kleuren,
        text=agg.apply(lambda r: f"{int(r['n_ingevuld']):,}/{int(r['n_eligible']):,} ({r['pct']}%) — sinds {r['eerste_jaar']:.0f}", axis=1),
        textposition='outside',
        hovertemplate=(
            '<b>%{y}</b><br>'
            'Bereik sinds eerste invulling: %{x:.1f}%<br>'
            'Deelnemers: %{customdata[2]}<br>'
            'Eligible deelnemers: %{customdata[3]}<br>'
            'Eerste: %{customdata[0]}<br>'
            'Laatste: %{customdata[1]}<extra></extra>'
        ),
        customdata=agg[['eerste_invulling', 'laatste_invulling', 'n_ingevuld', 'n_eligible']].values,
    ))

    fig.update_layout(
        title=f'Questionnaire Completion Percentage (total: {n_totaal:,} participants)',
        xaxis=dict(title='Completion percentage (%)', range=[0, 115]),
        yaxis=dict(title=''),
        height=max(400, len(agg) * 28),
        margin=dict(l=200, r=150),
        showlegend=False,
    )
    fig.add_vline(x=50, line_dash='dash', line_color='black',
                  annotation_text='50%', annotation_font_color='black')

    return fig, agg


# ── Kopers vs niet-kopers ──────────────────────────────────────────────────────
def maak_kopers_vergelijking_plot(base_pad: Path, db_url: str, participant_ids: list | set | pd.Series | None = None) -> tuple:
    """
    Vergelijkt gemiddelde scores van kopers vs niet-kopers.
    
    NOTE: This requires that order data can be mapped to participant IDs.
    If the mapping is not available (e.g., separate user systems), returns an empty figure.
    """
    # Gebruik de centrale koppelfunctie uit data_ingestion om aankoopdata te laden
    df_koppeling = get_user_purchases(base_pad, db_url)
    
    if df_koppeling.empty:
        # Empty figure with message
        fig = go.Figure()
        fig.add_annotation(
            text="Geen aankoopgegevens beschikbaar",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False, font=dict(size=14)
        )
        return fig, pd.DataFrame(columns=['Product', 'Aantal orders']), 0
    
    if participant_ids is not None:
        pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
        if 'participant_id' in df_koppeling.columns:
            df_koppeling = df_koppeling[pd.to_numeric(df_koppeling['participant_id'], errors='coerce').isin(pids)]

    # Filter for successful purchases
    if 'status' in df_koppeling.columns:
        success_statuses = {'completed', 'paid', 'success', 'shipped', 'delivered', 'voltooid', 'betaald'}
        df_koppeling = df_koppeling[df_koppeling['status'].astype(str).str.lower().isin(success_statuses)].copy()

    # Scores laden (gebruik de geconsolideerde data)
    df_scores_expanded = load_my_clic_participants_expanded(db_url or DB_URL)
    df_scores_expanded['participant_id'] = pd.to_numeric(df_scores_expanded['participant_id'], errors='coerce')
    if participant_ids is not None:
        pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
        df_scores_expanded = df_scores_expanded[df_scores_expanded['participant_id'].isin(pids)]
    df_scores_expanded = df_scores_expanded.drop_duplicates(subset='participant_id', keep='first')

    # Bepaal kopers op basis van participant_id of user_id, zodat koppeling ook werkt
    # wanneer de order- en scorebronnen verschillende identifieringsystemen gebruiken.
    kopers_participant = set(pd.to_numeric(df_koppeling.get('participant_id'), errors='coerce').dropna().astype(int))
    kopers_user = set(pd.to_numeric(df_koppeling.get('user_id'), errors='coerce').dropna().astype(int))

    if not kopers_participant and not kopers_user:
        # No valid participant mapping - cannot determine buyers
        fig = go.Figure()
        fig.add_annotation(
            text="Kan aankoopgegevens niet koppelen aan deelnemersgegevens.<br>De systemen gebruiken verschillende user-ID bereiken.",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False, font=dict(size=12)
        )
        return fig, pd.DataFrame(columns=['Product', 'Aantal orders']), 0

    def _is_koper(row):
        pid = pd.to_numeric(row.get('participant_id'), errors='coerce')
        uid = pd.to_numeric(row.get('user_id'), errors='coerce')
        if pd.notna(pid) and int(pid) in kopers_participant:
            return True
        if pd.notna(uid) and int(uid) in kopers_user:
            return True
        return False

    df_scores_expanded['groep'] = df_scores_expanded.apply(_is_koper, axis=1).map(
        {True: 'Heeft product gekocht', False: 'Geen product gekocht'}
    )
    n_kopers = int(df_scores_expanded['groep'].eq('Heeft product gekocht').sum())

    # Indicatoren
    indicatoren = {
        'Leefstijlscore':  'rec_ls_lifestyle_score',
        'BMI':             'rec_med_bmi',
        'Stress':          'rec_ls_stress_sum',
        'Heartrisk score': 'rec_heartrisk',
        'Slaap (PSQI)':    'rec_ls_sleep_psqi_sum',
        'Veerkracht':      'rec_resilience_score',
    }

    # Lager is beter voor deze indicatoren
    lager_beter = {'BMI', 'Stress', 'Heartrisk score', 'Slaap (PSQI)'}

    rijen = []
    for label, kolom in indicatoren.items():
        if kolom not in df_scores_expanded.columns:
            continue
        s = pd.to_numeric(df_scores_expanded[kolom], errors='coerce')
        df_scores_expanded['_s'] = s
        for groep in ['Heeft product gekocht', 'Geen product gekocht']: # type: ignore
            gem = df_scores_expanded[df_scores_expanded['groep'] == groep]['_s'].mean()
            n   = df_scores_expanded[df_scores_expanded['groep'] == groep]['_s'].notna().sum()
            rijen.append({'Indicator': label, 'Groep': groep,
                          'Gemiddelde': round(gem, 2), 'N': n})

    df_plot = pd.DataFrame(rijen)

    # Normaliseer naar 0-100 schaal per indicator voor vergelijkbaarheid
    genorm = []
    for ind in df_plot['Indicator'].unique():
        sub = df_plot[df_plot['Indicator'] == ind].copy()
        min_v = sub['Gemiddelde'].min()
        max_v = sub['Gemiddelde'].max()
        bereik = max_v - min_v if max_v != min_v else 1
        sub['Verschil_%'] = ((sub['Gemiddelde'] - min_v) / bereik * 100).round(1)
        if ind in lager_beter:
            sub['Verschil_%'] = 100 - sub['Verschil_%']
        genorm.append(sub)
    df_plot = pd.concat(genorm)

    volgorde = ['Heeft product gekocht', 'Geen product gekocht']
    kleur_map = {
        'Heeft product gekocht': '#2ECC71',
        'Geen product gekocht': '#95A5A6',
    }
    indicator_volgorde = list(indicatoren.keys())

    fig = go.Figure()
    for groep in [g for g in volgorde if g in df_plot['Groep'].unique()]:
        sub = df_plot[df_plot['Groep'] == groep].copy()
        sub['Indicator'] = pd.Categorical(sub['Indicator'], categories=indicator_volgorde, ordered=True)
        sub = sub.sort_values('Indicator')
        fig.add_bar(
            name=groep,
            x=sub['Indicator'].astype(str),
            y=sub['Gemiddelde'],
            marker_color=kleur_map[groep],
            text=[f"{v:.2f}" for v in sub['Gemiddelde']],
            textposition='outside',
            offsetgroup=groep,
        )

    fig.update_layout(
        title='Gemiddelde scores: kopers vs niet-kopers',
        xaxis_title='',
        yaxis_title='Gemiddelde score',
        barmode='group', # type: ignore
        legend_title_text='',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1), # type: ignore
    )

    # Producten top 10
    top_producten = df_koppeling['name'].value_counts().head(10).reset_index()
    top_producten = df_koppeling['name'].str.strip().value_counts().head(10).reset_index()
    top_producten.columns = ['Product', 'Aantal orders']

    return fig, top_producten, n_kopers


# ── Inactieve accounts analyse ────────────────────────────────────────────────
def maak_inactieve_accounts_plot(base_pad) -> tuple:
    """
    Analyseert inactieve accounts: aanmaakjaar, domeinen, kenmerken.
    """
    from pathlib import Path
    import pandas as pd

    base_pad = Path(base_pad)
    df_users  = _laad_actieve_users(base_pad, include_deleted=False)
    df_scores_expanded = load_my_clic_participants_expanded(DB_URL)
    # Ensure user_id column exists
    if 'user_id' not in df_scores_expanded.columns:
        df_scores_expanded = df_scores_expanded.rename(columns={'pmo_id': 'user_id'})
    df_scores_expanded = df_scores_expanded.drop_duplicates(subset='user_id', keep='first')

    for col in [ # type: ignore
        'completed_onboarding_at',
        'accepted_terms_at',
        'accepted_medical_data_processing_terms_at',
        'accepted_automated_data_processing_terms_at',
        'subscribed_to_service_mails_at',
        'subscribed_to_newsletter_at',
        'phone_number',
    ]:
        if col not in df_users.columns:
            df_users[col] = pd.NA

    # Gebruik robuuste numerieke conversie voor ID matching
    actieve_ids = set(pd.to_numeric(df_scores_expanded['user_id'], errors='coerce').dropna().astype(int))
    df_users_actief = df_users.copy()
    df_users_actief['actief'] = df_users_actief['id'].isin(actieve_ids)
    df_users_actief['id_num'] = pd.to_numeric(df_users_actief['id'], errors='coerce')
    df_users_actief['actief'] = df_users_actief['id_num'].isin(actieve_ids)
    df_users_actief = df_users_actief.dropna(subset=['id_num'])

    df_inactief = df_users_actief[~df_users_actief['actief']]
    df_actief   = df_users_actief[df_users_actief['actief']]

    # Plot 1: Aanmaakjaar verdeling actief vs inactief
    jaren = sorted(df_users_actief['jaar'].dropna().unique().astype(int))
    df_jaar = pd.DataFrame({
        'jaar':     jaren,
        'actief':   [int(df_actief['jaar'].eq(j).sum()) for j in jaren],
        'inactief': [int(df_inactief['jaar'].eq(j).sum()) for j in jaren],
    })

    fig_jaar = go.Figure()
    fig_jaar.add_trace(go.Bar(
        x=df_jaar['jaar'], y=df_jaar['actief'],
        name='Vragenlijst ingevuld',
        marker_color='#2ECC71',
    ))
    fig_jaar.add_trace(go.Bar(
        x=df_jaar['jaar'], y=df_jaar['inactief'],
        name='Nooit vragenlijst ingevuld',
        marker_color='#E74C3C',
    ))
    fig_jaar.update_layout(
        title='Accounts per aanmaakjaar: actief vs inactief',
        xaxis=dict(title='Aanmaakjaar', tickmode='linear', dtick=1),
        yaxis=dict(title='Aantal accounts'),
        barmode='stack',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
    )

    # Samenvatting
    samenvatting = {
        'Totaal inactieve accounts': len(df_inactief),
        'Piek aanmaakjaar':          int(df_inactief['jaar'].mode().iloc[0]) if len(df_inactief) > 0 else None,
        'Gemiddeld jaar':            round(df_inactief['jaar'].mean(), 0),
        'Activatiegraad totaal (%)': round(len(df_actief) / len(df_users_actief) * 100, 1),
        'Onboarding afgerond (%)':   round(df_inactief['completed_onboarding_at'].notna().mean() * 100, 1),
        'Voorwaarden geaccepteerd (%)': round(df_inactief['accepted_terms_at'].notna().mean() * 100, 1),
        'Service mails aan (%)':     round(df_inactief['subscribed_to_service_mails_at'].notna().mean() * 100, 1),
        'Telefoonnummer bekend (%)': round(df_inactief['phone_number'].notna().mean() * 100, 1),
    }

    kenmerken = pd.DataFrame([
        {'Kenmerk': 'Onboarding afgerond', 'Aantal': int(df_inactief['completed_onboarding_at'].notna().sum())},
        {'Kenmerk': 'Voorwaarden geaccepteerd', 'Aantal': int(df_inactief['accepted_terms_at'].notna().sum())},
        {'Kenmerk': 'Medische toestemming', 'Aantal': int(df_inactief['accepted_medical_data_processing_terms_at'].notna().sum())},
        {'Kenmerk': 'Geautomatiseerde verwerking akkoord', 'Aantal': int(df_inactief['accepted_automated_data_processing_terms_at'].notna().sum())},
        {'Kenmerk': 'Service mails aan', 'Aantal': int(df_inactief['subscribed_to_service_mails_at'].notna().sum())},
        {'Kenmerk': 'Nieuwsbrief aan', 'Aantal': int(df_inactief['subscribed_to_newsletter_at'].notna().sum())},
        {'Kenmerk': 'Telefoonnummer bekend', 'Aantal': int(df_inactief['phone_number'].notna().sum())},
    ])
    kenmerken['Percentage (%)'] = (kenmerken['Aantal'] / max(len(df_inactief), 1) * 100).round(1)

    return fig_jaar, samenvatting, kenmerken


def maak_artikel_interacties_overzicht(base_pad, user_ids: list | set | pd.Series | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Koppel content views aan gebruikers en artikeltitels.
    Haalt data uit database via 'interactions' tabel i.p.v. CSV bestanden.
    """
    base_pad = Path(base_pad)

    # Initialiseer lege dataframes. Data wordt direct uit de PostgreSQL database geladen.
    df_inter = pd.DataFrame()
    df_content_nl = pd.DataFrame()
    df_users = pd.DataFrame()
    empty_top_artikelen = pd.DataFrame(columns=['interactable_id', 'title', 'Views', 'Unieke_lezers', 'Laatste_view'])
    
    def _normalize_locale(series: pd.Series) -> pd.Series:
        return (
            series.astype(str)
            .str.strip()
            .str.lower()
            .str.replace('-', '_', regex=False)
            .fillna('')
        )

    try:
        from config import DB_URL
        if not DB_URL:
            raise ValueError("Geen database URL beschikbaar")
        
        engine = create_engine(DB_URL)
        
        # Laad data uit database tabellen
        try:
            df_inter_raw = pd.read_sql(
                "SELECT id, interactable_type, interactable_id, user_id, type, created_at, updated_at FROM interactions",
                engine
            )
        except Exception as e:
            logger.warning(f"Kon interactions niet laden met expliciete kolommen: {e}. Val terug op SELECT *")
            df_inter_raw = pd.read_sql("SELECT * FROM interactions", engine)

        if set(['id', 'interactable_type', 'interactable_id', 'user_id', 'type', 'created_at', 'updated_at']).issubset(df_inter_raw.columns):
            df_inter = df_inter_raw[['id', 'interactable_type', 'interactable_id', 'user_id', 'type', 'created_at', 'updated_at']].copy()
        elif len(df_inter_raw.columns) >= 7:
            df_inter = df_inter_raw.iloc[:, :7].copy()
            df_inter.columns = ['id', 'interactable_type', 'interactable_id', 'user_id', 'type', 'created_at', 'updated_at']
        else:
            logger.warning(f"Interactions tabel heeft slechts {len(df_inter_raw.columns)} kolommen (verwacht 7+)")
            df_inter = pd.DataFrame()

        if not df_inter.empty:
            df_inter = df_inter[
                (df_inter['interactable_type'].astype(str).str.strip() == 'content') &
                (df_inter['type'].astype(str).str.strip() == 'view')
            ].copy()
            logger.info(f"✓ Interactions geladen: {len(df_inter)} content views")
        
        try:
            df_content_nl_raw = pd.read_sql(
                "SELECT content_id, locale, title FROM content_translations",
                engine
            )
        except Exception as e:
            logger.warning(f"Kon content_translations niet laden met expliciete kolommen: {e}. Val terug op SELECT *")
            df_content_nl_raw = pd.read_sql("SELECT * FROM content_translations", engine)

        if set(['content_id', 'locale', 'title']).issubset(df_content_nl_raw.columns):
            df_content_nl = df_content_nl_raw[['content_id', 'locale', 'title']].copy()
        elif set(['id', 'public_id', 'content_id', 'locale', 'title']).issubset(df_content_nl_raw.columns):
            df_content_nl = df_content_nl_raw[['content_id', 'locale', 'title']].copy()
        elif len(df_content_nl_raw.columns) >= 5:
            df_content_nl = df_content_nl_raw.iloc[:, [2, 3, 4]].copy()
            df_content_nl.columns = ['content_id', 'locale', 'title']
        else:
            logger.warning(f"Content_translations tabel heeft slechts {len(df_content_nl_raw.columns)} kolommen")
            df_content_nl = pd.DataFrame(columns=['content_id', 'locale', 'title'])

        if not df_content_nl.empty:
            df_content_nl['locale'] = _normalize_locale(df_content_nl['locale'])
            df_content_nl = df_content_nl[df_content_nl['locale'].str.startswith('nl')].drop_duplicates('content_id')
            logger.info(f"✓ Content translations geladen: {len(df_content_nl)} records (nl locale)")
        else:
            logger.warning("Geen content translations gevonden in content_translations tabel")

        if df_content_nl.empty:
            try:
                df_content_fallback = pd.read_sql("SELECT id, title FROM content", engine)
                if {'id', 'title'}.issubset(df_content_fallback.columns):
                    df_content_nl = df_content_fallback.rename(columns={'id': 'content_id'})[['content_id', 'title']]
                    logger.info(f"✓ Fallback content geladen: {len(df_content_nl)} records")
            except Exception as e:
                logger.warning(f"Kon fallback content niet laden: {e}")

        # Check if users load successfully
        try:
            df_users = pd.read_sql("SELECT id, email, deleted_at FROM users", engine)
            logger.info(f"✓ Users geladen: {len(df_users)} records")
        except Exception as e:
            logger.warning(f"Kon deleted_at niet laden uit users ({e}), val terug op id/email")
            try:
                df_users = pd.read_sql("SELECT id, email FROM users", engine)
                logger.info(f"✓ Users geladen zonder deleted_at: {len(df_users)} records")
            except Exception as e2:
                logger.warning(f"Kon users niet laden: {e2}")
                df_users = pd.DataFrame(columns=['id', 'email', 'deleted_at'])

        for col in ['id', 'email', 'deleted_at']:
            if col not in df_users.columns:
                df_users[col] = pd.NA

        if df_inter.empty:
            logger.warning("Geen interactions gevonden in database")
            return pd.DataFrame(), pd.DataFrame(), {
                'Totaal views': 0, 'Unieke lezers': 0, 'Unieke artikelen': 0,
                'Lezers met actief account': 0, 'Gefilterde interne accounts': 0,
            }

    except Exception as e:
        logger.warning(f"Kan artikel interacties niet uit database laden: {e}. Retourneer lege dataset.")
        return pd.DataFrame(), pd.DataFrame(), {
            'Totaal views': 0, 'Unieke lezers': 0, 'Unieke artikelen': 0,
            'Lezers met actief account': 0, 'Gefilterde interne accounts': 0,
        }
    
    empty_top_artikelen = pd.DataFrame(columns=['interactable_id', 'title', 'Views', 'Unieke_lezers', 'Laatste_view'])

    df_inter['user_id'] = pd.to_numeric(df_inter['user_id'], errors='coerce')
    if user_ids is not None:
        uids = set(pd.to_numeric(pd.Series(list(user_ids)), errors='coerce').dropna().astype(int))
        if uids:
            df_candidate = df_inter[df_inter['user_id'].isin(uids)].copy()
            mapped_uids = set()
            try:
                bridge = _laad_participant_user_bridge(DB_URL)
                if not bridge.empty and 'participant_id' in bridge.columns and 'user_id' in bridge.columns:
                    mapped_uids = set(
                        pd.to_numeric(
                            bridge.loc[bridge['participant_id'].isin(uids), 'user_id'],
                            errors='coerce'
                        ).dropna().astype(int)
                    )
            except Exception as e:
                logger.warning(f"Kon participant-user bridge niet gebruiken voor artikelfiltering: {e}")

            if mapped_uids:
                combined_uids = uids | mapped_uids
                df_inter = df_inter[df_inter['user_id'].isin(combined_uids)].copy()
            else:
                df_inter = df_candidate
    if df_inter.empty:
        return empty_top_artikelen, pd.DataFrame(), {
            'Totaal views': 0, 'Unieke lezers': 0, 'Unieke artikelen': 0,
            'Lezers met actief account': 0, 'Gefilterde interne accounts': 0,
        }
    df_inter['interactable_id'] = pd.to_numeric(df_inter['interactable_id'], errors='coerce')
    df_inter['created_at'] = pd.to_datetime(df_inter['created_at'], errors='coerce')

    
    # Load content table to map interactable_id to public_id (content_id)
    try:
        df_content_raw = pd.read_sql("SELECT * FROM content", engine)
        if len(df_content_raw.columns) >= 2:
            # Extract: id and public_id columns
            df_content = df_content_raw.iloc[:, [0, 1]].copy()
            df_content.columns = ['id', 'public_id']
            df_content['id'] = pd.to_numeric(df_content['id'], errors='coerce')
            df_content['public_id'] = pd.to_numeric(df_content['public_id'], errors='coerce')
            logger.info(f"✓ Content geladen: {len(df_content)} records")
        else:
            logger.warning("Content tabel heeft niet genoeg kolommen")
            df_content = pd.DataFrame(columns=['id', 'public_id'])
    except Exception as e:
        logger.warning(f"Kon content niet laden: {e}")
        df_content = pd.DataFrame(columns=['id', 'public_id'])
    
    df_content_nl['content_id'] = pd.to_numeric(df_content_nl['content_id'], errors='coerce')
    df_content_nl = (
        df_content_nl[df_content_nl['locale'].str.startswith('nl')][['content_id', 'title']]
        .drop_duplicates('content_id')
    )

    df_content_nl = df_content_nl.drop_duplicates('content_id')
    
    # Join: interactions -> content_translations. In deze export verwijst
    # interactable_id direct naar content_translations.content_id; content.public_id
    # is niet dezelfde sleutel.
    df_views = (
        df_inter
        .merge(df_users, left_on='user_id', right_on='id', how='left')
        .merge(df_content_nl, left_on='interactable_id', right_on='content_id', how='left') # type: ignore
    )
    
    df_views['title'] = df_views['title'].fillna('Onbekend artikel')

    # Account status bepalen indien deleted_at beschikbaar is in de database
    if 'deleted_at' in df_views.columns:
        df_views['account_status'] = df_views['deleted_at'].isna().map({True: 'Actief account', False: 'Verwijderd account'})
    else:
        df_views['account_status'] = 'Onbekend'

    df_views['email_norm'] = df_views['email'].astype(str).str.strip().str.lower()
    df_views['email_localpart'] = df_views['email_norm'].str.split('@').str[0]

    # Filter interne accounts via een correcte boolean mask
    internal_mask = (
        df_views['email_norm'].str.endswith('@smarthealth.works', na=False) |
        df_views['email_norm'].str.endswith('@smarthealth.nl', na=False)
    )
    smarthealth_localparts = set(df_views.loc[internal_mask, 'email_localpart'].dropna())
    df_views = df_views[~df_views['email_localpart'].isin(smarthealth_localparts)].copy()

    if 'user_id' not in df_views.columns:
        df_views['user_id'] = pd.NA

    if df_views.empty:
        return empty_top_artikelen, pd.DataFrame(), {
            'Totaal views': 0, 'Unieke lezers': 0, 'Unieke artikelen': 0,
            'Lezers met actief account': 0, 'Gefilterde interne accounts': int(len(smarthealth_localparts)),
        }
    
    top_artikelen = (
        df_views.groupby(['interactable_id', 'title'], dropna=False)
        .agg(
            Views=('interactable_id', 'count'),
            Unieke_lezers=('user_id', 'nunique'),
            Laatste_view=('created_at', 'max'),
        )
        .reset_index()
        .sort_values(['Unieke_lezers', 'Views'], ascending=False)
        .head(20)
    )

    samenvatting = {
        'Totaal views': int(len(df_views)),
        'Unieke lezers': int(df_views['user_id'].nunique()),
        'Unieke artikelen': int(df_views['interactable_id'].nunique()),
        'Lezers met actief account': (
            int(df_views.loc[df_views['deleted_at'].isna(), 'user_id'].nunique()) 
            if 'deleted_at' in df_views.columns else int(df_views['user_id'].nunique())
        ),
        'Gefilterde interne accounts': int(len(smarthealth_localparts)),
    }
    return top_artikelen, df_views, samenvatting


# ── Scores per opdrachtgever ───────────────────────────────────────────────────
def maak_scores_per_opdrachtgever(base_pad, db_url: str,
                                   indicator: str = 'rec_ls_lifestyle_score',
                                   indicator_label: str = 'Leefstijlscore',
                                   min_n: int = 1,
                                   participant_ids: list | set | pd.Series | None = None) -> tuple:
    """
    Vergelijkt gemiddelde scores per opdrachtgever (store).
    Alleen stores met minimaal min_n deelnemers worden getoond.
    """
    from pathlib import Path
    import pandas as pd
    base_pad = Path(base_pad)

    # Scores laden
    df_expanded = load_my_clic_participants_expanded(db_url or DB_URL)
    if df_expanded.empty or 'participant_id' not in df_expanded.columns:
        return _empty_store_plot("Geen data beschikbaar voor deze selectie."), 0, 0

    if participant_ids is not None:
        pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
        df_expanded = df_expanded[pd.to_numeric(df_expanded['participant_id'], errors='coerce').isin(pids)]
        if df_expanded.empty:
            return _empty_store_plot("Geen data beschikbaar voor deze selectie."), 0, 0

    links = _laad_opdrachtgever_links(db_url or DB_URL)
    if links.empty:
        return _empty_store_plot("Geen opdrachtgeverkoppeling beschikbaar."), 0, 0

    df_expanded['participant_id'] = pd.to_numeric(df_expanded['participant_id'], errors='coerce')
    df_expanded = df_expanded.drop_duplicates(subset='participant_id', keep='first')
    df_expanded = df_expanded.drop(columns=[c for c in ['store_id', 'store_naam', 'store_name'] if c in df_expanded.columns])
    df_expanded = df_expanded.merge(
        links[['participant_id', 'store_id', 'store_name']],
        on='participant_id',
        how='inner',
    )


    if indicator in df_expanded.columns:
        df_expanded['score'] = pd.to_numeric(df_expanded[indicator], errors='coerce')
    else:
        df_expanded['score'] = pd.NA
    df_expanded['store_naam'] = df_expanded['store_name']

    # Aggregeer per store
    # n_deelnemers = totaal aantal deelnemers per store (ook zonder score) # type: ignore
    # n_met_score  = aantal deelnemers met een ingevulde score (noemer voor gemiddelde) # type: ignore
    agg = (df_expanded.groupby(['store_id', 'store_naam'])
           .agg(
               gemiddelde=('score', 'mean'),
               n_met_score=('score', 'count'),
               n_deelnemers=('participant_id', 'nunique'),
           )
           .reset_index())
    
    # Filter pas na aggregatie en drop pas dan NaNs
    agg = agg.dropna(subset=['gemiddelde'])

    # Filter op deelnemers met score; anders kan één ingevulde score binnen
    # een grote opdrachtgever ten onrechte als representatief gemiddelde tellen.
    if not agg.empty:
        agg['gemiddelde'] = pd.to_numeric(agg['gemiddelde'], errors='coerce').round(2)
        agg = agg[agg['n_met_score'] >= min_n].sort_values('gemiddelde', ascending=True)

    if agg.empty:
        return _empty_store_plot("Geen data beschikbaar voor deze selectie."), 0, 0

    # Gebruik een gewogen totaalgemiddelde zodat grote stores zwaarder meetellen
    # dan kleine stores in de referentielijn.
    totaal_gem = _weighted_average(agg['gemiddelde'], agg['n_met_score'])
    if pd.isna(totaal_gem): totaal_gem = 0

    categorie_config = SCORE_CATEGORIEEN.get(indicator)
    if categorie_config:
        agg['categorie'] = pd.cut(
            agg['gemiddelde'],
            bins=categorie_config['bins'],
            labels=categorie_config['labels'],
            include_lowest=True,
        ).astype('object')
        kleuren = agg['categorie'].map(categorie_config['kleuren']).fillna('#95A5A6')
        categorie_toelichting = categorie_config['toelichting']
    else:
        agg['categorie'] = 'Geen categorie'
        kleuren = pd.Series('#95A5A6', index=agg.index)
        categorie_toelichting = 'Geen bestaande categoriegrenzen voor deze score.'

    fig = go.Figure(go.Bar(
        x=agg['gemiddelde'],
        y=agg['store_naam'],
        orientation='h',
        marker_color=kleuren,
        text=agg.apply(
            lambda r: (
                f"{r['gemiddelde']:.2f} — {r['categorie']} "
                f"({r['n_met_score']}/{r['n_deelnemers']} deeln.)"
            ),
            axis=1,
        ),
        textposition='outside',
    ))

    fig.add_vline(
        x=totaal_gem, line_dash='dash', line_color='black',
        annotation_text=f'Gemiddeld ({totaal_gem:.2f})',
        annotation_position='top',
    )

    fig.update_layout(
        title=f'{indicator_label} per opdrachtgever',
        xaxis_title=indicator_label,
        yaxis_title='',
        height=max(400, len(agg) * 30),
        margin=dict(l=200, r=150),
        showlegend=False,
        meta={'categorie_toelichting': categorie_toelichting},
    )
    return fig, totaal_gem, len(agg)


# ══════════════════════════════════════════════════════════════════════════════
# MEERDERE VRAGENLIJSTEN INVULLERS
# ══════════════════════════════════════════════════════════════════════════════
def maak_meerdere_vragenlijsten_plot(base_pad: Path, participant_ids: list | set | pd.Series | None = None) -> tuple:
    """
    Analyseert wie meerdere vragenlijsten invullen.
    Geeft een plot van de verdeling + een profielanalyse terug.
    """
    base_pad = Path(base_pad)

    known_questionnaire_ids = {1, 2, 3, 4, 5, 6, 7, 8}
    naam_map = {
        1: 'Smart Health Test',
        2: 'Smart Work Test',
        3: 'Resilience',
        4: 'Well-being',
        5: 'Positive Health',
        6: 'Self-efficacy',
        7: 'Negative emotions',
        8: 'Smartphone and stress',
    }
    naam_map = {q_id: naam for q_id, naam in naam_map.items() if q_id in known_questionnaire_ids}
    # Dynamische naam mapping met filter
    try:
        from sqlalchemy import create_engine
        engine = create_engine(DB_URL)
        df_q = pd.read_sql("SELECT id, internal_name, name::text AS name, slug FROM questionnaires", engine)
        for _, row in df_q.iterrows():
            q_id = int(row['id'])
            if q_id not in known_questionnaire_ids:
                continue
            name = row.get('internal_name') or row.get('name') or row.get('slug')
            if name:
                name_low = str(name).lower()
                if not any(x in name_low for x in ['bloeddruk', 'blood_pressure', 'bloodpressure', 'test_']):
                    naam_map[q_id] = str(name)
    except:
        naam_map = {
            1: 'Smart Health Test', 2: 'Smart Work Test', 3: 'Resilience',
            4: 'Well-being', 5: 'Positive Health', 6: 'Self-efficacy',
            7: 'Negative emotions', 8: 'Smartphone and stress'
        }

    df_comp = load_completions(DB_URL)
    if participant_ids is not None:
        pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
        df_comp = df_comp[pd.to_numeric(df_comp['participant_id'], errors='coerce').isin(pids)].copy()
    df_comp['created_at'] = pd.to_datetime(df_comp['created_at'], errors='coerce')
    df_comp = df_comp[df_comp['questionnaire_id'].isin(naam_map.keys())]

    # Filter completions: gebruik alleen echte vragenlijsten
    df_comp['questionnaire_id'] = pd.to_numeric(df_comp['questionnaire_id'], errors='coerce')
    df_comp = df_comp[df_comp['questionnaire_id'].isin(naam_map.keys())].copy()

    # Aantal unieke vragenlijsten per participant
    per_participant = (
        df_comp.groupby('participant_id')['questionnaire_id']
        .nunique()
        .reset_index(name='n_vragenlijsten')
    )

    # Verdeling
    verdeling = (
        per_participant['n_vragenlijsten']
        .value_counts()
        .sort_index()
        .reset_index()
    )
    verdeling.columns = ['n_vragenlijsten', 'n_deelnemers']
    verdeling['pct'] = (verdeling['n_deelnemers'] / verdeling['n_deelnemers'].sum() * 100).round(1)

    kleuren = [HOOFD_KLEUR if n == 1 else '#2ECC71' for n in verdeling['n_vragenlijsten']]

    fig = go.Figure(go.Bar(
        x=verdeling['n_vragenlijsten'],
        y=verdeling['n_deelnemers'],
        marker_color=kleuren,
        text=verdeling.apply(lambda r: f"{int(r['n_deelnemers']):,} ({r['pct']}%)", axis=1),
        textposition='outside',
    ))
    fig.update_layout(
        title='Aantal ingevulde vragenlijsten per deelnemer',
        xaxis_title='Aantal verschillende vragenlijsten',
        yaxis_title='Aantal deelnemers',
        xaxis=dict(tickmode='linear', dtick=1),
        showlegend=False,
        height=450,
    )

    # Welke combinaties komen het meest voor
    combinaties = (
        df_comp.groupby('participant_id')['questionnaire_id']
        .apply(lambda x: ' + '.join(sorted([naam_map.get(i, str(i)) for i in x.unique()])))
        .reset_index(name='combinatie')
    )
    top_combinaties = (
        combinaties['combinatie']
        .value_counts()
        .head(10)
        .reset_index()
    )
    top_combinaties.columns = ['Combinatie', 'Aantal deelnemers']

    samenvatting = {
        'Totaal deelnemers': len(per_participant),
        'Slechts 1 vragenlijst': int((per_participant['n_vragenlijsten'] == 1).sum()),
        '2 of meer vragenlijsten': int((per_participant['n_vragenlijsten'] >= 2).sum()),
        'Alle vragenlijsten (8)': int((per_participant['n_vragenlijsten'] == 8).sum()),
        'Gemiddeld aantal': round(per_participant['n_vragenlijsten'].mean(), 2),
    }

    return fig, top_combinaties, samenvatting, per_participant


# ══════════════════════════════════════════════════════════════════════════════
# PROFIEL VROEGE KOPERS
# ══════════════════════════════════════════════════════════════════════════════
def maak_vroege_kopers_profiel(base_pad: Path, db_url: str,
                               geselecteerde_groepen: list[str] | None = None,
                               include_wellbeing: bool = False,
                               participant_ids: list | set | pd.Series | None = None) -> tuple:
    """
    Analyseert het profiel van vroege kopers: wie kopen er het eerste product?
    Vergelijkt vroege kopers (eerste aankoop <90 dagen na registratie)
    """
    try:
        base_pad = Path(base_pad)
        success_statuses = {'completed', 'paid', 'success', 'shipped', 'delivered', 'voltooid', 'betaald'}

        # Orders laden
        df_orders = None
        if _has_valid_db_url(db_url):
            try:
                engine = create_engine(db_url)
                df_orders = pd.read_sql('SELECT id, user_id, created_at, status FROM orders', engine)
            except Exception:
                df_orders = pd.DataFrame()

        # Aankopen laden via centrale herstelde koppeling.
        df_orders = get_user_purchases(base_pad, db_url)
        if participant_ids is not None:
            pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
            if 'participant_id' in df_orders.columns:
                df_orders = df_orders[pd.to_numeric(df_orders['participant_id'], errors='coerce').isin(pids)]

        for col in ['participant_id', 'user_id', 'status']:
            if col not in df_orders.columns:
                df_orders[col] = pd.NA
        if 'created_at' not in df_orders.columns:
            df_orders['created_at'] = pd.NaT

        if not df_orders.empty:
            df_orders['participant_id'] = pd.to_numeric(df_orders['participant_id'], errors='coerce')
            df_orders['created_at'] = pd.to_datetime(df_orders['created_at'], errors='coerce', utc=True).dt.tz_convert(None)
            df_orders = df_orders[df_orders['status'].astype(str).str.lower().isin(success_statuses)].copy()
            df_orders = df_orders.dropna(subset=['participant_id', 'created_at']).copy()

        eerste_aankoop = (
            df_orders.groupby('participant_id')['created_at']
            .min()
            .reset_index(name='eerste_aankoop')
        )

        # Registratiedatum (Referentie datum bepalen: account creation)
        df_users = load_participants(db_url or DB_URL)[['id', 'created_at']].copy()
        df_users = df_users.rename(columns={'id': 'participant_id', 'created_at': 'registratie_datum'})
        df_users['participant_id'] = pd.to_numeric(df_users['participant_id'], errors='coerce')
        df_users['referentie_datum'] = pd.to_datetime(
            df_users['registratie_datum'], errors='coerce', utc=True
        ).dt.tz_convert(None)

        df_kopers = eerste_aankoop.merge(df_users[['participant_id', 'referentie_datum']], on='participant_id', how='left')
        if 'user_id' in df_orders.columns:
            user_lookup = (
                df_orders[['participant_id', 'user_id']]
                .dropna(subset=['participant_id', 'user_id'])
                .drop_duplicates(subset=['participant_id'])
            )
            df_kopers = df_kopers.merge(user_lookup, on='participant_id', how='left')
        df_kopers['dagen_tot_koop'] = (df_kopers['eerste_aankoop'] - df_kopers['referentie_datum']).dt.days

        # Groepen
        def groep(dagen):
            if pd.isna(dagen): return 'Geen aankoop'
            elif dagen <= 90: return 'Vroege koper (≤90 dagen)'
            elif dagen <= 365: return 'Late koper (91-365 dagen)'
            else: return 'Zeer late koper (>365 dagen)'

        df_kopers['koper_groep'] = df_kopers['dagen_tot_koop'].apply(groep)

        # Scores koppelen
        df_scores_expanded = load_my_clic_participants_expanded(DB_URL)
        df_scores_expanded['participant_id'] = pd.to_numeric(df_scores_expanded['participant_id'], errors='coerce')
        if participant_ids is not None:
            pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
            df_scores_expanded = df_scores_expanded[df_scores_expanded['participant_id'].isin(pids)]
        df_scores_expanded = df_scores_expanded.drop_duplicates(subset='participant_id', keep='first')

        # Categoriseer leefstijlscore: 1-3 Slecht, 4-5 Matig, 6-7 Goed, 8-10 Uitstekend
        if 'rec_ls_lifestyle_score' in df_scores_expanded.columns:
            df_scores_expanded['ls_cat'] = pd.cut(
                df_scores_expanded['rec_ls_lifestyle_score'],
                bins=[0.5, 3.5, 5.5, 7.5, 10.5],
                labels=['Slecht', 'Matig', 'Goed', 'Uitstekend'],
                include_lowest=True
            )

        # Alle gebruikers krijgen een groep - select only available columns
        select_cols = ['participant_id']
        for col in ['rec_ls_lifestyle_score', 'rec_med_bmi', 'rec_ls_stress_sum', 'rec_heartrisk',
                     'rec_resilience_score', 'rec_wellbeing_score', 'rec_age_current', 'rec_user_gender']:
            if col in df_scores_expanded.columns:
                select_cols.append(col)
        df_all = df_scores_expanded[select_cols].copy()

        # Categoriseer leefstijlscore per gebruiker
        if 'ls_cat' in df_all.columns:
            df_all['ls_cat'] = pd.to_numeric(df_all['ls_cat'], errors='coerce').astype(str).replace(
                {'Slecht': '1', 'Matig': '2', 'Goed': '3', 'Uitstekend': '4'}
            )

        df_all['koper_groep'] = 'Geen aankoop'
        df_all['dagen_tot_koop'] = pd.NA

        participant_lookup = df_kopers.dropna(subset=['participant_id']).set_index('participant_id').to_dict(orient='index')
        user_lookup = df_kopers.dropna(subset=['user_id']).set_index('user_id').to_dict(orient='index')

        for idx, row in df_all.iterrows():
            pid = pd.to_numeric(row.get('participant_id'), errors='coerce')
            uid = pd.to_numeric(row.get('user_id'), errors='coerce')
            if pd.notna(pid) and int(pid) in participant_lookup:
                meta = participant_lookup[int(pid)]
            elif pd.notna(uid) and int(uid) in user_lookup:
                meta = user_lookup[int(uid)]
            else:
                continue
            df_all.at[idx, 'koper_groep'] = meta.get('koper_groep', 'Geen aankoop')
            df_all.at[idx, 'dagen_tot_koop'] = meta.get('dagen_tot_koop', pd.NA)

        # Categorie labels voor leefstijlscore
        ls_cat_labels = {1: tr('Slecht', 'nl'), 2: tr('Matig', 'nl'), 3: tr('Goed', 'nl'), 4: tr('Uitstekend', 'nl')}

        indicatoren = {
            'Leefstijlscore': 'ls_cat',
            'BMI': 'rec_med_bmi',
            'Stress': 'rec_ls_stress_sum',
            'Heartrisk': 'rec_heartrisk',
            'Veerkracht': 'rec_resilience_score',
        }
        if include_wellbeing:
            indicatoren['Welzijn'] = 'rec_wellbeing_score' # type: ignore

        rijen = []
        groep_volgorde = ['Vroege koper (≤90 dagen)', 'Late koper (91-365 dagen)',
                          'Zeer late koper (>365 dagen)', 'Geen aankoop']
        geselecteerde_groepen = geselecteerde_groepen or groep_volgorde
        geselecteerde_groepen = [groep for groep in groep_volgorde if groep in geselecteerde_groepen]
        for label, kolom in indicatoren.items():
            df_all[kolom] = pd.to_numeric(df_all[kolom], errors='coerce')
            for grp in geselecteerde_groepen:
                sub = df_all[df_all['koper_groep'] == grp][kolom].dropna()
                if len(sub) > 0:
                    # Gemiddelde score, of categorie modus als numeriek
                    if label == 'Leefstijlscore':
                        # Modus van de categorieën
                        cat_counts = sub.value_counts()
                        gemiddelde = int(cat_counts.idxmax()) if len(cat_counts) > 0 else 0
                    else:
                        gemiddelde = round(sub.mean(), 2)
                    rijen.append({
                        'Indicator': label,
                        'Groep': grp,
                        'Gemiddelde': gemiddelde,
                        'N': len(sub),
                    })

        df_plot = pd.DataFrame(rijen)

        # Categorie kleuren voor leefstijlscore
        ls_cat_kleuren = {
            tr('Slecht', 'nl'): '#E74C3C',
            tr('Matig', 'nl'): '#E87722',
            tr('Goed', 'nl'): '#2ECC71',
            tr('Uitstekend', 'nl'): '#1A8A4A',
        }
        kleur_map = {
            'Vroege koper (≤90 dagen)':    '#2ECC71',
            'Late koper (91-365 dagen)':   '#E87722',
            'Zeer late koper (>365 dagen)': '#E74C3C',
            'Geen aankoop':                '#95A5A6',
            # Extra kleur voor indicatoren balken
            'Leefstijlscore': ls_cat_kleuren,
        }

        fig = px.bar(
            df_plot, x='Indicator', y='Gemiddelde',
            color='Groep',
            barmode='group',
            color_discrete_map=kleur_map,
            text='Gemiddelde',
            labels={'Gemiddelde': 'Gemiddelde score', 'Indicator': ''}, # type: ignore
            title=f'Profiel vroege kopers vs late kopers (referentie: account_created)', # Use a default reference
            category_orders={'Groep': geselecteerde_groepen},
        )
        fig.update_traces(texttemplate='%{text:.2f}', textposition='outside')
        fig.update_layout(
            legend_title_text='',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1), # type: ignore
            height=500,
        )

        df_kpi = df_all[df_all['koper_groep'].isin(geselecteerde_groepen)].copy()
        if df_kpi.empty:
            df_kpi = df_all.copy()
        df_dagen = df_kopers[df_kopers['koper_groep'].isin(geselecteerde_groepen)].copy()
        profiel = {
            'Aantal geselecteerde gebruikers': len(df_kpi),
            'Gemiddelde leeftijd': round(pd.to_numeric(df_kpi['rec_age_current'], errors='coerce').mean(), 1),
            '% vrouw': round((pd.to_numeric(df_kpi['rec_user_gender'], errors='coerce') == 0).mean() * 100, 1),
            'Gem. leefstijlscore': round(pd.to_numeric(df_kpi['rec_ls_lifestyle_score'], errors='coerce').mean(), 2),
            'Gem. dagen tot aankoop': round(pd.to_numeric(df_dagen['dagen_tot_koop'], errors='coerce').mean(), 1),
        }

        # Verdeling dagen tot eerste aankoop
        df_kopers_valid = df_kopers[
            df_kopers['dagen_tot_koop'].between(0, 730) &
            df_kopers['koper_groep'].isin(geselecteerde_groepen)
        ].copy()
        if df_kopers_valid.empty and not df_kopers.empty:
            # Fallback to all buyers if specific groups are empty
            df_kopers_valid = df_kopers[df_kopers['dagen_tot_koop'].between(0, 730)].copy() # type: ignore
        elif df_kopers_valid.empty:
            # If still empty, create an empty DataFrame to avoid errors
            df_kopers_valid = pd.DataFrame(columns=['dagen_tot_koop'])
        fig_dagen = px.histogram(
            df_kopers_valid,
            x='dagen_tot_koop',
            nbins=50,
            color_discrete_sequence=[HOOFD_KLEUR],
            labels={'dagen_tot_koop': 'Dagen tot eerste aankoop', 'count': 'Aantal kopers'},
            title='Verdeling: dagen tot eerste aankoop (0-730 dagen)',
        )
        fig_dagen.add_vline(x=90, line_dash='dash', line_color='green',
                            annotation_text='90 dagen grens', annotation_position='top right')
        return fig, fig_dagen, profiel, df_plot
    except Exception as e:
        logger.error(f"Error in maak_vroege_kopers_profiel: {e}")
        # Return empty figures with error message
        empty_df = pd.DataFrame({'Indicator': [], 'Groep': [], 'Gemiddelde': [], 'N': []})
        fig_empty = px.bar(empty_df, x='Indicator', y='Gemiddelde',
                          title='Kopersprofiel: geen data beschikbaar')
        fig_empty.update_layout(height=500) # type: ignore

        fig_dagen_empty = px.histogram(pd.DataFrame(), title='Verdeling: geen data beschikbaar')
        fig_dagen_empty.update_layout(height=350) # type: ignore

        empty_profiel = {
            'Aantal geselecteerde gebruikers': 0,
            'Gemiddelde leeftijd': 0.0,
            '% vrouw': 0.0,
            'Gem. leefstijlscore': 0.0,
            'Gem. dagen tot aankoop': 0.0,
        }
        
        return fig_empty, fig_dagen_empty, empty_profiel, empty_df

def _is_higher_better(slug: str) -> bool:
    """Bepaal of een hogere score ‘beter’ is aan de hand van variabele metadata."""
    if not isinstance(slug, str) or slug == '':
        return True

    for variabele in VARIABELEN_DICT.values():
        if variabele.get('kolom') == slug or variabele.get('label') == slug:
            kleur_richting = variabele.get('kleur_richting')
            if kleur_richting == 'laatste_goed':
                return True
            if kleur_richting == 'eerste_goed':
                return False
            if kleur_richting == 'midden_goed':
                return True
    
    lager_is_beter = ['alcohol', 'smoking', 'stress', 'bmi', 'sugar', 'fat', 'salt', 'blood_pressure', 'diabetes']
    return slug not in lager_is_beter


def maak_risico_migratie_sankey(df_long: pd.DataFrame, slug: str, label_map: dict, lang: str = 'nl') -> go.Figure:
    """Toont de verschuiving tussen risicocategorieën tussen de eerste en laatste meting."""
    if {'Van', 'Na', 'Aantal'}.issubset(df_long.columns):
        matrix = df_long.copy()
    else:
        from analyses import bereken_risico_migratie
        matrix = bereken_risico_migratie(df_long, slug)
    
    if matrix.empty:
        return _empty_store_plot(tr("Onvoldoende deelnemers met herhaalmetingen voor migratie-analyse.", lang))
        
    # Bepaal werkelijk aanwezige categorieën (geen hardcoded filtering)
    present_cats = sorted(set(matrix['Van'].unique()) | set(matrix['Na'].unique()))
    higher_is_better = _is_higher_better(slug)
    display_cats = sorted(present_cats, reverse=higher_is_better)
    ncats = len(display_cats)
    
    if ncats == 0:
        return _empty_store_plot(tr("Onvoldoende data voor visualisatie.", lang))
    
    # Bereken totals per categorie voor eerste en laatste meting
    totals_van = matrix.groupby('Van')['Aantal'].sum().to_dict()
    totals_na = matrix.groupby('Na')['Aantal'].sum().to_dict()

    def label_with_count(i, when='Eerste'):
        base = tr(label_map.get(i, str(i)), lang)
        count = int(totals_van.get(i, 0)) if when == 'Eerste' else int(totals_na.get(i, 0))
        return f"{base} ({tr(when, lang)}) — {count:,}"

    labels_van = [label_with_count(i, 'Eerste') for i in display_cats]
    labels_na = [label_with_count(i, 'Laatste') for i in display_cats]
    all_labels = labels_van + labels_na

    groen, oranje, rood = '#2ECC71', '#E87722', '#E74C3C'

    # Bepaal kleur per categorie op basis van higher_is_better logica
    cat_to_color = {}
    for cat in display_cats:
        if ncats == 1:
            cat_to_color[cat] = groen
        elif ncats == 2:
            if higher_is_better:
                cat_to_color[cat] = groen if cat == max(present_cats) else rood
            else:
                cat_to_color[cat] = groen if cat == min(present_cats) else rood
        elif ncats == 3:
            if higher_is_better:
                if cat == max(present_cats):
                    cat_to_color[cat] = groen
                elif cat == min(present_cats):
                    cat_to_color[cat] = rood
                else:
                    cat_to_color[cat] = oranje
            else:
                if cat == min(present_cats):
                    cat_to_color[cat] = groen
                elif cat == max(present_cats):
                    cat_to_color[cat] = rood
                else:
                    cat_to_color[cat] = oranje
        else:
            # Meer dan 3: verdeel groen/oranje/rood lineair
            if higher_is_better:
                if cat == max(present_cats):
                    cat_to_color[cat] = groen
                elif cat == min(present_cats):
                    cat_to_color[cat] = rood
                else:
                    cat_to_color[cat] = oranje
            else:
                if cat == min(present_cats):
                    cat_to_color[cat] = groen
                elif cat == max(present_cats):
                    cat_to_color[cat] = rood
                else:
                    cat_to_color[cat] = oranje

    cat_colors = [cat_to_color[cat] for cat in display_cats]
    if ncats == 1:
        positions = [0.45]
    else:
        step = 0.8 / (ncats - 1)
        positions = [0.05 + (idx * step) for idx in range(ncats)]

    node_colors = cat_colors + cat_colors
    node_x = [0.02] * ncats + [0.98] * ncats
    node_y = positions + positions

    # Map oude categorieën naar nieuwe indices
    cat_to_idx = {cat: i for i, cat in enumerate(display_cats)}
    
    sources = [cat_to_idx[int(v)] for v in matrix['Van']]
    targets = [cat_to_idx[int(v)] + ncats for v in matrix['Na']]
    values = matrix['Aantal'].tolist()

    # Build link hover text showing count and percentage of source-category
    # Map source totals for percentage calculations
    source_totals = matrix.groupby('Van')['Aantal'].sum().to_dict()
    link_hover = []
    for _, row in matrix.iterrows():
        s = int(row['Van']); t = int(row['Na']); v = int(row['Aantal'])
        total_s = int(source_totals.get(s, 0)) or 1
        pct = v / total_s * 100
        link_hover.append(f"{tr(label_map.get(s, str(s)), lang)} → {tr(label_map.get(t, str(t)), lang)}: {v:,} ({pct:.1f}%)")
    
    link_colors = []
    
    for _, row in matrix.iterrows():
        s, t = int(row['Van']), int(row['Na'])
        if not higher_is_better:
            if t < s: color = 'rgba(46, 204, 113, 0.4)' # Groen (verbetering)
            elif t > s: color = 'rgba(231, 76, 60, 0.4)' # Rood (verslechtering)
            else: color = 'rgba(200, 200, 200, 0.4)'
        else:
            if t > s: color = 'rgba(46, 204, 113, 0.4)'
            elif t < s: color = 'rgba(231, 76, 60, 0.4)'
            else: color = 'rgba(200, 200, 200, 0.4)'
        link_colors.append(color)

    fig = go.Figure(data=[go.Sankey(
        arrangement='freeform',
        node = dict(
            pad = 30,
            thickness = 20,
            line = dict(color = "black", width = 0.5),
            label = all_labels,
            color = node_colors,
            x = node_x,
            y = node_y,
            align = 'center',
            hovertemplate = "%{label}<extra></extra>",
            hoverlabel = dict(font = dict(size=13, color='black', family='Arial, sans-serif'))
        ),
        link = dict(
            source = sources,
            target = targets,
            value = values,
            color = link_colors,
            customdata = link_hover,
            hovertemplate = "%{customdata}<extra></extra>",
            hoverlabel = dict(font = dict(size=12, family='Arial, sans-serif'))
        )
    )])

    fig.update_layout(
        title_text=tr("Risico-migratie: verschuiving tussen eerste en laatste meting", lang),
        height=700,
        margin=dict(l=200, r=200, t=100, b=50),
        font=dict(size=12, family='Arial, sans-serif', color='black'),
        paper_bgcolor='white',
        plot_bgcolor='white'
    )
    return fig


DEFAULT_RISICOMIGRATIE_BINS = {
    'bmi': {
        'bins': [-0.1, 18.5, 25.0, 30.0, 1000.0],
        'labels': ['Ondergewicht (<18.5)', 'Normaal gewicht (18.5-25)', 'Overgewicht (25-30)', 'Obesitas (>30)']
    },
    'fruit': {
        'bins': [-0.1, 0.5, 1.5, 10000.0],
        'labels': ['Weinig (<1/dag)', 'Matig (~1/dag)', 'Veel (≥2/dag)']
    },
    'vegetables': {
        'bins': [-0.1, 150.0, 250.0, 100000.0],
        'labels': ['Laag (<150g)', 'Matig (150-250g)', 'Veel (≥250g)']
    },
    'stress': {
        'bins': [-0.1, 5.0, 14.0, 100.0],
        'labels': ['Weinig stress (<5)', 'Matig stress (5-14)', 'Veel stress (>14)']
    },
    'dass_stress': {
        'bins': [-0.1, 14.0, 18.0, 25.0, 100.0],
        'labels': ['Normaal (0-14)', 'Matig (15-18)', 'Ernstig (19-25)', 'Zeer ernstig (>25)']
    },
    'dass_anxiety': {
        'bins': [-0.1, 7.0, 9.0, 14.0, 100.0],
        'labels': ['Normaal (0-7)', 'Matig (8-9)', 'Ernstig (10-14)', 'Zeer ernstig (>14)']
    },
    'dass_depression': {
        'bins': [-0.1, 9.0, 13.0, 20.0, 100.0],
        'labels': ['Normaal (0-9)', 'Matig (10-13)', 'Ernstig (14-20)', 'Zeer ernstig (>20)']
    },
    'sleep': {
        'bins': [-0.1, 5.0, 10.0, 100.0],
        'labels': ['Goed (PSQI ≤5)', 'Matig (PSQI 6-10)', 'Slecht (PSQI >10)']
    },
    'alcohol': {
        'bins': [-0.1, 0.5, 14.0, 1000.0],
        'labels': ['Geen/Zelden (<1/wk)', 'Matig (1-14/wk)', 'Hoog (>14/wk)']
    },
    'sugar': {
        'bins': [-0.1, 25.0, 50.0, 10000.0],
        'labels': ['Laag (<25g)', 'Matig (25-50g)', 'Hoog (>50g)']
    },
    'fat': {
        'bins': [-0.1, 22.0, 35.0, 10000.0],
        'labels': ['Laag (<22g)', 'Matig (22-35g)', 'Hoog (>35g)']
    },
    'salt': {
        'bins': [-0.1, 2400.0, 3500.0, 100000.0],
        'labels': ['Laag (<2400mg)', 'Matig (2400-3500mg)', 'Hoog (>3500mg)']
    },
    'blood_pressure': {
        'bins': [-0.1, 0.5, 1.5, 10.0],
        'labels': ['Normaal', 'Verhoogd', 'Hoog']
    },
    'steps': {
        'bins': [-0.1, 5000.0, 10000.0, 100000.0],
        'labels': ['Weinig (<5.000)', 'Matig (5.000-10.000)', 'Veel (>10.000)']
    },
    'exercise': {
        'bins': [-0.1, 150.0, 300.0, 10000.0],
        'labels': ['Onvoldoende (<150 min)', 'Voldoende (150-300 min)', 'Actief (>300 min)']
    },
    'wellbeing': {
        'bins': [-0.1, 50.0, 75.0, 100.0],
        'labels': ['Laag welzijn (<50)', 'Matig welzijn (50-75)', 'Hoog welzijn (>75)']
    },
    'resilience': {
        'bins': [-0.1, 20.0, 30.0, 40.0],
        'labels': ['Laag (<20)', 'Gemiddeld (20-30)', 'Hoog (>30)']
    },
    'workload': {
        'bins': [-0.1, 3.0, 7.0, 10.0],
        'labels': ['Lage werkdruk (<3)', 'Normale werkdruk (3-7)', 'Hoge werkdruk (>7)']
    },
    'job_satisfaction': {
        'bins': [-0.1, 5.0, 7.5, 10.0],
        'labels': ['Ontevreden (<5)', 'Voldoende (5-7.5)', 'Tevreden (>7.5)']
    },
    'lifestyle': {
        'bins': [-0.1, 60.0, 80.0, 100.0],
        'labels': ['Matig (<60)', 'Voldoende (60-80)', 'Uitstekend (>80)']
    },
    'heartrisk': {
        'bins': [-0.1, 0.5, 1.5, 10.0],
        'labels': ['Laag risico', 'Matig risico', 'Hoog risico']
    }
}


def bereken_risico_migratie_value_binned(df_long: pd.DataFrame, slug: str, max_unique: int = 6, n_bins: int = 5, custom_bins: dict | None = None):
    """Bereken migratie op basis van `score_value` door waarden te binen wanneer nodig.

    Returns: (matrix_df, label_map) where matrix_df has columns Van(int), Na(int), Aantal
    and label_map maps integer codes to display labels.
    """
    if df_long is None or df_long.empty:
        return pd.DataFrame(), {}

    df_factor = df_long[df_long['slug'] == slug].sort_values(['participant_id', 'completion_created_at'])
    if df_factor.empty:
        return pd.DataFrame(), {}

    ids = df_factor.groupby('participant_id').size()
    multi_ids = ids[ids >= 2].index
    first = df_factor.groupby('participant_id').first().loc[multi_ids]
    last = df_factor.groupby('participant_id').last().loc[multi_ids]

    first_vals = pd.to_numeric(first['score_value'], errors='coerce')
    last_vals = pd.to_numeric(last['score_value'], errors='coerce')
    df_pairs = pd.DataFrame({'Van_raw': first_vals, 'Na_raw': last_vals}).dropna()
    if df_pairs.empty:
        return pd.DataFrame(), {}

    combined = pd.concat([df_pairs['Van_raw'], df_pairs['Na_raw']])
    unique_vals = combined.dropna().unique()

    bins_config = {**DEFAULT_RISICOMIGRATIE_BINS, **(custom_bins or {})}

    if slug in bins_config:
        try:
            cfg = bins_config[slug]
            bins_edges = list(cfg.get('bins'))
            labels = list(cfg.get('labels'))
            if not bins_edges or not labels:
                return pd.DataFrame(), {}
            df_pairs['Van_bin'] = pd.cut(df_pairs['Van_raw'], bins=bins_edges, include_lowest=True)
            df_pairs['Na_bin'] = pd.cut(df_pairs['Na_raw'], bins=bins_edges, include_lowest=True)
            categories = list(pd.Categorical(df_pairs['Van_bin']).categories)
            cat_to_code = {cat: i for i, cat in enumerate(categories)}
            df_pairs['Van'] = df_pairs['Van_bin'].map(cat_to_code)
            df_pairs['Na'] = df_pairs['Na_bin'].map(cat_to_code)
            label_map = {i: labels[i] if i < len(labels) else str(categories[i]) for i in range(len(categories))}
        except Exception:
            return pd.DataFrame(), {}
    else:
        # If few unique integer-like values, use them directly as categories
        is_integer_like = pd.api.types.is_integer_dtype(combined) or all(float(x).is_integer() for x in unique_vals[:min(len(unique_vals), 20)])
        if len(unique_vals) <= max_unique and is_integer_like:
            bins = sorted(int(v) for v in sorted(unique_vals))
            val_to_code = {v: i for i, v in enumerate(bins)}
            label_map = {i: str(v) for v, i in val_to_code.items()}
            df_pairs['Van'] = df_pairs['Van_raw'].astype(int).map(val_to_code)
            df_pairs['Na'] = df_pairs['Na_raw'].astype(int).map(val_to_code)
        else:
            # Use quantile-based bins with formatted labels
            try:
                bins_edges = list(np.unique(np.quantile(combined.dropna(), np.linspace(0, 1, n_bins + 1))))
                if len(bins_edges) <= 1:
                    return pd.DataFrame(), {}
                df_pairs['Van_bin'] = pd.cut(df_pairs['Van_raw'], bins=bins_edges, include_lowest=True)
                df_pairs['Na_bin'] = pd.cut(df_pairs['Na_raw'], bins=bins_edges, include_lowest=True)
                categories = list(pd.Categorical(df_pairs['Van_bin']).categories)
                label_map = {}
                for i, cat in enumerate(categories):
                    label_map[i] = f"{cat.left:.1f} – {cat.right:.1f}"
                cat_to_code = {cat: i for i, cat in enumerate(categories)}
                df_pairs['Van'] = df_pairs['Van_bin'].map(cat_to_code)
                df_pairs['Na'] = df_pairs['Na_bin'].map(cat_to_code)
            except Exception:
                return pd.DataFrame(), {}

    df_pairs = df_pairs.dropna(subset=['Van', 'Na'])
    if df_pairs.empty:
        return pd.DataFrame(), {}

    matrix = df_pairs.groupby(['Van', 'Na']).size().reset_index(name='Aantal')
    matrix['Van'] = matrix['Van'].astype(int)
    matrix['Na'] = matrix['Na'].astype(int)
    return matrix, label_map

def maak_engagement_funnel_plot(base_pad: Path, db_url: str, lang: str = 'nl', participant_ids: list | set | pd.Series | None = None) -> go.Figure:
    """Visualiseert de funnel van registratie naar herhaalmeting."""
    from data_ingestion import load_participants, load_completions, get_user_purchases
    
    try:
        df_p = load_participants(db_url)
        df_c = load_completions(db_url)
        df_o = get_user_purchases(base_pad, db_url)
        df_long = laad_longitudinale_data(base_pad, db_url)
        
        if participant_ids is not None:
            pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
            if not df_p.empty and 'id' in df_p.columns:
                df_p = df_p[pd.to_numeric(df_p['id'], errors='coerce').isin(pids)]
            if not df_c.empty and 'participant_id' in df_c.columns:
                df_c = df_c[pd.to_numeric(df_c['participant_id'], errors='coerce').isin(pids)]
            if not df_o.empty and 'participant_id' in df_o.columns:
                df_o = df_o[pd.to_numeric(df_o['participant_id'], errors='coerce').isin(pids)]
            if not df_long.empty and 'participant_id' in df_long.columns:
                df_long = df_long[pd.to_numeric(df_long['participant_id'], errors='coerce').isin(pids)]

        n_reg = df_p['id'].nunique() if not df_p.empty else 0
        n_comp = df_c['participant_id'].nunique() if not df_c.empty else 0
        n_buy = df_o['participant_id'].nunique() if not df_o.empty and 'participant_id' in df_o.columns else 0
        n_repeat_count = int((df_long.groupby('participant_id')['completion_id'].nunique() >= 2).sum()) if not df_long.empty else 0
        
        stages = [tr("Geregistreerd", lang), tr("Vragenlijst ingevuld", lang), tr("Product gekocht", lang), tr("Herhaalmeting gedaan", lang)]
        values = [n_reg, n_comp, n_buy, n_repeat_count]
        
        fig = go.Figure(go.Funnel(
            y = stages, x = values,
            textinfo = "value+percent initial",
            marker = {"color": ["#1F6FBF", "#3498DB", "#2ECC71", "#27AE60"]}
        ))
        fig.update_layout(title_text=tr("Engagement Funnel: conversie naar actie", lang), height=450)
        return fig
    except Exception:
        return _empty_store_plot(tr("Fout bij laden van engagement funnel.", lang))

def maak_business_value_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    """Toont correlatie tussen WAI en productiviteitsschatting."""
    if df.empty or 'rec_asr_wai_score' not in df.columns:
         return _empty_store_plot(tr("Geen WAI data beschikbaar.", lang))

    df2 = df.dropna(subset=['rec_asr_wai_score']).copy()
    df2['WAI'] = pd.to_numeric(df2['rec_asr_wai_score'], errors='coerce')
    df2 = df2.dropna(subset=['WAI'])
    
    if df2.empty:
        return _empty_store_plot(tr("Geen WAI data beschikbaar.", lang))

    # Wetenschappelijke aanname: 1 punt stijging in WAI correleert met ~3% productiviteitswinst
    df2['Productiviteit (%)'] = (70 + df2['WAI'] * 3).clip(0, 100)
    
    fig = px.scatter(df2, x='WAI', y='Productiviteit (%)', trendline="ols" if HAS_STATSMODELS else None,
                     title=tr("Business Case: Werkvermogen (WAI) vs Geschatte Productiviteit", lang),
                     labels={'WAI': 'Work Ability Index (0-10)', 'Productiviteit (%)': tr('Productiviteit (%)', lang)},
                     color_discrete_sequence=[HOOFD_KLEUR], opacity=0.5)
    fig.update_layout(template='plotly_white')
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# 4 ANALYTISCHE VISUALISATIES VOOR DE VRAGEN
# ══════════════════════════════════════════════════════════════════════════════

def maak_vragenlijst_herhalingen_vs_scores(base_pad: Path, db_url: str, lang: str = 'nl') -> tuple:
    """Backward-compatible wrapper – gebruikt analyse_invulfrequentie_vs_scores."""
    from analyses import analyse_invulfrequentie_vs_scores
    df_plot, samenvatting, meta = analyse_invulfrequentie_vs_scores(
        base_pad, db_url, score_kolom='rec_ls_lifestyle_score'
    )
    if df_plot.empty:
        return _empty_store_plot(tr("Onvoldoende data.", lang)), None

    score_kolom = meta.get('score_kolom', 'rec_ls_lifestyle_score')
    fig = px.box(
        df_plot, x='n_categorie', y=score_kolom, points='outliers',
        title=tr('Invulfrequentie vs Huidige Leefstijlscore', lang),
        labels={
            score_kolom: tr('Leefstijlscore', lang),
            'n_categorie': tr('Aantal verschillende vragenlijsten ingevuld', lang),
        },
        category_orders={'n_categorie': ['1x', '2x', '3x', '4x', '5x', '6+x']},
    )
    fig.update_layout(template='plotly_white')

    samenvatting_dict = {}
    if not samenvatting.empty:
        for _, row in samenvatting.iterrows():
            samenvatting_dict[f"{row['Invulfrequentie']} - gem. score"] = row.get(f'gem_{score_kolom}')
        if 'verschil_1x_vs_6plus' in meta:
            samenvatting_dict['Verschil (6+x vs 1x)'] = meta['verschil_1x_vs_6plus']
    return fig, samenvatting_dict


def maak_invulfrequentie_vs_scores_plot(
    base_pad: Path,
    db_url: str,
    score_kolom: str = 'rec_ls_lifestyle_score',
    score_label: str = 'Leefstijlscore',
    lang: str = 'nl',
) -> tuple:
    """Boxplot + gemiddelde-balken voor scores per invulfrequentie (1x, 2x, ...)."""
    from analyses import analyse_invulfrequentie_vs_scores

    df_plot, samenvatting, meta = analyse_invulfrequentie_vs_scores(base_pad, db_url, score_kolom)
    if df_plot.empty or samenvatting.empty:
        return _empty_store_plot(tr("Onvoldoende data.", lang)), _empty_store_plot(tr("Onvoldoende data.", lang)), pd.DataFrame(), df_plot

    volgorde = ['1x', '2x', '3x', '4x', '5x', '6+x']
    fig_box = px.box(
        df_plot, x='n_categorie', y=score_kolom, points='outliers',
        title=tr('Scoreverdeling per invulfrequentie', lang),
        labels={'n_categorie': tr('Aantal vragenlijsten', lang), score_kolom: score_label},
        category_orders={'n_categorie': volgorde},
    )
    fig_box.update_layout(template='plotly_white')

    plot_agg = samenvatting.copy()
    fig_bar = px.bar(
        plot_agg,
        x='Invulfrequentie',
        y=f'gem_{score_kolom}',
        error_y=f'std_{score_kolom}',
        text='n_deelnemers',
        title=tr('Gemiddelde score per invulfrequentie', lang),
        labels={
            'Invulfrequentie': tr('Invulfrequentie', lang),
            f'gem_{score_kolom}': score_label,
            'n_deelnemers': 'n',
        },
        category_orders={'Invulfrequentie': volgorde},
        color_discrete_sequence=[HOOFD_KLEUR],
    )
    fig_bar.update_traces(
        texttemplate='n=%{text}',
        textposition='outside',
    )
    fig_bar.update_layout(template='plotly_white', showlegend=False)

    display_cols = ['Invulfrequentie', 'n_deelnemers'] + [
        c for c in samenvatting.columns if c.startswith('gem_')
    ]
    return fig_box, fig_bar, samenvatting[display_cols], df_plot


def maak_herhaalde_vragenlijst_scoreverandering_plot(
    base_pad: Path,
    db_url: str,
    questionnaire_id: int,
    score_slug: str,
    lang: str = 'nl',
) -> tuple:
    """
    Visualiseer scoreverandering bij herhaald invullen van dezelfde vragenlijst.

    Returns: (fig_verandering, fig_traject, samenvatting, traject, df_change, meta)
    """
    from analyses import analyse_herhaalde_vragenlijst_scoreverandering

    samenvatting, traject, df_change, meta = analyse_herhaalde_vragenlijst_scoreverandering(
        base_pad, db_url, questionnaire_id, score_slug
    )
    if samenvatting.empty:
        empty = _empty_store_plot(tr("Onvoldoende data voor herhaalanalyse.", lang))
        return empty, empty, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), meta

    q_naam = meta.get('questionnaire_naam', f'Vragenlijst {questionnaire_id}')
    score_label = score_slug.replace('rec_', '').replace('_', ' ').title()
    volgorde = ['1x', '2x', '3x', '4x', '5x', '6+x']

    fig_verandering = px.bar(
        samenvatting,
        x='Invulfrequentie',
        y='gem_verandering',
        error_y='std_verandering',
        text='n_deelnemers',
        title=tr(
            'Gemiddelde scoreverandering (laatste − eerste) bij herhaald invullen: {naam}',
            lang,
        ).format(naam=q_naam),
        labels={
            'Invulfrequentie': tr('Aantal keer dezelfde vragenlijst ingevuld', lang),
            'gem_verandering': tr(f'Verandering {score_label}', lang),
            'n_deelnemers': 'n',
        },
        category_orders={'Invulfrequentie': volgorde},
        color_discrete_sequence=[HOOFD_KLEUR],
    )
    fig_verandering.update_traces(texttemplate='n=%{text}', textposition='outside')
    fig_verandering.add_hline(y=0, line_dash='dash', line_color='gray')
    fig_verandering.update_layout(template='plotly_white', showlegend=False)

    fig_traject = _empty_store_plot(tr("Geen trajectdata.", lang))
    if not traject.empty:
        fig_traject = px.line(
            traject,
            x='invul_label',
            y='gem_score',
            markers=True,
            text='n_deelnemers',
            title=tr('Scoreverloop per invulmoment: {naam}', lang).format(naam=q_naam),
            labels={
                'invul_label': tr('Invulmoment', lang),
                'gem_score': score_label,
                'n_deelnemers': 'n',
            },
            color_discrete_sequence=[HOOFD_KLEUR],
        )
        fig_traject.update_traces(
            texttemplate='n=%{text}',
            textposition='top center',
        )
        fig_traject.update_layout(template='plotly_white')

    return fig_verandering, fig_traject, samenvatting, traject, df_change, meta


def maak_account_dataflow_funnel_plot(base_pad: Path, db_url: str, lang: str = 'nl') -> tuple:
    """Funneldiagram van registratie naar scores, incl. naam- en leeftijdstap."""
    from analyses import analyse_account_dataflow_funnel

    funnel_df, meta = analyse_account_dataflow_funnel(base_pad, db_url)
    if funnel_df.empty:
        return _empty_store_plot(tr("Onvoldoende data voor funnel.", lang)), pd.DataFrame(), {}

    funnel_plot_df = funnel_df[funnel_df['stap_key'] != 'naam_parallel'] if 'stap_key' in funnel_df.columns else funnel_df

    fig = go.Figure(go.Funnel(
        y=[tr(row['stap'], lang) if lang == 'en' else row['stap'] for _, row in funnel_plot_df.iterrows()],
        x=funnel_plot_df['aantal'],
        textinfo='value+percent initial',
        customdata=funnel_plot_df[['pct_afgevallen_sinds_vorige', 'afgevallen_sinds_vorige']].values,
        hovertemplate=(
            '<b>%{y}</b><br>'
            'Aantal: %{x}<br>'
            '%{percentInitial} van start<br>'
            'Afgevallen sinds vorige stap: %{customdata[1]} (%{customdata[0]:.1f}%)<extra></extra>'
        ),
        marker={'color': ['#1F6FBF', '#3498DB', '#5DADE2', '#2ECC71', '#27AE60'][:len(funnel_plot_df)]},
    ))
    fig.update_layout(
        title=tr('Dataflow: van registratie naar scores', lang),
        height=500,
        template='plotly_white',
    )
    return fig, funnel_df, meta


def _laad_interaction_views(db_url: str | None = None) -> pd.DataFrame:
    """Laad content-views uit interactions (position-based kolommapping)."""
    effective_db_url = db_url or DB_URL
    if not _has_valid_db_url(effective_db_url):
        return pd.DataFrame(columns=['user_id', 'created_at'])

    try:
        engine = create_engine(effective_db_url)
        df_inter_raw = pd.read_sql("SELECT * FROM interactions", engine)
        if df_inter_raw.empty or len(df_inter_raw.columns) < 7:
            return pd.DataFrame(columns=['user_id', 'created_at'])

        df_inter = df_inter_raw.iloc[:, :7].copy()
        df_inter.columns = ['id', 'interactable_type', 'interactable_id', 'user_id', 'type', 'created_at', 'updated_at']
        df_inter = df_inter[
            (df_inter['interactable_type'].astype(str).str.strip() == 'content') &
            (df_inter['type'].astype(str).str.strip() == 'view')
        ].copy()
        df_inter['user_id'] = pd.to_numeric(df_inter['user_id'], errors='coerce')
        df_inter['created_at'] = pd.to_datetime(df_inter['created_at'], errors='coerce')
        return df_inter.dropna(subset=['user_id'])
    except Exception as e:
        logger.warning(f"Kon interactions niet laden: {e}")
        return pd.DataFrame(columns=['user_id', 'created_at'])


def _laad_user_challenges_per_store(db_url: str | None = None) -> pd.DataFrame:
    """Laad challenge-deelname per store (position-based kolommapping)."""
    effective_db_url = db_url or DB_URL
    if not _has_valid_db_url(effective_db_url):
        return pd.DataFrame(columns=['store_id', 'user_ref', 'status', 'created_at'])

    try:
        engine = create_engine(effective_db_url)
        df_raw = pd.read_sql("SELECT * FROM user_challenges", engine)
        if df_raw.empty or len(df_raw.columns) < 5:
            return pd.DataFrame(columns=['store_id', 'user_ref', 'status', 'created_at'])

        df = df_raw.iloc[:, :9].copy()
        df.columns = [
            'id', 'user_ref', 'challenge_id', 'store_id', 'status',
            'weeks_completed', 'challenge_type', 'created_at', 'updated_at',
        ][:len(df.columns)]
        df['store_id'] = pd.to_numeric(df['store_id'], errors='coerce')
        df['user_ref'] = pd.to_numeric(df['user_ref'], errors='coerce')
        df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce')
        return df.dropna(subset=['store_id'])
    except Exception as e:
        logger.warning(f"Kon user_challenges niet laden: {e}")
        return pd.DataFrame(columns=['store_id', 'user_ref', 'status', 'created_at'])


def _laad_participant_user_bridge(db_url: str | None = None) -> pd.DataFrame:
    """Koppel participant_id aan user_id via my_clic bridge."""
    effective_db_url = db_url or DB_URL
    if not _has_valid_db_url(effective_db_url):
        return pd.DataFrame(columns=['participant_id', 'user_id'])

    try:
        engine = create_engine(effective_db_url)
        bridge = pd.read_sql(
            text("""
                SELECT p.id AS participant_id, m.user_id
                FROM participants p
                JOIN my_clic_participants m
                    ON m.qe_participant_id = p.public_id
                WHERE m.user_id IS NOT NULL
            """),
            engine,
        )
        bridge['participant_id'] = pd.to_numeric(bridge['participant_id'], errors='coerce')
        bridge['user_id'] = pd.to_numeric(bridge['user_id'], errors='coerce')
        return bridge.dropna(subset=['participant_id', 'user_id']).drop_duplicates('participant_id')
    except Exception as e:
        logger.warning(f"Kon participant-user bridge niet laden: {e}")
        return pd.DataFrame(columns=['participant_id', 'user_id'])


ENGAGEMENT_COMPONENT_DEFAULTS = {
    'vragenlijst': 0.30,
    'herhaalmeting': 0.20,
    'breedte': 0.15,
    'artikelen': 0.15,
    'challenges': 0.10,
    'aankopen': 0.10,
}


def bereken_gebruiker_engagement_scores(
    base_pad: Path,
    db_url: str | None = None,
    participant_ids: list | set | pd.Series | None = None,
) -> pd.DataFrame:
    """
    Bereken per deelnemer engagement-componenten (0–100) over koppelbare databronnen.
    """
    base_pad = Path(base_pad)
    effective_db_url = db_url or DB_URL

    links = _laad_opdrachtgever_links(effective_db_url)
    if links.empty:
        return pd.DataFrame()

    if participant_ids is not None:
        pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
        links = links[pd.to_numeric(links['participant_id'], errors='coerce').isin(pids)]
        if links.empty:
            return pd.DataFrame()

    df_scores = load_my_clic_participants_expanded(effective_db_url)
    if df_scores.empty:
        return pd.DataFrame()

    df = links[['participant_id', 'store_id', 'store_name', 'user_id']].copy()
    df['participant_id'] = pd.to_numeric(df['participant_id'], errors='coerce')
    df = df.drop_duplicates(subset='participant_id', keep='first')

    score_cols = ['rec_ls_lifestyle_score']
    score_cols = [c for c in score_cols if c in df_scores.columns]
    if score_cols:
        df_scores['participant_id'] = pd.to_numeric(df_scores['participant_id'], errors='coerce')
        df = df.merge(
            df_scores[['participant_id'] + score_cols].drop_duplicates('participant_id'),
            on='participant_id',
            how='left',
        )

    if 'user_id' not in df.columns or df['user_id'].isna().all():
        bridge = _laad_participant_user_bridge(effective_db_url)
        if not bridge.empty:
            df = df.drop(columns=['user_id'], errors='ignore').merge(bridge, on='participant_id', how='left')

    known_questionnaire_ids = {1, 2, 3, 4, 5, 6, 7, 8}
    df_comp = load_completions(effective_db_url)
    if not df_comp.empty:
        df_comp = df_comp.copy()
        df_comp['participant_id'] = pd.to_numeric(df_comp['participant_id'], errors='coerce')
        df_comp['questionnaire_id'] = pd.to_numeric(df_comp['questionnaire_id'], errors='coerce')
        df_comp = df_comp[df_comp['questionnaire_id'].isin(known_questionnaire_ids)]
        comp_stats = df_comp.groupby('participant_id').agg(
            n_completions=('completion_id', 'nunique') if 'completion_id' in df_comp.columns else ('questionnaire_id', 'count'),
            n_vragenlijsten=('questionnaire_id', 'nunique'),
        ).reset_index()
        df = df.merge(comp_stats, on='participant_id', how='left')
    else:
        df['n_completions'] = 0
        df['n_vragenlijsten'] = 0

    df['n_completions'] = pd.to_numeric(df.get('n_completions'), errors='coerce').fillna(0)
    df['n_vragenlijsten'] = pd.to_numeric(df.get('n_vragenlijsten'), errors='coerce').fillna(0)

    has_score = pd.to_numeric(df.get('rec_ls_lifestyle_score'), errors='coerce').notna()
    df['score_vragenlijst'] = np.where(has_score, 100.0, np.where(df['n_completions'] > 0, 50.0, 0.0))
    df['score_herhaalmeting'] = np.where(df['n_completions'] >= 2, 100.0, 0.0)
    df['score_breedte'] = (df['n_vragenlijsten'].clip(0, 8) / 8.0 * 100.0).round(1)

    views = _laad_interaction_views(effective_db_url)
    if not views.empty and 'user_id' in df.columns:
        viewers = set(views['user_id'].dropna().astype(int))
        df['user_id_num'] = pd.to_numeric(df['user_id'], errors='coerce')
        df['score_artikelen'] = np.where(df['user_id_num'].isin(viewers), 100.0, 0.0)
    else:
        df['score_artikelen'] = 0.0

    purchases = get_user_purchases(base_pad, effective_db_url)
    if not purchases.empty and 'participant_id' in purchases.columns:
        buyers = set(pd.to_numeric(purchases['participant_id'], errors='coerce').dropna().astype(int))
        df['score_aankopen'] = np.where(df['participant_id'].isin(buyers), 100.0, 0.0)
    else:
        df['score_aankopen'] = 0.0

    # Challenges: store-level deelnemersratio, toegepast als store-kenmerk
    uc = _laad_user_challenges_per_store(effective_db_url)
    if not uc.empty:
        uc_ok = uc[uc['status'].astype(str).str.lower().isin(['completed', 'active', 'in_progress'])]
        challenge_per_store = (
            uc_ok.groupby('store_id')['user_ref']
            .nunique()
            .reset_index(name='n_challenge_deelnemers')
        )
        store_counts = df.groupby('store_id')['participant_id'].nunique().reset_index(name='n_store_users')
        challenge_per_store = challenge_per_store.merge(store_counts, on='store_id', how='left')
        challenge_per_store['pct_challenge_store'] = (
            challenge_per_store['n_challenge_deelnemers'] / challenge_per_store['n_store_users'].clip(lower=1) * 100
        ).clip(0, 100)
        df = df.merge(
            challenge_per_store[['store_id', 'pct_challenge_store']],
            on='store_id',
            how='left',
        )
        df['score_challenges'] = df['pct_challenge_store'].fillna(0.0)
    else:
        df['score_challenges'] = 0.0

    return df


def bereken_engagement_per_opdrachtgever(
    base_pad: Path,
    db_url: str | None = None,
    gewichten: dict | None = None,
    participant_ids: list | set | pd.Series | None = None,
) -> tuple[pd.DataFrame, float, pd.DataFrame]:
    """
    Aggregeer engagement naar opdrachtgever-niveau met gewogen samengestelde score.
    """
    gewichten = gewichten or ENGAGEMENT_COMPONENT_DEFAULTS.copy()
    totaal_gewicht = sum(gewichten.values()) or 1.0
    gewichten = {k: v / totaal_gewicht for k, v in gewichten.items()}

    df_users = bereken_gebruiker_engagement_scores(base_pad, db_url, participant_ids=participant_ids)
    if df_users.empty:
        return pd.DataFrame(), 0.0, pd.DataFrame()

    component_map = {
        'vragenlijst': 'score_vragenlijst',
        'herhaalmeting': 'score_herhaalmeting',
        'breedte': 'score_breedte',
        'artikelen': 'score_artikelen',
        'challenges': 'score_challenges',
        'aankopen': 'score_aankopen',
    }

    for key, col in component_map.items():
        if col in df_users.columns:
            df_users[f'w_{key}'] = df_users[col] * gewichten.get(key, 0.0)

    weight_cols = [f'w_{k}' for k in component_map if f'w_{k}' in df_users.columns]
    df_users['engagement_score'] = df_users[weight_cols].sum(axis=1).round(1)

    agg_spec = {
        'engagement_score': ('engagement_score', 'mean'),
        'n_deelnemers': ('participant_id', 'nunique'),
    }
    for key, col in component_map.items():
        if col in df_users.columns:
            agg_spec[f'comp_{key}'] = (col, 'mean')

    agg = (
        df_users.groupby(['store_id', 'store_name'], as_index=False)
        .agg(**agg_spec)
        .round(1)
    )
    agg['engagement_score'] = agg['engagement_score'].round(1)
    for col in [c for c in agg.columns if c.startswith('comp_')]:
        agg[col] = agg[col].round(1)

    benchmark = _weighted_average(agg['engagement_score'], agg['n_deelnemers'])
    if pd.isna(benchmark):
        benchmark = 0.0

    koppeling = controleer_gebruikers_koppeling(base_pad, db_url)
    return agg.sort_values('engagement_score', ascending=False), float(benchmark), koppeling


def controleer_gebruikers_koppeling(base_pad: Path, db_url: str | None = None) -> pd.DataFrame:
    """Controleer consistentie van gebruikerskoppeling over databronnen."""
    effective_db_url = db_url or DB_URL
    rows = []

    links = _laad_opdrachtgever_links(effective_db_url)
    n_participants_linked = int(links['participant_id'].nunique()) if not links.empty else 0
    rows.append({'Databron': 'Opdrachtgever-koppeling', 'Beschikbaar': n_participants_linked, 'Koppelbaar': n_participants_linked})

    bridge = _laad_participant_user_bridge(effective_db_url)
    n_bridge = int(bridge['participant_id'].nunique()) if not bridge.empty else 0
    rows.append({'Databron': 'Participant → user_id (my_clic)', 'Beschikbaar': n_bridge, 'Koppelbaar': n_bridge})

    df_scores = load_my_clic_participants_expanded(effective_db_url)
    n_scores = int(df_scores['participant_id'].nunique()) if not df_scores.empty and 'participant_id' in df_scores.columns else 0
    if not links.empty and n_scores:
        score_ids = set(pd.to_numeric(df_scores['participant_id'], errors='coerce').dropna().astype(int))
        link_ids = set(pd.to_numeric(links['participant_id'], errors='coerce').dropna().astype(int))
        koppelbaar = len(score_ids & link_ids)
        rows.append({'Databron': 'Vragenlijstscores', 'Beschikbaar': n_scores, 'Koppelbaar': koppelbaar})
    else:
        rows.append({'Databron': 'Vragenlijstscores', 'Beschikbaar': n_scores, 'Koppelbaar': 0})

    views = _laad_interaction_views(effective_db_url)
    n_views = int(views['user_id'].nunique()) if not views.empty else 0
    if not bridge.empty and n_views:
        bridge_users = set(bridge['user_id'].dropna().astype(int))
        koppelbaar = len(set(views['user_id'].dropna().astype(int)) & bridge_users)
        rows.append({'Databron': 'Artikelviews (interactions)', 'Beschikbaar': n_views, 'Koppelbaar': koppelbaar})
    else:
        rows.append({'Databron': 'Artikelviews (interactions)', 'Beschikbaar': n_views, 'Koppelbaar': 0})

    uc = _laad_user_challenges_per_store(effective_db_url)
    n_challenge_stores = int(uc['store_id'].nunique()) if not uc.empty else 0
    rows.append({
        'Databron': 'Challenges (store-niveau)',
        'Beschikbaar': n_challenge_stores,
        'Koppelbaar': n_challenge_stores,
        'Opmerking': 'Geen betrouwbare user-level koppeling; metric op store-niveau',
    })

    koppeling = pd.DataFrame(rows)
    if 'Opmerking' not in koppeling.columns:
        koppeling['Opmerking'] = ''
    if n_participants_linked:
        koppeling['Koppelingsgraad (%)'] = (koppeling['Koppelbaar'] / koppeling['Beschikbaar'].replace(0, pd.NA) * 100).round(1)
    return koppeling


def maak_engagement_opdrachtgever_ranking_plot(
    agg: pd.DataFrame,
    benchmark: float,
    min_deelnemers: int = 1,
    toon_klein: bool = True,
    lang: str = 'nl',
) -> go.Figure:
    """Horizontale ranking van engagement scores met benchmarklijn."""
    if agg.empty:
        return _empty_store_plot(tr("Geen engagementdata beschikbaar.", lang))

    df = agg.copy()
    if not toon_klein:
        df = df[df['n_deelnemers'] >= min_deelnemers]
    if df.empty:
        return _empty_store_plot(tr("Geen opdrachtgevers boven de drempel.", lang))

    df = df.sort_values('engagement_score', ascending=True)
    kleuren = ['#2ECC71' if s >= benchmark else '#E74C3C' for s in df['engagement_score']]
    waarschuwing = df['n_deelnemers'] < min_deelnemers

    fig = go.Figure(go.Bar(
        x=df['engagement_score'],
        y=df['store_name'],
        orientation='h',
        marker_color=kleuren,
        text=df.apply(
            lambda r: f"{r['engagement_score']:.1f} (n={int(r['n_deelnemers'])}{' ⚠' if r['n_deelnemers'] < min_deelnemers else ''})",
            axis=1,
        ),
        textposition='outside',
    ))
    fig.add_vline(
        x=benchmark, line_dash='dash', line_color='black',
        annotation_text=f'Benchmark ({benchmark:.1f})',
        annotation_position='top',
    )
    fig.update_layout(
        title=tr('Engagement score per opdrachtgever', lang),
        xaxis_title=tr('Engagement score (0-100)', lang),
        yaxis_title='',
        height=max(400, len(df) * 28),
        margin=dict(l=200, r=120),
        template='plotly_white',
    )
    fig.update_layout(meta={'kleine_stores': int(waarschuwing.sum())})
    return fig


def maak_engagement_breakdown_plot(agg: pd.DataFrame, store_name: str, lang: str = 'nl') -> go.Figure:
    """Gestapelde componenten voor één opdrachtgever."""
    if agg.empty or not store_name:
        return _empty_store_plot(tr("Geen data voor uitsplitsing.", lang))

    row = agg[agg['store_name'] == store_name]
    if row.empty:
        return _empty_store_plot(tr("Opdrachtgever niet gevonden.", lang))

    row = row.iloc[0]
    comp_labels = {
        'comp_vragenlijst': tr('Vragenlijst', lang),
        'comp_herhaalmeting': tr('Herhaalmeting', lang),
        'comp_breedte': tr('Breedte (meerdere vragenlijsten)', lang),
        'comp_artikelen': tr('Artikelen', lang),
        'comp_challenges': tr('Challenges (store)', lang),
        'comp_aankopen': tr('Aankopen', lang),
    }
    values = []
    labels = []
    for col, label in comp_labels.items():
        if col in row.index and pd.notna(row[col]):
            values.append(float(row[col]))
            labels.append(label)

    if not values:
        return _empty_store_plot(tr("Geen componentdata.", lang))

    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker_color=['#1F6FBF', '#3498DB', '#5DADE2', '#85C1E9', '#2ECC71', '#E87722'][:len(values)],
        text=[f'{v:.1f}' for v in values],
        textposition='outside',
    ))
    fig.update_layout(
        title=tr('Engagement uitsplitsing: {store}', lang).format(store=store_name),
        yaxis_title=tr('Component score (0-100)', lang),
        template='plotly_white',
        height=420,
    )
    return fig


def bereken_engagement_trend(
    base_pad: Path,
    db_url: str | None = None,
    gewichten: dict | None = None,
    min_deelnemers: int = 1,
    participant_ids: list | set | pd.Series | None = None,
) -> pd.DataFrame:
    """Maandelijkse engagement trend per opdrachtgever."""
    effective_db_url = db_url or DB_URL
    gewichten = gewichten or ENGAGEMENT_COMPONENT_DEFAULTS.copy()
    totaal_gewicht = sum(gewichten.values()) or 1.0
    gewichten = {k: v / totaal_gewicht for k, v in gewichten.items()}

    links = _laad_opdrachtgever_links(effective_db_url)
    df_comp = load_completions(effective_db_url)
    if links.empty or df_comp.empty:
        return pd.DataFrame()

    if participant_ids is not None:
        pids = set(pd.to_numeric(pd.Series(list(participant_ids)), errors='coerce').dropna().astype(int))
        links = links[pd.to_numeric(links['participant_id'], errors='coerce').isin(pids)]
        df_comp = df_comp[pd.to_numeric(df_comp['participant_id'], errors='coerce').isin(pids)]
        if links.empty or df_comp.empty:
            return pd.DataFrame()

    df_comp = df_comp.copy()
    df_comp['participant_id'] = pd.to_numeric(df_comp['participant_id'], errors='coerce')
    df_comp['created_at'] = pd.to_datetime(df_comp['created_at'], errors='coerce')
    df_comp = df_comp.dropna(subset=['participant_id', 'created_at'])
    df_comp = df_comp.merge(
        links[['participant_id', 'store_id', 'store_name']],
        on='participant_id',
        how='inner',
    )
    if df_comp.empty:
        return pd.DataFrame()

    df_comp['jaar_maand'] = df_comp['created_at'].dt.to_period('M').dt.to_timestamp()

    # Cumulatieve actieve deelnemers per store per maand
    maanden = sorted(df_comp['jaar_maand'].dropna().unique())
    trend_rows = []
    for store_id, store_df in df_comp.groupby('store_id'):
        store_name = store_df['store_name'].iloc[0]
        seen = set()
        for maand in maanden:
            nieuw = set(store_df[store_df['jaar_maand'] <= maand]['participant_id'].astype(int))
            seen |= nieuw
            n = len(seen)
            if n < 1:
                continue
            # Engagement-proxy: % deelnemers met ≥1 completion t/m deze maand (100) gewogen met herhaalratio
            comp_counts = store_df[store_df['jaar_maand'] <= maand].groupby('participant_id').size()
            pct_repeat = (comp_counts >= 2).mean() * 100 if len(comp_counts) else 0
            engagement_proxy = round(0.6 * 100 + 0.4 * pct_repeat, 1)
            trend_rows.append({
                'store_id': store_id,
                'store_name': store_name,
                'jaar_maand': maand,
                'engagement_score': engagement_proxy,
                'n_deelnemers': n,
            })

    trend = pd.DataFrame(trend_rows)
    if trend.empty:
        return trend

    trend = trend[trend['n_deelnemers'] >= max(1, min_deelnemers)]
    benchmark_per_month = (
        trend.groupby('jaar_maand')
        .apply(lambda g: _weighted_average(g['engagement_score'], g['n_deelnemers']), include_groups=False)
        .reset_index(name='benchmark')
    )
    trend = trend.merge(benchmark_per_month, on='jaar_maand', how='left')
    return trend


def maak_engagement_trend_plot(
    trend: pd.DataFrame,
    store_name: str | None = None,
    lang: str = 'nl',
) -> go.Figure:
    """Lijngrafiek engagement trend met benchmark."""
    if trend.empty:
        return _empty_store_plot(tr("Onvoldoende data voor trend.", lang))

    df = trend.copy()
    if store_name:
        df_store = df[df['store_name'] == store_name]
    else:
        df_store = (
            df.groupby('jaar_maand', as_index=False)
            .agg(
                engagement_score=('engagement_score', 'mean'),
                n_deelnemers=('n_deelnemers', 'sum'),
                benchmark=('benchmark', 'first'),
            )
        )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_store['jaar_maand'],
        y=df_store['engagement_score'],
        mode='lines+markers',
        name=store_name or tr('Gemiddelde', lang),
        line=dict(color=HOOFD_KLEUR, width=2),
    ))
    if 'benchmark' in df_store.columns:
        bench = df.groupby('jaar_maand')['benchmark'].first().reset_index()
        fig.add_trace(go.Scatter(
            x=bench['jaar_maand'],
            y=bench['benchmark'],
            mode='lines',
            name=tr('Benchmark (gewogen)', lang),
            line=dict(color='black', dash='dash'),
        ))
    fig.update_layout(
        title=tr('Engagement trend over tijd', lang),
        xaxis_title=tr('Maand', lang),
        yaxis_title=tr('Engagement score', lang),
        template='plotly_white',
        height=450,
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
    )
    return fig


def maak_periode_filter_visualisatie(base_pad: Path, db_url: str, lang: str = 'nl') -> go.Figure:
    """
    ✓ VRAAG 2: Kan je een periode selecteren of alleen data tot nu?
    
    Toont cumulatieve groei per jaar + kunnen kiezen welke periode weergegeven.
    """
    df_scores = load_my_clic_participants_expanded(db_url or DB_URL)
    
    if df_scores.empty or 'created_at' not in df_scores.columns:
        return _empty_store_plot(tr("Geen tijddata.", lang))
    
    df_scores['created_at'] = pd.to_datetime(df_scores['created_at'], errors='coerce')
    df_scores['jaar'] = df_scores['created_at'].dt.year
    
    # Cumulatieve groei
    jaren_counts = df_scores.groupby('jaar')['participant_id'].nunique().reset_index()
    jaren_counts['cumulatief'] = jaren_counts['participant_id'].cumsum()
    jaren_counts.columns = ['Jaar', 'Nieuwe deelnemers', 'Totaal cumulatief']
    
    fig = go.Figure()
    fig.add_trace(go.Bar(x=jaren_counts['Jaar'], y=jaren_counts['Nieuwe deelnemers'],
                         name=tr('Nieuwe deelnemers', lang), marker_color='#3498DB'))
    fig.add_trace(go.Scatter(x=jaren_counts['Jaar'], y=jaren_counts['Totaal cumulatief'],
                             name=tr('Totaal cumulatief', lang), line=dict(color='#E87722', width=3),
                             yaxis='y2', mode='lines+markers'))
    
    fig.update_layout(
        title=tr('Data beschikbaar per periode', lang),
        xaxis_title=tr('Jaar', lang),
        yaxis_title=tr('Nieuwe deelnemers', lang),
        yaxis2=dict(overlaying='y', side='right', title=tr('Totaal cumulatief', lang)),
        barmode='group',
        hovermode='x unified'
    )
    return fig


def maak_leeftijd_vs_scores_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    """
    ✓ VRAAG 3: Zou het ook mogelijk zijn op te filteren op leeftijd(categorie)?
    
    Toont leeftijdscategorieën met gemiddelde scores per categorie.
    """
    df = df.copy()
    df['rec_age_current'] = pd.to_numeric(df['rec_age_current'], errors='coerce')
    df['rec_ls_lifestyle_score'] = pd.to_numeric(df['rec_ls_lifestyle_score'], errors='coerce')
    
    # Maak leeftijdscategorieën
    df['leeftijd_cat'] = pd.cut(df['rec_age_current'],
                               bins=[0, 25, 35, 45, 55, 65, 150],
                               labels=['18-25', '26-35', '36-45', '46-55', '56-65', '65+'])
    
    df_group = df.dropna(subset=['leeftijd_cat', 'rec_ls_lifestyle_score']).groupby('leeftijd_cat', observed=True).agg(
        gemiddelde_score=('rec_ls_lifestyle_score', 'mean'),
        n=('rec_age_current', 'count'),
        std=('rec_ls_lifestyle_score', 'std')
    ).reset_index()
    
    fig = px.bar(df_group, x='leeftijd_cat', y='gemiddelde_score', error_y='std',
                 title=tr('Leefstijlscore naar leeftijdscategorie', lang),
                 labels={'leeftijd_cat': tr('Leeftijdsgroep', lang), 'gemiddelde_score': tr('Gem. leefstijlscore', lang)},
                 color_discrete_sequence=[HOOFD_KLEUR],
                 custom_data=['n'])
    
    fig.update_traces(customdata=df_group['n'], hovertemplate='<b>%{x}</b><br>Score: %{y:.2f}<br>N: %{customdata}')
    return fig


def maak_engagement_metrics_dashboard(base_pad: Path, db_url: str, lang: str = 'nl') -> tuple:
    """
    ✓ VRAAG 4: Zou je ook de engagement op het platform inzichtelijk kunnen maken?
    
    Toont engagement metrics: vragenlijsten, artikelen, challenges per opdrachtgever.
    """
    try:
        df_p = load_participants(db_url or DB_URL)
        df_c = load_completions(db_url or DB_URL)
        df_long = laad_longitudinale_data(base_pad, db_url or DB_URL)
        
        n_reg = len(df_p) if not df_p.empty else 0
        n_unique_completes = df_c['participant_id'].nunique() if not df_c.empty else 0
        pct_vragenlijsten = (n_unique_completes / max(n_reg, 1)) * 100 if n_reg > 0 else 0
        
        # Herhaalmeting engagement (2+ metingen)
        n_repeat = int((df_long.groupby('participant_id')['completion_id'].nunique() >= 2).sum()) if not df_long.empty else 0
        pct_repeat = (n_repeat / max(n_reg, 1)) * 100 if n_reg > 0 else 0
        
        # Metrics per opdrachtgever (als beschikbaar)
        links = _laad_opdrachtgever_links(db_url or DB_URL)
        
        metrics = pd.DataFrame([
            {'Metric': tr('Totaal geregistreerd', lang), 'Waarde': n_reg, 'Percentage': 100},
            {'Metric': tr('Vragenlijst ingevuld', lang), 'Waarde': n_unique_completes, 'Percentage': pct_vragenlijsten},
            {'Metric': tr('Herhaalmetingen gedaan', lang), 'Waarde': n_repeat, 'Percentage': pct_repeat},
        ])
        
        # Visualisatie
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=metrics['Metric'],
            y=metrics['Percentage'],
            text=metrics.apply(lambda r: f"{r['Waarde']:,} ({r['Percentage']:.0f}%)", axis=1),
            textposition='outside',
            marker_color=['#1F6FBF', '#2ECC71', '#E87722'],
            name=tr('Engagement %', lang)
        ))
        
        fig.update_layout(
            title=tr('Engagement Metrics: Participatiegraad per activiteit', lang),
            yaxis_title=tr('Percentage van totaal (%)', lang),
            xaxis_title='',
            showlegend=False,
            height=450
        )
        
        return fig, metrics
    except Exception as e:
        logger.error(f"Error in engagement metrics: {e}")
        return _empty_store_plot(tr("Fout bij laden engagement metrics.", lang)), pd.DataFrame()
