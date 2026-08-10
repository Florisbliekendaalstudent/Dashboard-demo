import pandas as pd
from pathlib import Path
import sys

# Projectpaden instellen
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from config import TABLES_DIR, setup_logger, DB_URL, setup_logger
from data_ingestion import upload_dataframe_to_database, generate_consolidated_scores_in_db, generate_store_averages_in_db, create_engine, inspect

logger = setup_logger(__name__)

def detecteer_skiprows(pad: Path) -> int:
    """
    Zoekt automatisch naar de regel waar de CSV-data begint door te kijken naar bekende headers.
    """
    # Uitgebreide zoektermen om ook door SQL dumps heen te kijken
    zoektermen = ['Participant ID', 'participant_id', 'User ID', 'ID,', '"id"', 'COPY ', 'INSERT INTO']
    try:
        with open(pad, 'r', encoding='utf-8-sig', errors='ignore') as f:
            for i, line in enumerate(f):
                # Zoek naar een regel die een van de termen bevat en waarschijnlijk de header is
                if any(term in line for term in zoektermen) and (',' in line or ';' in line or '\t' in line):
                    logger.info(f"✨ Header automatisch gedetecteerd op regel {i+1}")
                    return i
    except Exception as e:
        logger.warning(f"Kon header niet automatisch detecteren: {e}")
    return 0

def get_table_row_count(engine, table_name):
    try:
        with engine.connect() as conn:
            result = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            return result.scalar()
    except:
        return 0

def valideer_en_schoon_data(df: pd.DataFrame, tabelnaam: str, engine) -> pd.DataFrame:
    """
    Controleert of de kolommen in de CSV overeenkomen met de database.
    Hernoemt kolommen op basis van een mapping en filtert onbekende kolommen eruit.
    """
    # Splits schema van tabelnaam voor validatie
    onderdelen = tabelnaam.replace('"', '').split('.')
    schema = onderdelen[0] if len(onderdelen) > 1 else None
    pure_tabel = onderdelen[-1]

    inspector = inspect(engine)
    db_cols = [c['name'] for c in inspector.get_columns(pure_tabel, schema=schema)]
    
    # --- MAPPING: Pas dit aan als je CSV andere namen gebruikt dan de database ---
    # Formaat: 'Naam_In_CSV': 'naam_in_database'
    mapping = {
        'Participant ID': 'id',
        'participant_id': 'id',
        'ID': 'id',
        'User ID': 'user_id',
        'user_id': 'user_id',
        'Pmo ID': 'pmo_id',
        'pmo_id': 'pmo_id',
        'Datum': 'created_at',
        'Aangemaakt': 'created_at',
        'Created At': 'created_at',
        'created_at': 'created_at',
        'Bijgewerkt': 'updated_at',
        'Updated At': 'updated_at',
        'updated_at': 'updated_at',
        'Datum invullen': 'completion_created_at',
        'Geboortedatum': 'date_of_birth',
        'Geslacht': 'gender',
        'Postcode': 'postal_code',
        'Leefstijlscore': 'rec_ls_lifestyle_score', 'leefstijlscore': 'rec_ls_lifestyle_score',
        'BMI': 'rec_med_bmi', 'bmi': 'rec_med_bmi',
        'Stress Score': 'rec_ls_stress_sum', 'stress_score': 'rec_ls_stress_sum',
        'Hartrisico': 'rec_heartrisk', 'hartrisico': 'rec_heartrisk',
        'Heartrisk': 'rec_heartrisk',
        'Slaapscore': 'rec_ls_sleep_psqi_sum', 'slaapscore': 'rec_ls_sleep_psqi_sum',
        'Sleep score': 'rec_ls_sleep_psqi_sum',
        'Veerkracht': 'rec_resilience_score', 'veerkracht': 'rec_resilience_score',
        'Resilience': 'rec_resilience_score',
        'Beweegscore': 'rec_ls_score_exercise', 'beweegscore': 'rec_ls_score_exercise',
        'Exercise score': 'rec_ls_score_exercise'
    }
    
    df = df.rename(columns=mapping)
    
    # --- NIEUW: Zorg dat user_id gevuld is (essentieel voor dashboard) ---
    if 'user_id' in db_cols:
        if 'user_id' not in df.columns and 'id' in df.columns:
            df['user_id'] = df['id']
            logger.info("ℹ️ 'user_id' automatisch gevuld vanuit 'id'.")
        elif 'user_id' in df.columns:
            df['user_id'] = df['user_id'].fillna(df['id']) if 'id' in df.columns else df['user_id']

    # --- NIEUW: Datum kolommen parsen en opschonen ---
    # Dit zorgt ervoor dat data tot en met 2030 correct herkend wordt
    datum_kolommen = ['created_at', 'updated_at', 'date_of_birth', 'completion_created_at']
    for col in datum_kolommen:
        if col in df.columns:
            logger.info(f"📅 Datumkolom '{col}' parsen...")
            # errors='coerce' maakt ongeldige datums 'NaT' (Not a Time)
            # dayfirst=True helpt bij formaten zoals 31-01-2030
            df[col] = pd.to_datetime(df[col], errors='coerce', dayfirst=True)
            
    # Zorg dat er altijd een created_at is voor de tijd-as in het dashboard
    if 'created_at' in db_cols:
        if 'created_at' not in df.columns or df['created_at'].isna().all():
            if 'created_at' not in df.columns:
                df['created_at'] = pd.Timestamp.now()
                logger.info("🕒 Kolom 'created_at' toegevoegd met huidige tijd.")
            else:
                # Alleen lege rijen vullen
                df['created_at'] = df['created_at'].fillna(pd.Timestamp.now())

    # Log welke kolommen NIET in de database voorkomen en dus genegeerd worden
    onbekende_kolommen = [c for c in df.columns if c not in db_cols]
    
    # Extra check op separator
    if len(df.columns) <= 1 and len(db_cols) > 5:
        logger.error(f"❌ Slechts {len(df.columns)} kolom gevonden. Is de separator (komma) wel juist?")
        logger.info(f"Headers gevonden: {df.columns.tolist()}")

    if onbekende_kolommen:
        logger.warning(f"⚠️ De volgende kolommen uit de CSV worden NIET geüpload (onbekend in DB): {onbekende_kolommen}")
        logger.info(f"💡 Tip: Voeg deze toe aan de 'mapping' dictionary in dit script als ze hernoemd moeten worden.")
    
    # Filter: behoud alleen kolommen die daadwerkelijk in de database tabel bestaan
    geaccepteerde_kolommen = [c for c in df.columns if c in db_cols]
    
    if len(geaccepteerde_kolommen) == 0:
        logger.warning(f"⚠️ Geen bekende kolommen gevonden, we proberen de kolommen uit de mapping te forceren.")
        geforceerde_kolommen = [v for v in mapping.values() if v in df.columns]
        if not geforceerde_kolommen:
             return pd.DataFrame()
        geaccepteerde_kolommen = geforceerde_kolommen

    logger.info(f"✅ {len(geaccepteerde_kolommen)} kolommen komen overeen en worden geüpload.")
    
    # Verwijder duplicates binnen het bestand zelf
    df_result = df[geaccepteerde_kolommen].copy()
    if 'id' in df_result.columns:
        df_result = df_result.drop_duplicates(subset=['id'], keep='last')
            
    return df_result

