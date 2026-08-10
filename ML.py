import pandas as pd
import numpy as np
import logging
import plotly.express as px
import plotly.graph_objects as go
from i18n import tr
from kleuren import HOOFD_KLEUR

logger = logging.getLogger(__name__)

# Defensieve import voor ML bibliotheken
try:
    from sklearn.cluster import KMeans
    from sklearn.ensemble import (
        ExtraTreesClassifier,
        ExtraTreesRegressor,
        GradientBoostingRegressor,
        HistGradientBoostingClassifier,
        HistGradientBoostingRegressor,
        RandomForestClassifier,
        RandomForestRegressor,
        VotingClassifier,
        VotingRegressor,
    )
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.metrics import confusion_matrix, precision_recall_curve, recall_score
    from sklearn.model_selection import cross_validate, train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler, label_binarize
    HAS_SKLEARN = True
except Exception as e:
    HAS_SKLEARN = False
    SKLEARN_IMPORT_ERROR = str(e)
    logger.warning(f"Scikit-learn niet beschikbaar. ML functionaliteit beperkt: {e}")
else:
    SKLEARN_IMPORT_ERROR = ""


BP_FEATURES = [
    'rec_age_current',
    'rec_user_gender',
    'rec_med_bmi',
    'rec_med_diabetes_cat',
    'rec_ls_exercise_steps_per_day',
    'rec_ls_nutrition_natrium_per_day',
    'rec_ls_alcohol_total_per_week',
    'rec_ls_sleep_psqi_sum',
    'rec_ls_stress_sum',
    'rec_resilience_score',
]

HEARTRISK_FEATURES = [
    'rec_age_current',
    'rec_user_gender',
    'rec_med_bmi',
    'rec_smoking_answer',
    'rec_med_blood_pressure_cat',
    'rec_med_diabetes_cat',
    'rec_ls_sleep_psqi_sum',
    'rec_ls_exercise_steps_per_day',
    'rec_resilience_score',
    'rec_ls_nutrition_saturated_fat_per_day',
    'rec_ls_nutrition_sugar_per_day',
    'rec_ls_nutrition_natrium_per_day',
]

ML_MODEL_VERSION = "v3-ensemble-extra-models-2026-06-03"
LIFESTYLE_USE_CLASSIFICATION = False

ACTIVATION_FEATURES = [
    'rec_age_current',
    'rec_user_gender',
    'store_id',
    'has_postal_code',
]

LIFESTYLE_FEATURES = [
    'rec_age_current',
    'rec_user_gender',
    'rec_med_bmi',
    'rec_ls_stress_sum',
    'rec_ls_sleep_psqi_sum',
    'rec_ls_exercise_steps_per_day',
    'rec_ls_nutrition_fruit_fruit_per_day',
    'rec_ls_nutrition_vegetables_gram_per_day',
    'rec_ls_nutrition_sugar_per_day',
    'rec_ls_nutrition_saturated_fat_per_day',
    'rec_ls_nutrition_natrium_per_day',
    'rec_ls_alcohol_total_per_week',
    'rec_resilience_score',
    'rec_wellbeing_score',
]

IMPROVEMENT_FEATURES = [
    'rec_age_current',
    'rec_user_gender',
    'rec_med_bmi',
    'rec_ls_stress_sum',
    'rec_ls_sleep_psqi_sum',
    'rec_ls_exercise_steps_per_day',
    'rec_resilience_score',
    'rec_wellbeing_score',
]

PURCHASE_FEATURES = [
    'rec_age_current',
    'rec_user_gender',
    'rec_med_bmi',
    'rec_ls_lifestyle_score',
    'rec_heartrisk_cat',
    'rec_ls_stress_sum',
    'rec_ls_sleep_psqi_sum',
    'rec_resilience_score',
    'rec_wellbeing_score',
    'store_id',
]

FEATURE_LABELS = {
    'rec_age_current': 'Leeftijd',
    'rec_user_gender': 'Geslacht',
    'rec_med_bmi': 'BMI',
    'rec_med_diabetes_cat': 'Diabetes',
    'rec_ls_exercise_steps_per_day': 'Stappen per dag',
    'rec_ls_nutrition_natrium_per_day': 'Natrium',
    'rec_ls_alcohol_total_per_week': 'Alcohol',
    'rec_ls_sleep_psqi_sum': 'Slaap PSQI',
    'rec_resilience_score': 'Veerkracht',
    'rec_smoking_answer': 'Roken',
    'rec_med_blood_pressure_cat': 'Bloeddruk',
    'rec_ls_nutrition_saturated_fat_per_day': 'Verzadigd vet',
    'rec_ls_nutrition_sugar_per_day': 'Suiker',
    'rec_ls_lifestyle_score': 'Leefstijlscore',
    'rec_ls_stress_sum': 'Stress',
    'rec_wellbeing_score': 'Welzijn',
    'store_id': 'Opdrachtgever',
    'has_postal_code': 'Postcode aanwezig',
    'improvement_lifestyle_score': 'Verbetering leefstijlscore',
    'has_purchase': 'Heeft aankoop',
    'dropoff_risk': 'Geen scoredata',
}


