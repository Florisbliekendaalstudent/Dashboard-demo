import pandas as pd
import streamlit as st
from pathlib import Path

from config import DB_URL

# Lokale instellingen
CODE_DIR = Path(__file__).resolve().parent

class DataManager:
    """Centrale laag voor data-opvraging en filtering."""
    
    @staticmethod
    @st.cache_data
    def get_raw_data() -> pd.DataFrame:
        """Laadt de basis dataset."""
        df = pd.read_parquet(CODE_DIR / 'users_met_scores.parquet')
        return df.drop_duplicates(subset='user_id', keep='first').reset_index(drop=True)

    @staticmethod
    @st.cache_data
    def get_longitudinal_data() -> pd.DataFrame:
        """Laadt historische data."""
        # Import hier om circulaire imports te voorkomen
        from visualisaties import laad_longitudinale_data
        return laad_longitudinale_data(CODE_DIR, DB_URL)

    @staticmethod
    def apply_global_filters(df: pd.DataFrame) -> pd.DataFrame:
        """Past filters toe op basis van st.session_state."""
        if df is None or df.empty:
            return df
            
        filtered_df = df.copy()
        geslacht = st.session_state.get('global_geslacht', 'beide')
        if geslacht == 'man':
            filtered_df = filtered_df[pd.to_numeric(filtered_df['rec_user_gender'], errors='coerce') == 1]
        elif geslacht == 'vrouw':
            filtered_df = filtered_df[pd.to_numeric(filtered_df['rec_user_gender'], errors='coerce') == 0]
        return filtered_df

    @staticmethod
    def get_filtered_data() -> pd.DataFrame:
        """Helper die ruwe data haalt en direct de globale filters toepast."""
        df = DataManager.get_raw_data()
        return DataManager.apply_global_filters(df)