def voer_import_uit(bestandsnaam: str, tabelnaam: str, skiprows: int = 0):
    pad = TABLES_DIR / bestandsnaam
    
    if not pad.exists():
        logger.error(f"Bestand niet gevonden: {pad}")
        return
    
    logger.info(f"Inlezen van {bestandsnaam}...")
    try:
        if pad.suffix == '.csv':
            # Als skiprows handmatig op 0 staat, proberen we het automatisch te detecteren
            # Dit negeert de SQL-code bovenin de export.
            if skiprows == 0:
                skiprows = detecteer_skiprows(pad)
            else:
                logger.info(f"Gebruik handmatige skip van {skiprows} regels.")
                
            df = pd.read_csv(pad, skiprows=skiprows, sep=None, engine='python', encoding='utf-8-sig')
        elif pad.suffix == '.sql':
            logger.info(f"🚀 SQL dump gedetecteerd. Starten van direct SQL import via DataIntegrator...")
            from data_integration import DataIntegrator
            integrator = DataIntegrator(DB_URL, backup_before_import=False)
            stats = integrator.upsert_from_sql_dump(pad, execute_create_statements=False)
            logger.info(f"✓ SQL import voltooid: {stats['executed']} statements uitgevoerd.")
            # Bij een SQL dump hoeven we de rest van de DataFrame-logica niet uit te voeren
            return
        elif pad.suffix in ['.xlsx', '.xls']:
            df = pd.read_excel(pad)
        else:
            logger.error("Bestandstype niet ondersteund. Gebruik .csv of .xlsx")
            return

        engine = create_engine(DB_URL)
        
        # Check bestand grootte vs skiprows
        totaal_regels = len(df) + skiprows
        if len(df) == 0:
            logger.error(f"❌ Fout: Na het overslaan van {skiprows} regels is het bestand LEEG.")
            logger.info(f"Het bestand {bestandsnaam} heeft in totaal {totaal_regels} regels.")
            if skiprows > 0:
                logger.info("💡 Tip: Zet 'skip' op 0 in de takenlijst onderaan dit script.")
            return

        count_before = get_table_row_count(engine, tabelnaam)
        
        # Directe preview van wat er uit het bestand komt
        logger.info(f"📊 Bestand ingelezen: {len(df)} regels gevonden (na overslaan van {skiprows}).")
        print("\n--- RUWE DATA PREVIEW (Eerste 3 rijen) ---")
        print(df.head(3).to_string())
        print("------------------------------------------\n")

        # Data opschonen en layout matchen met de database
        df_clean = valideer_en_schoon_data(df, tabelnaam, engine)
        
        if df_clean is None or df_clean.empty:
            logger.error(f"Import afgebroken voor {bestandsnaam} wegens layout-fouten.")
            return
            
        # Verwijder duplicaten binnen het dataframe zelf voordat we naar de DB gaan
        if 'id' in df_clean.columns:
            aantal_voor = len(df_clean)
            df_clean = df_clean.drop_duplicates(subset=['id'], keep='last')
            if len(df_clean) < aantal_voor:
                logger.info(f"Filtered {aantal_voor - len(df_clean)} duplicate IDs within the file.")

        logger.info("👀 Preview van de GEFILTERDE data voor upload:")
        print(df_clean.head().to_string())

        logger.info(f"✅ Data gevalideerd. {len(df_clean)} rijen klaar voor upload.")
        logger.info(f"📋 Kolommen die worden gevuld: {', '.join(df_clean.columns.tolist())}")

        # Upload naar de database
        logger.info(f"🚀 Starten van upload naar tabel '{tabelnaam}'...")
        success = upload_dataframe_to_database(df_clean, tabelnaam, primary_keys=['id'])
        
        if success:
            count_after = get_table_row_count(engine, tabelnaam)
            toegevoegd = count_after - count_before
            if toegevoegd > 0:
                print(f"Hoera! Er zijn {toegevoegd} nieuwe rijen toegevoegd aan '{tabelnaam}'.")
                print(f"\n🎉 Succes! De data uit '{bestandsnaam}' is verwerkt.")
            else:
                print(f"⚠️ Waarschuwing: Upload geslaagd, maar het aantal rijen in de database is niet toegenomen. Mogelijk zijn alle IDs al aanwezig.")
            
    except Exception as e:
        logger.error(f"Fout bij verwerken: {e}")

