# Dashboard Deployen

## Aanbevolen route

Gebruik een private GitHub repository + Streamlit Community Cloud.

## Bestanden

- Entry point: `dashboard.py`
- Dependencies: `requirements.txt`
- Lokale auth file: niet committen, maar lokaal bewaren

## Auth file lokaal

Zet jouw auth-bestand bijvoorbeeld hier:

`~/Documents/smart_health_auth.json`

Voorbeeld inhoud:

```json
{
  "enabled": true,
  "users": [
    {
      "username": "jouwnaam",
      "password_hash": "pbkdf2_sha256:200000:<salt_hex>:<derived_key_hex>"
    }
  ]
}
```

Gebruik voor nieuwe wachtwoorden altijd een gehashte waarde. Een eenvoudige manier om een hash te genereren is:

```bash
python3 - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, str(Path('/Users/bliekendaal/Desktop/Code').resolve()))
from auth import hash_password
print(hash_password('jouw_wachtwoord'))
PY
```

## Lokaal testen

Als jouw bestand precies `~/Documents/smart_health_auth.json` heet, wordt het automatisch gevonden.
Alleen bij een andere locatie hoef je `SMART_HEALTH_AUTH_FILE` te zetten.

```bash
export SMART_HEALTH_AUTH_FILE="$HOME/Documents/smart_health_auth.json"
streamlit run /Users/bliekendaal/Desktop/Code/dashboard.py
```

## GitHub

1. Maak een private repository.
2. Upload de inhoud van de map `Code`.
3. Commit nooit `.dashboard_auth.json` of andere echte secrets.

## Streamlit Community Cloud

1. Log in op Streamlit Community Cloud.
2. Kies `Create app`.
3. Selecteer jouw private GitHub repository.
4. Kies branch.
5. Kies als main file: `dashboard.py`
6. Deploy de app.

## Streamlit secrets

Voor online deployment raad ik aan om users in Streamlit secrets te zetten.

Plak in Streamlit Cloud bij `Secrets` bijvoorbeeld:

```toml
[auth]
enabled = true

[[auth.users]]
username = "jouwnaam"
password = "jouw_wachtwoord"

[[auth.users]]
username = "collega"
password = "nog_een_wachtwoord"
```

De app leest eerst Streamlit secrets. Als die ontbreken, valt hij lokaal terug op jouw auth-bestand.

## Nieuwe environment variables

Je kunt de app ook via environment variables sturen:

- `DATABASE_URL`: de databaseconnectiestring die de app gebruikt.
- `SMART_HEALTH_AUTH_ENABLED`: zet op `true` of `1` om authenticatie altijd te forceren.

Voor productie is het aan te raden:

```bash
export DATABASE_URL="postgresql+psycopg2://user:password@host/dbname"
export SMART_HEALTH_AUTH_ENABLED=true
```

## Belangrijke noot

De app heeft nu een loginlaag in de app zelf. Voor echte afscherming is het beter om daarnaast ook de app zelf private te maken in Streamlit Cloud.

## Mogelijke blocker

`dashboard.py` verwijst naar een `ML`-module. Als dat bestand niet in de repository staat, werkt de ML-pagina niet online. De rest van het dashboard blijft wel werken.