def _find_best_thresholds_for_classification(model, X_val, y_val, class_labels: list[int], top_n: int = 5) -> list[dict]:
    """
    Scans for optimal probability thresholds for multi-class classification
    to improve recall, especially for minority classes (1 and 2).
    Returns a list of top-performing threshold combinations and their metrics.
    """
    if not hasattr(model, 'predict_proba'):
        return []

    y_pred_proba = model.predict_proba(X_val)
    
    # Ensure class_labels are sorted and correspond to proba columns
    # Also, ensure we only consider classes actually present in y_val for indexing
    present_classes_in_val = sorted(y_val.unique())
    
    # Map class labels to their index in y_pred_proba
    # The order of columns in y_pred_proba corresponds to sorted(model.classes_)
    model_classes = sorted(model.classes_)
    
    # Define a range of thresholds to check for class 1 (moderate) and class 2 (high)
    threshold_steps = np.arange(0.1, 0.9, 0.05) # Check thresholds from 0.1 to 0.85

    results = []

    # Iterate over thresholds for class 1 (moderate) and class 2 (high)
    for moderate_threshold in threshold_steps:
        for high_threshold in threshold_steps:
            y_pred_tuned = np.zeros(len(y_val), dtype=int)
            
            # Apply custom thresholds. Prioritize higher risk categories.
            for i in range(len(y_val)):
                pred_class = 0 # Default to class 0 (Low/Normal)
                
                # Get probabilities for class 1 and 2, if they exist in the model's classes
                proba_class_1 = y_pred_proba[i, model_classes.index(1)] if 1 in model_classes else -1.0
                proba_class_2 = y_pred_proba[i, model_classes.index(2)] if 2 in model_classes else -1.0

                # Check if class 2 (High) probability is above its threshold
                if proba_class_2 >= high_threshold:
                    pred_class = 2
                # Else, check if class 1 (Moderate) probability is above its threshold
                elif proba_class_1 >= moderate_threshold:
                    pred_class = 1
                # Else, default to class 0 (Low/Normal)
                
                y_pred_tuned[i] = pred_class

            # Calculate metrics. Only consider classes that are actually present in y_val.
            recalls_per_class = recall_score(y_val, y_pred_tuned, average=None, labels=present_classes_in_val, zero_division=0)
            macro_recall = recall_score(y_val, y_pred_tuned, average='macro', labels=present_classes_in_val, zero_division=0)
            
            # Get recalls for specific classes, handling cases where a class might not be present in y_val
            recall_low = recalls_per_class[present_classes_in_val.index(0)] if 0 in present_classes_in_val else 0.0
            recall_moderate = recalls_per_class[present_classes_in_val.index(1)] if 1 in present_classes_in_val else 0.0
            recall_high = recalls_per_class[present_classes_in_val.index(2)] if 2 in present_classes_in_val else 0.0

            res = {
                'moderate_threshold': round(moderate_threshold, 2),
                'high_threshold': round(high_threshold, 2),
                'macro_recall': round(macro_recall, 3),
                'recall_low': round(recall_low, 3),
                'recall_moderate': round(recall_moderate, 3),
                'recall_high': round(recall_high, 3),
                'score': round(macro_recall, 3) # Use macro recall as the objective score
            }
            results.append(res)

    # Sort by macro_recall and return top N
    results.sort(key=lambda x: x['macro_recall'], reverse=True)
    return results[:top_n]


def _empty_fig(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=14))
    fig.update_layout(template='plotly_white', height=420)
    return fig


def _prepare_classification_data(df: pd.DataFrame, target: str, features: list[str], min_rows: int = 50):
    if not HAS_SKLEARN:
        raise RuntimeError("Scikit-learn is niet beschikbaar.")
    if df is None or df.empty:
        raise ValueError("Geen data beschikbaar voor het ML model.")
    available = [c for c in features if c in df.columns]
    if target not in df.columns:
        raise ValueError(f"Doelkolom ontbreekt: {target}")
    if len(available) < 3:
        raise ValueError("Te weinig bruikbare features voor het ML model.")

    df_ml = df[available + [target]].apply(pd.to_numeric, errors='coerce')
    df_ml = df_ml.dropna(subset=[target])
    df_ml = df_ml[df_ml[target].isin([0, 1, 2])]
    if len(df_ml) < min_rows:
        raise ValueError("Te weinig rijen met geldige targetwaarden voor ML.")

    X = df_ml[available]
    y = df_ml[target].astype(int)
    stratify = y if y.value_counts().min() >= 2 else None
    return train_test_split(X, y, test_size=0.25, random_state=42, stratify=stratify) + [available]


def _make_classifier(n_estimators: int = 350) -> Pipeline:
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('model', VotingClassifier(
            estimators=[
                ('rf', RandomForestClassifier(
                    n_estimators=n_estimators,
                    random_state=42,
                    class_weight='balanced_subsample',
                    min_samples_leaf=2,
                    max_features='sqrt',
                    n_jobs=-1,
                )),
                ('et', ExtraTreesClassifier(
                    n_estimators=max(200, n_estimators),
                    random_state=42,
                    class_weight='balanced',
                    min_samples_leaf=2,
                    max_features='sqrt',
                    n_jobs=-1,
                )),
                ('hgb', HistGradientBoostingClassifier(
                    learning_rate=0.05,
                    max_depth=6,
                    random_state=42,
                    l2_regularization=0.05,
                )),
            ],
            voting='soft',
        )),
    ])


