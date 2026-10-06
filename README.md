# Instagram Following Cleaner

Herramienta en Python para auditar y limpiar la lista de seguidos en Instagram respetando excepciones y límites de tasa (rate limits).

## Seguridad y Autenticación
El script **no requiere ni almacena tu contraseña**. Se autentica exclusivamente a través de la cookie de sesión existente (`sessionid`) de tu navegador web habitual:
1. Abre Instagram en tu navegador.
2. Abre las herramientas de desarrollador (`F12` -> `Almacenamiento`/`Storage` o `Aplicación`/`Application` -> `Cookies` -> `https://www.instagram.com`).
3. Copia el valor de la cookie llamada `sessionid`.

Puedes proporcionarla de tres formas:
- **Interactivamente:** El script la solicitará con entrada oculta (no se muestra en pantalla).
- **Archivo local seguro:** Guardándola en `.sessionid` dentro del proyecto (ignorado por Git).
- **Variable de entorno:** `export IG_SESSIONID="<sessionid>"`

Una vez validada, la sesión se persiste localmente en `ig_session.json` (también ignorado en Git) para no pedirla de nuevo mientras sea válida.

## Reglas de filtrado
1. Identifica cuentas que **no te siguen de vuelta**.
2. **Excepciones conservadas (no se dejan de seguir):**
   - Cuentas que superan el umbral de seguidores configurado (por defecto: 2.000 seguidores, guardadas en `exempt_over_<umbral>.txt`).
   - Cuentas privadas (guardadas en `exempt_private.txt`).
3. El resto de perfiles se marcan como candidatos (`candidates_to_unfollow.txt`).

## Uso con `uv`

### 1. Auditoría / Simulación (Dry-Run por defecto)
Analiza y genera las listas sin realizar ninguna acción destructiva:
```bash
cd /home/carlosg/Projects/instagram-cleaner
uv run main.py
```
*Al iniciar, puedes presionar `Enter` para usar el umbral predeterminado de 2.000 seguidores, o ingresar cualquier número.*

También puedes pasar el parámetro directamente:
```bash
uv run main.py --min-followers 5000
```

### 2. Ejecutar bajas reales
Aplica el flag `--execute` y opcionalmente define un `--limit` por sesión (recomendado máximo 50-70 por día para evitar suspensiones):
```bash
uv run main.py --execute --limit 50
```

## Opciones CLI
- `--min-followers <N>`: Umbral de seguidores para eximir cuentas.
- `--execute`: Ejecuta unfollows reales (por defecto es simulación).
- `--limit <N>`: Límite de unfollows por ejecución (por defecto: 50).
- `--reset-session`: Borra la sesión guardada para cambiar de cuenta.
- `--clear-cache`: Borra los reportes `.txt` anteriores para reiniciar desde cero.

## Archivos de salida
- `exempt_over_<umbral>.txt`: Lista de perfiles con más seguidores que el umbral.
- `exempt_private.txt`: Lista de perfiles privados conservados.
- `candidates_to_unfollow.txt`: Lista de cuentas que no te siguen y no cumplen las excepciones.
- `unfollowed.txt`: Registro acumulativo de cuentas dadas de baja.
