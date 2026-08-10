import sys
from pathlib import Path
import pandas as pd

# Zorg dat we de lokale modules kunnen laden
CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from data_ingestion import load_my_clic_participants_expanded, add_app_user_ids_and_addresses
from config import DB_URL

def count_filled_postcodes():
    print("Gegevens worden opgehaald uit de database...")
    # We laden de geconsolideerde data zoals het dashboard dat ook doet
    df = load_my_clic_participants_expanded(DB_URL)
    
    if df.empty:
        print("Fout: Geen data kunnen laden.")
        return

    # Verrijk de data met adresgegevens uit de tabel smart_health.addresses
    df_enriched = add_app_user_ids_and_addresses(df, DB_URL)

    # Check zowel de originele kolom als de toegevoegde kolom uit de adrestabel
    pc_col = 'postal_code' if 'postal_code' in df_enriched.columns else None
    
    if pc_col:
        gevuld = df_enriched[pc_col].notna().sum()
        totaal = len(df)
        print(f"\nResultaat:")
        print(f"  - Totaal aantal gebruikers: {totaal}")
        print(f"  - Gebruikers met ingevulde postal_code: {gevuld}")
    else:
        print("Kolom 'postal_code' niet gevonden in de geconsolideerde tabel.")

if __name__ == "__main__":
    count_filled_postcodes()