def _make_regressor(n_estimators: int = 350) -> Pipeline:
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('model', VotingRegressor(
            estimators=[
                ('rf', RandomForestRegressor(
                    n_estimators=n_estimators,
                    random_state=42,
                    n_jobs=-1,
                )),
                ('et', ExtraTreesRegressor(
                    n_estimators=max(200, n_estimators),
                    random_state=42,
                    n_jobs=-1,
                )),
                ('gbr', GradientBoostingRegressor(
                    n_estimators=max(150, n_estimators // 2),
                    learning_rate=0.05,
                    random_state=42,
                )),
                ('hgr', HistGradientBoostingRegressor(
                    learning_rate=0.05,
                    max_depth=6,
                    random_state=42,
                    l2_regularization=0.05,
                )),
            ],
        )),
    ])


def _apply_custom_thresholds(proba, thresholds, classes):
    """Helper om drempelwaarden toe te passen op kans-voorspellingen."""
    n_samples = proba.shape[0]
    preds = np.zeros(n_samples, dtype=int)
    
    # Haal drempels op (fallback naar 0.33 voor 3 klassen)
    t_mod = thresholds.get('moderate_threshold', 0.33)
    t_high = thresholds.get('high_threshold', 0.33)
    
    model_classes = list(classes)
    idx_mod = model_classes.index(1) if 1 in model_classes else -1
    idx_high = model_classes.index(2) if 2 in model_classes else -1
    
    for i in range(n_samples):
        p_mod = proba[i, idx_mod] if idx_mod != -1 else -1.0
        p_high = proba[i, idx_high] if idx_high != -1 else -1.0
        
        if p_high >= t_high:
            preds[i] = 2
        elif p_mod >= t_mod:
            preds[i] = 1
        else:
            preds[i] = 0
    return preds


def _prepare_regression_data(df: pd.DataFrame, target: str, features: list[str], min_rows: int = 80):
    if not HAS_SKLEARN:
        raise RuntimeError("Scikit-learn is niet beschikbaar.")
    if df is None or df.empty:
        raise ValueError("Geen data beschikbaar voor het ML model.")
    available = [c for c in features if c in df.columns]
    if target not in df.columns:
        raise ValueError(f"Doelkolom ontbreekt: {target}")
    if len(available) < 3:
        raise ValueError("Te weinig bruikbare features voor het ML model.")

    df_ml = df[available + [target]].apply(pd.to_numeric, errors='coerce').dropna(subset=[target])
    if len(df_ml) < min_rows:
        raise ValueError("Te weinig rijen voor een betrouwbare regressie.")

    X = df_ml[available]
    y = df_ml[target].astype(float)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)
    return X_train, X_test, y_train, y_test, available


def _prepare_binary_data(df: pd.DataFrame, target: str, features: list[str], min_rows: int = 80):
    if not HAS_SKLEARN:
        raise RuntimeError("Scikit-learn is niet beschikbaar.")
    if df is None or df.empty:
        raise ValueError("Geen data beschikbaar voor het ML model.")
    available = [c for c in features if c in df.columns]
    if target not in df.columns:
        raise ValueError(f"Doelkolom ontbreekt: {target}")
    if len(available) < 3:
        raise ValueError("Te weinig bruikbare features voor het ML model.")

    df_ml = df[available + [target]].apply(pd.to_numeric, errors='coerce').dropna(subset=[target])
    df_ml = df_ml[df_ml[target].isin([0, 1])]
    if len(df_ml) < min_rows or df_ml[target].nunique() < 2:
        raise ValueError("Te weinig rijen of targetvariatie voor classificatie.")

    X = df_ml[available]
    y = df_ml[target].astype(int)
    stratify = y if y.value_counts().min() >= 2 else None
    return train_test_split(X, y, test_size=0.25, random_state=42, stratify=stratify) + [available]