def toon_beschikbare_bestanden():
    """Handige helper om te zien welke bestanden er klaarstaan."""
    bestanden = list(TABLES_DIR.glob('*.csv')) + list(TABLES_DIR.glob('*.xlsx')) + list(TABLES_DIR.glob('*.sql'))
    if not bestanden:
        print(f"\nℹ️ Geen bestanden gevonden in map: {TABLES_DIR}")
    else:
        print(f"\n📂 Beschikbare bestanden in '{TABLES_DIR.name}':")
        for b in bestanden:
            print(f"  - {b.name}")
    print("")

if __name__ == "__main__":
    # --- LIJST VAN BESTANDEN OM TE UPLOADEN ---
    # Pas hier de bestandsnamen aan naar de daadwerkelijke bestanden in de map 'Tabellen'.
    # 1. Toon eerst wat er in de map staat
    toon_beschikbare_bestanden()

    # 2. CONFIGURATIE: Voeg hier je bestanden toe die je wilt importeren.
    # De DataIntegrator zorgt ervoor dat duplicaten op basis van 'id' worden afgehandeld.
    taken = [
        # SQL bestanden: het script voert ALLE SQL statements in het bestand uit.
        # De 'table' parameter is hier een beschrijvende label voor de logging.
        {"file": "sh-2026-04-23.sql", "table": "algemene_update", "skip": 0},
        {"file": "sh_questionnaire-2026-04-23.sql", "table": "vragenlijsten_update", "skip": 0},
    ]

    for taak in taken:
        logger.info(f"--- Verwerken van {taak['file']} ---")
        print(f"\n--- 🚀 Verwerken van {taak['file']} ---")
        voer_import_uit(
            taak['file'], 
            taak['table'], 
            skiprows=taak['skip']
        )

    # BELANGRIJK: Na het uploaden van ruwe data moeten we de 
    # 'users_met_scores' tabel verversen zodat het dashboard de nieuwe data ziet.
    logger.info("--- Dashboard data synchroniseren ---")
    try:
        engine = create_engine(DB_URL)
        s1, m1 = generate_consolidated_scores_in_db(engine)
        s2, m2 = generate_store_averages_in_db(engine)
        
        if s1 and s2:
            print("\n✅ Dashboard data is succesvol bijgewerkt!")
            print("Je kunt nu het dashboard refreshen om de nieuwe resultaten te zien.")
        else:
            print(f"\n⚠️ Fout bij synchroniseren: {m1} | {m2}")
    except Exception as e:
        logger.error(f"Synchronisatie mislukt: {e}")