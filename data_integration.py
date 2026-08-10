"""
Smart Health Data Integration
Combineert nieuwe data met bestaande database via intelligent UPSERT.

Strategie:
- UPSERT: Insert nieuwe records, update bestaande (via Primary Key)
- Conflict handling: Bij duplicate keys, update alle columns behalve id
- Logging: Track welke tabellen gewijzigd zijn
- Backup: Optioneel backup van oude data vóór import
"""

import pandas as pd
import logging
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError
import json

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_integration.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class DataIntegrator:
    """Intelligente data integratie voor PostgreSQL met UPSERT en backup support."""
    
    def __init__(self, db_url, backup_before_import: bool = True):
        """
        Parameters:
        -----------
        db_url : str or Engine
            Database connection string or SQLAlchemy engine
        backup_before_import : bool
            Maak backup van tabellen vóór import
        """
        if hasattr(db_url, 'connect'):
            self.engine = db_url
        elif isinstance(db_url, str):
            self.engine = create_engine(db_url)
        else:
            self.engine = create_engine(str(db_url))
        self.backup_before_import = backup_before_import
        self.import_stats = {}
        
        # Test connection
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✓ Database connection successful")
        except Exception as e:
            logger.error(f"✗ Database connection failed: {e}")
            raise
    
    def get_primary_keys(self, table_name: str) -> list:
        """Haalt Primary Keys van een tabel op."""
        onderdelen = table_name.replace('"', '').split('.')
        schema = onderdelen[0] if len(onderdelen) > 1 else None
        pure_tabel = onderdelen[-1]
        inspector = inspect(self.engine)
        pk = inspector.get_pk_constraint(pure_tabel, schema=schema)
        return pk.get('constrained_columns', ['id']) if pk else ['id']
    
    def get_existing_columns(self, table_name: str) -> list:
        """Haalt bestaande kolommen van een tabel op."""
        onderdelen = table_name.replace('"', '').split('.')
        schema = onderdelen[0] if len(onderdelen) > 1 else None
        pure_tabel = onderdelen[-1]
        inspector = inspect(self.engine)
        columns = inspector.get_columns(pure_tabel, schema=schema)
        return [col['name'] for col in columns]
    
    def table_exists(self, table_name: str) -> bool:
        """Check of tabel bestaat."""
        onderdelen = table_name.replace('"', '').split('.')
        schema = onderdelen[0] if len(onderdelen) > 1 else None
        pure_tabel = onderdelen[-1]
        inspector = inspect(self.engine)
        return pure_tabel in inspector.get_table_names(schema=schema)
    
    def backup_table(self, table_name: str) -> str:
        """
        Maakt backup van een tabel.
        
        Returns:
        --------
        str : naam van backup tabel
        """
        backup_name = f"{table_name}_backup_{datetime.now():%Y%m%d_%H%M%S}"
        try:
            with self.engine.begin() as conn:
                conn.execute(text(
                    f"CREATE TABLE {backup_name} AS SELECT * FROM {table_name}"
                ))
            logger.info(f"✓ Backup created: {backup_name}")
            return backup_name
        except Exception as e:
            logger.error(f"✗ Backup failed for {table_name}: {e}")
            raise
    
    def upsert_dataframe(
        self,
        df: pd.DataFrame,
        table_name: str,
        primary_keys: list = None,
        create_if_missing: bool = True,
        backup_first: bool = None
    ) -> dict:
        """
        UPSERT pandas DataFrame naar database.
        
        - Nieuwe records: INSERT
        - Bestaande records (PK match): UPDATE
        
        Parameters:
        -----------
        df : pd.DataFrame
            Data om in te voegen
        table_name : str
            Doeltabel naam
        primary_keys : list, optional
            Primary key kolommen (auto-detect als None)
        create_if_missing : bool
            Maak tabel aan als deze niet bestaat
        backup_first : bool, optional
            Override global backup setting
        
        Returns:
        --------
        dict : {'inserted': int, 'updated': int, 'total': int}
        """
        if df.empty:
            logger.warning(f"⚠ Empty dataframe for {table_name}, skipping")
            return {'inserted': 0, 'updated': 0, 'total': 0}
        
        if self.engine.dialect.name == 'sqlite':
            df.to_sql(table_name, self.engine, if_exists='replace', index=False)
            stats = {
                'table': table_name,
                'total_rows_processed': len(df),
                'inserted': len(df),
                'updated': 0,
                'primary_keys': primary_keys or ['id'],
                'status': 'success'
            }
            self.import_stats[table_name] = stats
            logger.info(f"✓ {table_name}: {len(df)} rows saved to SQLite")
            return stats
        
        # Backup logic
        backup_enabled = backup_first if backup_first is not None else self.backup_before_import
        if backup_enabled and self.table_exists(table_name):
            self.backup_table(table_name)
        
        # Detecteer primary keys
        if primary_keys is None:
            if self.table_exists(table_name):
                primary_keys = self.get_primary_keys(table_name)
            else:
                primary_keys = ['id']
        
        if not isinstance(primary_keys, list):
            primary_keys = [primary_keys]
        
        # Valideer kolommen
        if self.table_exists(table_name):
            existing_cols = self.get_existing_columns(table_name)
            missing_cols = set(df.columns) - set(existing_cols)
            if missing_cols:
                logger.warning(f"⚠ New columns in {table_name}: {missing_cols}")
                # Voeg nieuwe kolommen toe
                with self.engine.begin() as conn:
                    for col in missing_cols:
                        col_type = self._infer_sql_type(df[col].dtype)
                        conn.execute(text(
                            f"ALTER TABLE {table_name} ADD COLUMN {col} {col_type}"
                        ))
                logger.info(f"✓ Added {len(missing_cols)} new columns to {table_name}")
        
        try:
            with self.engine.begin() as conn:
                # Maak temp tabel (voeg microseconden toe voor uniekheid)
                temp_table = f'temp_{table_name}_{datetime.now():%H%M%S%f}'
                df.to_sql(temp_table, conn, if_exists='replace', index=False)
                
                # Build UPSERT query
                all_cols = df.columns.tolist()
                pk_str = ', '.join(primary_keys)
                update_cols = [c for c in all_cols if c not in primary_keys]
                
                if not update_cols:
                    # Geen kolommen om te updaten (alleen PK)
                    update_clause = "DO NOTHING"
                else:
                    set_clause = ', '.join([f"{c} = EXCLUDED.{c}" for c in update_cols])
                    update_clause = f"DO UPDATE SET {set_clause}"
                
                cols_str = ', '.join(all_cols)
                
                # Check of tabel bestaat
                if not self.table_exists(table_name):
                    if create_if_missing:
                        logger.info(f"Creating new table: {table_name}")
                        # Copy temp table naar permanent
                        conn.execute(text(
                            f"CREATE TABLE {table_name} AS SELECT * FROM {temp_table}"
                        ))
                        # Als de tabel nieuw is, zijn alle rijen ingevoegd
                        inserted_count = len(df)
                        updated_count = 0
                    else:
                        raise ValueError(f"Table {table_name} doesn't exist and create_if_missing=False")
                else:
                    # UPSERT query
                    query = f"""
                    INSERT INTO {table_name} ({cols_str})
                    SELECT {cols_str} FROM {temp_table}
                    ON CONFLICT ({pk_str}) 
                    {update_clause}
                    RETURNING xmax = 0 AS inserted;
                    """
                    
                    # Voer de query uit en tel ingevoegde/bijgewerkte rijen
                    result = conn.execute(text(query))
                    for row in result:
                        if row.inserted:
                            inserted_count += 1
                        else:
                            updated_count += 1
                    total_processed = inserted_count + updated_count
                
                # Cleanup
                conn.execute(text(f"DROP TABLE {temp_table}"))
            
            # Stats
            stats = {
                'table': table_name,
                'total_rows_processed': total_processed,
                'inserted': inserted_count,
                'updated': updated_count,
                'primary_keys': primary_keys,
                'status': 'success'
            }
            self.import_stats[table_name] = stats
            
            logger.info(f"✓ {table_name}: {inserted_count} inserted, {updated_count} updated (PK: {pk_str})")
            return stats
            
        except Exception as e:
            logger.error(f"✗ UPSERT failed for {table_name}: {e}")
            raise
    
    def upsert_from_parquet(
        self,
        parquet_path: Path,
        table_name: str,
        primary_keys: list = None,
        **kwargs
    ) -> dict:
        """Lees Parquet bestand en UPSERT naar database."""
        parquet_path = Path(parquet_path)
        
        if not parquet_path.exists():
            logger.error(f"✗ File not found: {parquet_path}")
            raise FileNotFoundError(parquet_path)
        
        logger.info(f"Reading: {parquet_path}")
        df = pd.read_parquet(parquet_path)
        
        logger.info(f"UPSERT {len(df)} rows into {table_name}")
        return self.upsert_dataframe(df, table_name, primary_keys, **kwargs)
    
    def upsert_from_sql_dump(
        self,
        sql_file: Path,
        table_mappings: dict = None,
        execute_create_statements: bool = True
    ) -> dict:
        """
        Voer SQL dump uit met intelligent schema handling.
        
        Parameters:
        -----------
        sql_file : Path
            SQL file met DROP, CREATE, INSERT statements
        table_mappings : dict, optional
            Map table names {old_name: new_name} voor renames
        execute_create_statements : bool
            Voer CREATE TABLE statements uit (skip DROP voor UPSERT mode)
        
        Returns:
        --------
        dict : Execution stats
        """
        sql_file = Path(sql_file)
        
        if not sql_file.exists():
            logger.error(f"✗ SQL file not found: {sql_file}")
            raise FileNotFoundError(sql_file)
        
        with open(sql_file, 'r') as f:
            sql_content = f.read()
        
        # Parse statements
        statements = [s.strip() for s in sql_content.split(';') if s.strip()]
        
        stats = {'total_statements': len(statements), 'executed': 0, 'failed': 0}
        
        try:
            with self.engine.begin() as conn:
                # Zorg dat ongekwalificeerde tabelnamen in de juiste volgorde worden gezocht
                conn.execute(text("SET search_path TO smart_health, public"))
                for i, stmt in enumerate(statements, 1):
                    stmt_upper = stmt.upper()
                    
                    # Skip DROP TABLE statements (we're doing UPSERT)
                    if stmt_upper.startswith('DROP'):
                        logger.info(f"⊘ Skipping DROP statement (using UPSERT mode)")
                        continue
                    
                    # Skip CREATE TABLE statements (data-driven)
                    if execute_create_statements and stmt_upper.startswith('CREATE'):
                        logger.info(f"Executing CREATE statement")
                        try:
                            conn.execute(text(stmt))
                        except Exception as e:
                            if 'already exists' in str(e):
                                logger.info(f"⊘ Table already exists, skipping CREATE")
                            else:
                                raise
                        continue
                    
                    # Execute INSERT, UPDATE, andere statements
                    if stmt_upper.startswith('INSERT') or stmt_upper.startswith('UPDATE'):
                        try:
                            conn.execute(text(stmt))
                            stats['executed'] += 1
                            if (i % 100) == 0:
                                logger.info(f"Processed {i}/{len(statements)} statements")
                        except Exception as e:
                            logger.warning(f"Failed statement {i}: {e}")
                            stats['failed'] += 1
                    else:
                        # Andere statements
                        conn.execute(text(stmt))
                        stats['executed'] += 1
            
            logger.info(f"✓ SQL execution complete: {stats['executed']} executed, {stats['failed']} failed")
            return stats
            
        except Exception as e:
            logger.error(f"✗ SQL execution failed: {e}")
            raise
    
    def merge_data_sources(
        self,
        sources: list,
        table_configs: dict = None
    ) -> dict:
        """
        Merge meerdere data sources (Parquet, SQL dumps, DataFrames).
        
        Parameters:
        -----------
        sources : list of dict
            Elke source: {
                'type': 'parquet'|'sql'|'dataframe',
                'path'|'content'|'data': <path/sql/df>,
                'table': <table_name>,
                'primary_keys': [<list>],  # optional
            }
        table_configs : dict, optional
            Global table configs: {table_name: {primary_keys: [...]}}
        
        Returns:
        --------
        dict : merged stats
        """
        table_configs = table_configs or {}
        all_stats = {'sources_processed': 0, 'tables_updated': {}}
        
        for i, source in enumerate(sources, 1):
            logger.info(f"\n--- Processing source {i}/{len(sources)} ---")
            
            source_type = source.get('type', 'unknown')
            table_name = source.get('table', 'unknown_table')
            primary_keys = source.get('primary_keys') or table_configs.get(table_name, {}).get('primary_keys')
            
            try:
                if source_type == 'parquet':
                    stats = self.upsert_from_parquet(
                        source['path'],
                        table_name,
                        primary_keys=primary_keys
                    )
                
                elif source_type == 'dataframe':
                    stats = self.upsert_dataframe(
                        source['data'],
                        table_name,
                        primary_keys=primary_keys
                    )
                
                elif source_type == 'sql':
                    stats = self.upsert_from_sql_dump(
                        source['path'],
                        execute_create_statements=False
                    )
                
                else:
                    logger.warning(f"⚠ Unknown source type: {source_type}")
                    continue
                
                all_stats['sources_processed'] += 1
                all_stats['tables_updated'][table_name] = stats
                
            except Exception as e:
                logger.error(f"✗ Failed to process source {i}: {e}")
                all_stats['sources_processed'] -= 1
        
        return all_stats
    
    def get_summary(self) -> str:
        """Genereert samenvatting van import."""
        summary = "\n" + "="*60 + "\n"
        summary += "DATA INTEGRATION SUMMARY\n"
        summary += "="*60 + "\n"
        
        for table_name, stats in self.import_stats.items():
            summary += f"\n{table_name}:\n"
            summary += f"  Rows: {stats.get('total_rows', 'unknown')}\n"
            summary += f"  Primary Keys: {', '.join(stats.get('primary_keys', ['id']))}\n"
            summary += f"  Status: {stats.get('status', 'unknown')}\n"
        
        summary += "\n" + "="*60 + "\n"
        return summary
    
    @staticmethod
    def _infer_sql_type(dtype) -> str:
        """Infer SQL type van pandas dtype."""
        dtype_str = str(dtype).lower()
        if 'int' in dtype_str:
            return 'INTEGER'
        elif 'float' in dtype_str:
            return 'DECIMAL(10,2)'
        elif 'bool' in dtype_str:
            return 'BOOLEAN'
        elif 'datetime' in dtype_str:
            return 'TIMESTAMP'
        else:
            return 'TEXT'