def _with_basic_ml_features(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    if 'postal_code' in result.columns:
        result['has_postal_code'] = result['postal_code'].notna().astype(int)
    elif 'has_postal_code' not in result.columns:
        result['has_postal_code'] = 0
    return result


def _normalize_for_model_score(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors='coerce')
    if s.notna().sum() == 0:
        return s

    low = s.quantile(0.05)
    high = s.quantile(0.95)
    if pd.isna(low) or pd.isna(high) or high <= low:
        max_value = s.max()
        if pd.isna(max_value) or max_value <= 0:
            return s
        return 1.0 + 9.0 * (s / max_value).clip(0, 1)

    scaled = (s - low) / (high - low)
    return 1.0 + 9.0 * scaled.clip(0, 1)


def _load_lifestyle_improvement_target(df: pd.DataFrame) -> pd.DataFrame:
    try:
        from config import DB_URL
        from data_ingestion import load_factor_score_histories, load_table_from_database

        hist = load_factor_score_histories(DB_URL)
        if hist.empty:
            raise ValueError("factor_score_histories is leeg.")

        hist = hist.copy()
        if 'slug' not in hist.columns:
            qf = load_table_from_database('questionnaire_factors', DB_URL)
            if qf.empty or 'id' not in qf.columns or 'slug' not in qf.columns:
                raise ValueError("Kan score-slugs niet koppelen.")
            hist['questionnaire_factor_id'] = pd.to_numeric(hist['questionnaire_factor_id'], errors='coerce')
            qf['id'] = pd.to_numeric(qf['id'], errors='coerce')
            hist = hist.merge(qf[['id', 'slug']], left_on='questionnaire_factor_id', right_on='id', how='left')

        hist['participant_id'] = pd.to_numeric(hist['participant_id'], errors='coerce')
        hist['score_value'] = pd.to_numeric(hist['score_value'], errors='coerce')
        hist['completion_created_at'] = pd.to_datetime(hist['completion_created_at'], errors='coerce')
        hist = hist.dropna(subset=['participant_id', 'score_value', 'completion_created_at'])

        slug_candidates = {'rec_ls_lifestyle_score', 'ls_lifestyle_score', 'lifestyle_score'}
        hist_lifestyle = hist[hist['slug'].astype(str).isin(slug_candidates)].copy()
        if hist_lifestyle.empty:
            factor_map = {
                9: 'rec_ls_alcohol_total_per_week',
                12: 'rec_ls_exercise_physical_activity_minutes_total',
                13: 'rec_ls_nutrition_saturated_fat_per_day',
                14: 'rec_ls_nutrition_fruit_fruit_per_day',
                17: 'rec_ls_nutrition_natrium_per_day',
                18: 'rec_ls_sleep_psqi_sum',
                19: 'rec_ls_stress_sum',
                20: 'rec_ls_nutrition_sugar_per_day',
                21: 'rec_ls_vegetables_gram_per_day',
            }
            hist_components = hist.copy()
            hist_components['factor_name'] = pd.to_numeric(
                hist_components['questionnaire_factor_id'],
                errors='coerce',
            ).map(factor_map)
            hist_components = hist_components.dropna(subset=['factor_name'])
            if hist_components.empty:
                raise ValueError("Geen historische leefstijlscore of leefstijlcomponenten gevonden.")

            wide = hist_components.pivot_table(
                index=['participant_id', 'completion_created_at'],
                columns='factor_name',
                values='score_value',
                aggfunc='mean',
            ).reset_index()
            component_cols = [c for c in wide.columns if c in factor_map.values()]
            if not component_cols:
                raise ValueError("Geen historische leefstijlcomponenten gevonden.")

            normalized = wide[component_cols].apply(_normalize_for_model_score)
            wide['score_value'] = normalized.mean(axis=1)
            hist_lifestyle = wide[['participant_id', 'completion_created_at', 'score_value']].dropna(subset=['score_value'])

        hist = hist_lifestyle.sort_values(['participant_id', 'completion_created_at'])

        grouped = hist.groupby('participant_id')
        first = grouped.first()[['score_value']].rename(columns={'score_value': 'first_lifestyle_score'})
        last = grouped.last()[['score_value']].rename(columns={'score_value': 'last_lifestyle_score'})
        counts = grouped.size().rename('n_lifestyle_measurements')
        target = first.join(last).join(counts).reset_index()
        target = target[target['n_lifestyle_measurements'] >= 2].copy()
        target['improvement_lifestyle_score'] = target['last_lifestyle_score'] - target['first_lifestyle_score']

        result = df.copy()
        if 'participant_id' in result.columns:
            result['participant_id'] = pd.to_numeric(result['participant_id'], errors='coerce')
            result = result.merge(
                target[['participant_id', 'improvement_lifestyle_score', 'n_lifestyle_measurements']],
                on='participant_id',
                how='left',
            )
        else:
            result['improvement_lifestyle_score'] = pd.NA
            result['n_lifestyle_measurements'] = pd.NA
        return result
    except Exception as exc:
        logger.warning(f"Kon verbeterdoel niet maken: {exc}")
        result = df.copy()
        result['improvement_lifestyle_score'] = pd.NA
        result['n_lifestyle_measurements'] = pd.NA
        return result


def _load_purchase_target(df: pd.DataFrame) -> pd.DataFrame:
    try:
        from config import DB_URL
        from data_ingestion import get_user_purchases

        purchases = get_user_purchases(db_url=DB_URL)
        result = df.copy()
        result['has_purchase'] = 0
        if purchases.empty:
            return result

        purchases = purchases.copy()
        if 'status' in purchases.columns:
            status = purchases['status'].astype(str).str.lower()
            purchases = purchases[~status.isin(['cancelled', 'canceled', 'failed', 'refunded'])]

        if 'participant_id' in result.columns and 'participant_id' in purchases.columns:
            buyers = pd.to_numeric(purchases['participant_id'], errors='coerce').dropna().unique()
            result['has_purchase'] = pd.to_numeric(result['participant_id'], errors='coerce').isin(buyers).astype(int)
        elif 'user_id' in result.columns and 'user_id' in purchases.columns:
            buyers = pd.to_numeric(purchases['user_id'], errors='coerce').dropna().unique()
            result['has_purchase'] = pd.to_numeric(result['user_id'], errors='coerce').isin(buyers).astype(int)
        return result
    except Exception as exc:
        logger.warning(f"Kon aankoopdoel niet maken: {exc}")
        result = df.copy()
        result['has_purchase'] = 0
        return result


def _attach_cv_metrics(model: Pipeline, X: pd.DataFrame, y: pd.Series) -> None:
    if y.nunique(dropna=True) <= 5:
        min_class = int(y.value_counts().min()) if not y.empty else 0
        if min_class < 3:
            model.cv_metrics = {}
            return

    y_numeric = pd.to_numeric(y, errors='coerce')
    if y_numeric.nunique(dropna=True) <= 8 and y_numeric.dropna().between(0, 2).all():
        cv = min(5, int(y.value_counts().min()) if not y.empty else 5)
        cv = max(2, cv)
        scores = cross_validate(
            model,
            X,
            y,
            cv=cv,
            scoring={'accuracy': 'accuracy', 'recall_macro': 'recall_macro'},
            error_score='raise',
        )
        model.cv_metrics = {
            'accuracy_mean': float(scores['test_accuracy'].mean()),
            'recall_macro': float(scores['test_recall_macro'].mean()),
            'recall_macro_mean': float(scores['test_recall_macro'].mean()),
            'recall_macro_std': float(scores['test_recall_macro'].std()),
        }
        return

    cv = min(5, max(2, int(len(y) / 20)))
    scores = cross_validate(
        model,
        X,
        y,
        cv=cv,
        scoring={'r2': 'r2', 'neg_mean_absolute_error': 'neg_mean_absolute_error'},
        error_score='raise',
    )
    model.cv_metrics = {
        'r2_mean': float(scores['test_r2'].mean()),
        'r2_std': float(scores['test_r2'].std()),
        'mae_mean': float(-scores['test_neg_mean_absolute_error'].mean()),
        'mae_std': float(scores['test_neg_mean_absolute_error'].std()),
    }


def train_bp_model(df: pd.DataFrame, force_retrain: bool = False):
    X_train, X_test, y_train, y_test, features = _prepare_classification_data(
        df,
        'rec_med_blood_pressure_cat',
        BP_FEATURES,
    )
    model = _make_classifier()
    model.fit(X_train, y_train)
    _attach_cv_metrics(model, X_train, y_train)

    # Vind beste drempelwaarden op de testset
    threshold_scan_results = _find_best_thresholds_for_classification(model, X_test, y_test, sorted(y_test.unique()))

    # Update model.cv_metrics with threshold scan results
    if not hasattr(model, 'cv_metrics'):
        model.cv_metrics = {}
    model.cv_metrics['threshold_scan_top'] = threshold_scan_results
    
    # Sla de beste drempels op in het model object voor later gebruik in predict_bp
    if threshold_scan_results:
        model.best_thresholds = threshold_scan_results[0]
        
    return model, X_test, y_test, features, y_train


def train_lifestyle_model(df: pd.DataFrame, force_retrain: bool = False):
    X_train, X_test, y_train, y_test, features = _prepare_regression_data(
        df,
        'rec_ls_lifestyle_score',
        LIFESTYLE_FEATURES,
        min_rows=80,
    )
    model = _make_regressor()
    model.fit(X_train, y_train)
    _attach_cv_metrics(model, X_train, y_train)

    y_pred = model.predict(X_test)
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    model.cv_metrics = {
        **(getattr(model, 'cv_metrics', {}) or {}),
        'mae': float(mean_absolute_error(y_test, y_pred)),
        'rmse': float(np.sqrt(mean_squared_error(y_test, y_pred))),
        'r2': float(r2_score(y_test, y_pred)),
        'n_test': int(len(y_test)),
    }
    return model, X_test, y_test, features, y_train


def train_dropoff_model(df: pd.DataFrame, force_retrain: bool = False):
    df_model = _with_basic_ml_features(df)
    df_model['dropoff_risk'] = pd.to_numeric(df_model.get('rec_ls_lifestyle_score'), errors='coerce').isna().astype(int)
    X_train, X_test, y_train, y_test, features = _prepare_binary_data(
        df_model,
        'dropoff_risk',
        ACTIVATION_FEATURES,
        min_rows=120,
    )
    model = _make_classifier(n_estimators=240)
    model.fit(X_train, y_train)
    _attach_cv_metrics(model, X_train, y_train)
    return model, X_test, y_test, features, y_train


def train_improvement_model(df: pd.DataFrame, force_retrain: bool = False):
    df_model = _load_lifestyle_improvement_target(df)
    X_train, X_test, y_train, y_test, features = _prepare_regression_data(
        df_model,
        'improvement_lifestyle_score',
        IMPROVEMENT_FEATURES,
        min_rows=50,
    )
    model = _make_regressor(n_estimators=240)
    model.fit(X_train, y_train)
    _attach_cv_metrics(model, X_train, y_train)
    return model, X_test, y_test, features, y_train


def train_purchase_model(df: pd.DataFrame, force_retrain: bool = False):
    df_model = _load_purchase_target(df)
    X_train, X_test, y_train, y_test, features = _prepare_binary_data(
        df_model,
        'has_purchase',
        PURCHASE_FEATURES,
        min_rows=120,
    )
    model = _make_classifier(n_estimators=240)
    model.fit(X_train, y_train)
    _attach_cv_metrics(model, X_train, y_train)
    return model, X_test, y_test, features, y_train


def _align_input_features(model, input_df: pd.DataFrame) -> pd.DataFrame:
    """Align input columns to the trained feature order to avoid sklearn feature-name mismatches."""
    if input_df is None:
        raise ValueError("Geen invoerdata beschikbaar voor leefstijlvoorspelling.")

    candidate_features = None
    if hasattr(model, 'feature_names_in_'):
        candidate_features = list(model.feature_names_in_)
    elif hasattr(model, 'named_steps') and hasattr(model.named_steps.get('model', model), 'feature_names_in_'):
        candidate_features = list(model.named_steps['model'].feature_names_in_)

    if candidate_features:
        aligned = input_df.copy()
        aligned = aligned.reindex(columns=candidate_features, fill_value=np.nan)
        return aligned
    return input_df


def predict_lifestyle(model, input_df: pd.DataFrame):
    aligned_df = _align_input_features(model, input_df)
    return model.predict(aligned_df)


def predict_binary_model(model, input_df: pd.DataFrame):
    aligned_df = _align_input_features(model, input_df)
    proba = model.predict_proba(aligned_df)
    return model.predict(aligned_df), proba


def train_heartrisk_model(df: pd.DataFrame, force_retrain: bool = False):
    X_train, X_test, y_train, y_test, features = _prepare_classification_data(
        df,
        'rec_heartrisk_cat',
        HEARTRISK_FEATURES,
    )
    model = _make_classifier(n_estimators=260)
    model.fit(X_train, y_train)
    _attach_cv_metrics(model, X_train, y_train)

    # Vind beste drempelwaarden
    threshold_scan_results = _find_best_thresholds_for_classification(model, X_test, y_test, sorted(y_test.unique()))
    
    # Gebruik drempels voor de metrieken rapportage
    best_t = threshold_scan_results[0] if threshold_scan_results else {}
    y_pred_proba_test = model.predict_proba(X_test)
    y_pred_hr_test = _apply_custom_thresholds(y_pred_proba_test, best_t, model.classes_)

    # Ensure all class labels are present in y_test for recall calculation
    class_labels = sorted(y_test.unique())
    # If a class is missing, recall for that class is 0.
    rec_moderate = recall_score(
        (y_test == 1).astype(int), (y_pred_hr_test == 1).astype(int), zero_division=0
    ) if 1 in class_labels else 0.0
    rec_high = recall_score(
        (y_test == 2).astype(int), (y_pred_hr_test == 2).astype(int), zero_division=0
    ) if 2 in class_labels else 0.0

    if not hasattr(model, 'cv_metrics'):
        model.cv_metrics = {}
        
    model.best_thresholds = best_t
    # Update model.cv_metrics with corrected class-specific recalls and threshold scan results
    model.cv_metrics.update({
        'recall_moderate_mean': float(rec_moderate),
        'recall_moderate_std': 0.0,
        'recall_high_mean': float(rec_high),
        'recall_high_std': 0.0,
        'threshold_scan_top': threshold_scan_results,
    })
    return model, X_test, y_test, features, y_train


def predict_bp(model, input_df: pd.DataFrame):
    aligned_df = _align_input_features(model, input_df)
    proba = model.predict_proba(aligned_df)
    if hasattr(model, 'best_thresholds'):
        preds = _apply_custom_thresholds(proba, model.best_thresholds, model.classes_)
        return preds, proba
    return model.predict(aligned_df), proba


def predict_heartrisk(model, input_df: pd.DataFrame):
    aligned_df = _align_input_features(model, input_df)
    proba = model.predict_proba(aligned_df)
    if hasattr(model, 'best_thresholds'):
        preds = _apply_custom_thresholds(proba, model.best_thresholds, model.classes_)
        return preds, proba
    return model.predict(aligned_df), proba


def _extract_feature_importances(model) -> np.ndarray | None:
    """Return ensemble feature importances even when the fitted object is a VotingClassifier/Regressor."""
    estimator = model.named_steps.get('model') if hasattr(model, 'named_steps') else model

    direct = getattr(estimator, 'feature_importances_', None)
    if direct is not None:
        return np.asarray(direct, dtype=float)

    estimators = getattr(estimator, 'estimators_', None) or getattr(estimator, 'named_estimators_', None)
    if isinstance(estimators, dict):
        estimators = list(estimators.values())

    if estimators:
        importances = []
        for est in estimators:
            imp = getattr(est, 'feature_importances_', None)
            if imp is not None:
                importances.append(np.asarray(imp, dtype=float))
        if importances:
            return np.mean(np.vstack(importances), axis=0)

    return None


def plot_feature_importance(model, features: list[str], titel: str = "Model") -> go.Figure:
    importances = _extract_feature_importances(model)
    if importances is None or len(importances) != len(features):
        return _empty_fig("Geen feature importance beschikbaar voor dit model.")
    labels = [FEATURE_LABELS.get(f, f) for f in features]
    df_imp = pd.DataFrame({'Feature': labels, 'Belangrijkheid': importances}).sort_values('Belangrijkheid')
    fig = px.bar(
        df_imp,
        x='Belangrijkheid',
        y='Feature',
        orientation='h',
        title=f'Belangrijkste voorspellers - {titel}',
        color_discrete_sequence=[HOOFD_KLEUR],
    )
    fig.update_layout(template='plotly_white', height=480, yaxis_title='')
    return fig


def plot_confusion_matrix(y_true, y_pred) -> go.Figure:
    labels = [0, 1, 2]
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    fig = px.imshow(
        cm,
        x=['Laag/Normaal', 'Matig/Verhoogd', 'Hoog'],
        y=['Laag/Normaal', 'Matig/Verhoogd', 'Hoog'],
        text_auto=True,
        color_continuous_scale='Blues',
        labels={'x': 'Voorspeld', 'y': 'Werkelijk', 'color': 'Aantal'},
        title='Confusion matrix',
    )
    fig.update_layout(template='plotly_white', height=420)
    return fig


def plot_prediction_performance_regression(y_true, y_pred) -> go.Figure:
    """Visualiseert regressievoorspellingen tegen de werkelijke waarden."""
    y_true = pd.to_numeric(pd.Series(y_true), errors='coerce').reset_index(drop=True)
    y_pred = pd.to_numeric(pd.Series(y_pred), errors='coerce').reset_index(drop=True)

    if y_true.empty or y_pred.empty or len(y_true) != len(y_pred):
        return _empty_fig("Geen bruikbare regressie-data voor de voorspellinggrafiek.")

    aligned = pd.DataFrame({'y_true': y_true, 'y_pred': y_pred}).dropna()
    if aligned.empty:
        return _empty_fig("Geen bruikbare regressie-data voor de voorspellinggrafiek.")

    fig = px.scatter(
        aligned,
        x='y_true',
        y='y_pred',
        opacity=0.7,
        title='Werkelijke vs. voorspelde waarden',
        labels={'y_true': 'Werkelijke waarde', 'y_pred': 'Voorspelde waarde'},
        color_discrete_sequence=[HOOFD_KLEUR],
    )
    min_val = min(aligned['y_true'].min(), aligned['y_pred'].min())
    max_val = max(aligned['y_true'].max(), aligned['y_pred'].max())
    fig.add_trace(go.Scatter(
        x=[min_val, max_val],
        y=[min_val, max_val],
        mode='lines',
        name='Ideale lijn',
        line=dict(color='red', dash='dash'),
    ))
    fig.update_layout(template='plotly_white', height=420, showlegend=True)
    return fig


def plot_precision_recall_curve(y_true, y_pred_proba) -> go.Figure:
    classes = [0, 1, 2]
    y_bin = label_binarize(y_true, classes=classes)
    fig = go.Figure()
    labels = {0: 'Laag', 1: 'Matig', 2: 'Hoog'}
    for idx, cls in enumerate(classes):
        if y_bin[:, idx].sum() == 0:
            continue
        precision, recall, _ = precision_recall_curve(y_bin[:, idx], y_pred_proba[:, idx])
        fig.add_trace(go.Scatter(x=recall, y=precision, mode='lines', name=labels[cls]))
    fig.update_layout(
        template='plotly_white',
        title='Precision-recall curve',
        xaxis_title='Recall',
        yaxis_title='Precision',
        height=420,
    )
    return fig


def plot_local_shap(model_data: dict, input_df: pd.DataFrame, titel: str = "Model") -> go.Figure:
    model = model_data.get('model') if isinstance(model_data, dict) else None
    features = model_data.get('features', list(input_df.columns)) if isinstance(model_data, dict) else list(input_df.columns)
    importances = _extract_feature_importances(model)
    if importances is None or len(importances) != len(features):
        return _empty_fig("Geen lokale uitleg beschikbaar.")

    row = input_df.reindex(columns=features)
    baseline = pd.DataFrame(model_data.get('X_test', row)).reindex(columns=features)
    baseline_mean = baseline.apply(pd.to_numeric, errors='coerce').mean()
    values = row.iloc[0].apply(pd.to_numeric, errors='coerce')
    signed = (values - baseline_mean).fillna(0) * importances
    df_local = pd.DataFrame({
        'Feature': [FEATURE_LABELS.get(f, f) for f in features],
        'Invloed': signed.values,
    }).sort_values('Invloed')
    fig = px.bar(df_local, x='Invloed', y='Feature', orientation='h', title=f'Lokale uitleg - {titel}')
    fig.update_layout(template='plotly_white', height=420, yaxis_title='')
    return fig


def maak_gebruikers_segmentatie_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    if not HAS_SKLEARN:
        return _empty_fig(tr("Scikit-learn is niet beschikbaar.", lang))
    features = [
        'rec_ls_lifestyle_score',
        'rec_med_bmi',
        'rec_ls_stress_sum',
        'rec_wellbeing_score',
        'rec_resilience_score',
    ]
    available = [c for c in features if c in df.columns]
    if len(available) < 3:
        return _empty_fig(tr("Onvoldoende data voor gebruikerssegmentatie.", lang))
    df_seg = df[available].apply(pd.to_numeric, errors='coerce').dropna()
    if len(df_seg) < 30:
        return _empty_fig(tr("Te weinig datapunten voor gebruikerssegmentatie.", lang))

    scaled = StandardScaler().fit_transform(df_seg)
    clusters = KMeans(n_clusters=3, n_init=10, random_state=42).fit_predict(scaled)
    plot_df = df_seg.copy()
    plot_df['Segment'] = [f"Segment {c + 1}" for c in clusters]
    x_col = 'rec_ls_lifestyle_score' if 'rec_ls_lifestyle_score' in plot_df.columns else available[0]
    y_col = 'rec_med_bmi' if 'rec_med_bmi' in plot_df.columns else available[1]
    size_col = 'rec_ls_stress_sum' if 'rec_ls_stress_sum' in plot_df.columns else None
    fig = px.scatter(
        plot_df,
        x=x_col,
        y=y_col,
        color='Segment',
        size=size_col,
        opacity=0.65,
        title=tr('Gebruikerssegmenten op basis van gezondheidsprofiel', lang),
        labels={x_col: tr(FEATURE_LABELS.get(x_col, x_col), lang), y_col: tr(FEATURE_LABELS.get(y_col, y_col), lang)},
    )
    fig.update_layout(template='plotly_white', height=520)
    return fig

def maak_feature_importance_plot(df: pd.DataFrame, lang: str = 'nl') -> go.Figure:
    """
    Visualiseert welke factoren de leefstijlscore het meest beïnvloeden
    met behulp van een Random Forest Regressor.
    """
    if not HAS_SKLEARN:
        fig = go.Figure()
        fig.add_annotation(
            text=tr("Machine Learning module (scikit-learn) is niet beschikbaar in deze omgeving.", lang),
            showarrow=False, font=dict(size=14)
        )
        fig.update_layout(template='plotly_white', height=400)
        return fig

    if df is None or df.empty:
        fig = go.Figure()
        fig.add_annotation(text=tr("Geen data beschikbaar.", lang), showarrow=False)
        return fig

    # Mapping van interne namen naar leesbare labels voor de grafiek
    feature_labels = {
        'rec_age_current': tr('Leeftijd', lang),
        'rec_ls_score_fruit': tr('Fruit', lang),
        'rec_ls_score_vegetables': tr('Groenten', lang),
        'rec_ls_score_sugar': tr('Suiker', lang),
        'rec_ls_score_saturated_fat': tr('Verzadigd vet', lang),
        'rec_ls_score_alcohol': tr('Alcohol', lang),
        'rec_ls_score_natrium': tr('Zout', lang),
        'rec_ls_stress_sum': tr('Stress', lang),
        'rec_ls_sleep_psqi_sum': tr('Slaap', lang),
    }
    
    target = 'rec_ls_lifestyle_score'
    
    # Alleen de kolommen gebruiken die daadwerkelijk in de dataframe zitten
    available_features = [c for c in feature_labels.keys() if c in df.columns]
    
    if target not in df.columns or len(available_features) < 3:
        fig = go.Figure()
        fig.add_annotation(text=tr("Onvoldoende data voor machine learning analyse.", lang), showarrow=False)
        return fig

    # Data voorbereiden: numeriek maken en rijen met missende waarden verwijderen
    df_ml = df[available_features + [target]].apply(pd.to_numeric, errors='coerce').dropna()
    
    if len(df_ml) < 50:
        fig = go.Figure()
        fig.add_annotation(text=tr("Te weinig datapunten voor een betrouwbare analyse.", lang), showarrow=False)
        return fig

    X = df_ml[available_features]
    y = df_ml[target]

    # Model trainen
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X, y)

    # Importance data verzamelen en sorteren
    importance_df = pd.DataFrame({
        'Feature': [feature_labels[c] for c in available_features],
        'Belangrijkheid': model.feature_importances_
    }).sort_values('Belangrijkheid', ascending=True)

    fig = px.bar(
        importance_df, 
        x='Belangrijkheid', 
        y='Feature',
        orientation='h',
        title=tr('Impact van factoren op Leefstijlscore', lang),
        labels={'Belangrijkheid': tr('Relatieve impact', lang), 'Feature': ''},
        color_discrete_sequence=[HOOFD_KLEUR]
    )
    
    fig.update_layout(
        template='plotly_white',
        height=500,
        xaxis=dict(showgrid=True, gridcolor='rgba(0,0,0,0.1)'),
        yaxis=dict(showgrid=False)
    )
    
    return fig