# ══════════════════════════════════════════════════════════════════════════════
# USAGE EXAMPLES
# ══════════════════════════════════════════════════════════════════════════════

def example_simple_upsert():
    """Voorbeeld 1: Simpele UPSERT van Parquet bestand."""
    from config import DB_URL
    
    integrator = DataIntegrator(DB_URL, backup_before_import=True)
    
    # UPSERT orders
    integrator.upsert_from_parquet(
        Path('new_data/orders.parquet'),
        'orders',
        primary_keys=['id']
    )
    
    # UPSERT users
    integrator.upsert_from_parquet(
        Path('new_data/users.parquet'),
        'users_mysql',
        primary_keys=['id']
    )
    
    print(integrator.get_summary())


def example_merge_multiple_sources():
    """Voorbeeld 2: Merge meerdere data sources."""
    from config import DB_URL, CODE_DIR
    
    integrator = DataIntegrator(DB_URL, backup_before_import=True)
    
    sources = [
        {
            'type': 'parquet',
            'path': CODE_DIR / 'users_met_scores.parquet',
            'table': 'users_met_scores',
            'primary_keys': ['user_id']
        },
        {
            'type': 'parquet',
            'path': CODE_DIR / 'factor_score_histories.parquet',
            'table': 'factor_score_histories',
            'primary_keys': ['id']
        },
        {
            'type': 'sql',
            'path': Path('new_data/insert_statements.sql'),
            'table': 'orders'
        },
    ]
    
    stats = integrator.merge_data_sources(sources)
    print(json.dumps(stats, indent=2))


def example_sql_dump_with_upsert():
    """Voorbeeld 3: Voer SQL dump uit in UPSERT mode (skip DROP)."""
    from config import DB_URL
    
    integrator = DataIntegrator(DB_URL, backup_before_import=True)
    
    # De SQL file mag DROP/CREATE statements bevatten - deze worden geskipped
    # Alleen INSERT statements worden uitgevoerd in UPSERT mode
    stats = integrator.upsert_from_sql_dump(
        Path('new_data/full_backup.sql'),
        execute_create_statements=False  # Skip CREATE TABLE statements
    )
    
    logger.info(f"Executed: {stats['executed']}, Failed: {stats['failed']}")


if __name__ == '__main__':
    # Kies een voorbeeld
    example_simple_upsert()
    # example_merge_multiple_sources()
    # example_sql_dump_with_upsert()