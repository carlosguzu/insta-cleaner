import argparse
import getpass
import json
import os
import random
import sys
import time
from pathlib import Path
from instagrapi import Client

SESSION_FILE = Path("ig_session.json")
EXEMPT_PRIVATE_FILE = Path("exempt_private.txt")
CANDIDATES_FILE = Path("candidates_to_unfollow.txt")
UNFOLLOWED_LOG_FILE = Path("unfollowed.txt")
UNFOLLOWED_CSV_FILE = Path("unfollowed_history.csv")
UNFOLLOWED_JSON_FILE = Path("unfollowed_history.json")


def get_exempt_followers_file(min_followers: int) -> Path:
    if min_followers == 2000 and Path("exempt_over_2k.txt").exists():
        return Path("exempt_over_2k.txt")
    return Path(f"exempt_over_{min_followers}.txt")


def get_client(session_file: Path = SESSION_FILE) -> Client:
    cl = Client()
    cl.request_timeout = 20

    session_file_txt = Path(".sessionid")
    new_session_id = os.getenv("IG_SESSIONID")
    if not new_session_id and session_file_txt.exists():
        new_session_id = session_file_txt.read_text(encoding="utf-8").strip()

    # 1. Si el usuario puso un nuevo sessionid explícito en .sessionid, usarlo y actualizar ig_session.json
    if new_session_id:
        # Si ya existe un ig_session.json, comprobar si el sessionid cambió
        saved_sessionid = ""
        if session_file.exists():
            try:
                import json
                data = json.loads(session_file.read_text(encoding="utf-8"))
                saved_sessionid = data.get("cookies", {}).get("sessionid", "")
            except Exception:
                pass

        if new_session_id != saved_sessionid:
            print("[*] Nuevo sessionid detectado en .sessionid. Actualizando sesión...")
            try:
                cl.login_by_sessionid(new_session_id)
                cl.dump_settings(session_file)
                print(f"[+] Autenticación exitosa como @{cl.username} (ID: {cl.user_id}).")
                return cl
            except Exception as err:
                print(f"[!] Error con el nuevo sessionid: {err}")

    # 2. Cargar sesión guardada previamente si existe
    if session_file.exists():
        print(f"[*] Cargando sesión persistida desde: {session_file.resolve()}")
        try:
            cl.load_settings(session_file)
            if cl.user_id:
                print(f"[+] Sesión cargada para ID: {cl.user_id}.")
                return cl
        except Exception as err:
            print(f"[!] Sesión guardada no válida o expirada ({err}). Solicitando nuevo sessionid...")

    # 3. Si no hay sesión válida ni nuevo sessionid, solicitar interactivamente
    if not new_session_id:
        print("\nPara autenticarte de forma segura sin contraseña:")
        print("1. Abre Instagram en tu navegador habitual.")
        print("2. Abre DevTools (F12) -> Almacenamiento/Storage (o Aplicación) -> Cookies -> https://www.instagram.com")
        print("3. Copia el valor de la cookie 'sessionid'.")
        new_session_id = getpass.getpass("\nPega tu cookie sessionid (la entrada no se mostrará en pantalla): ").strip()

    if not new_session_id:
        print("[-] Error: sessionid no proporcionado.")
        sys.exit(1)

    try:
        print("[*] Validando sessionid con Instagram...")
        cl.login_by_sessionid(new_session_id)
        cl.dump_settings(session_file)
        print(f"[+] Autenticación exitosa como @{cl.username} (ID: {cl.user_id}).")
        return cl
    except Exception as err:
        print(f"[-] Error al autenticar con sessionid: {err}")
        sys.exit(1)


def analyze_relationships(
    cl: Client,
    min_followers: int = 2000,
    sleep_range: tuple[float, float] = (2.0, 4.0),
) -> tuple[list[str], list[str], list[tuple[int, str]]]:
    user_id = cl.user_id

    print("\n[*] Obteniendo lista de cuentas seguidas (following)...")
    following = cl.user_following(user_id)
    print(f"    Total seguidos: {len(following)}")

    print("[*] Obteniendo lista de seguidores (followers)...")
    followers = cl.user_followers(user_id)
    print(f"    Total seguidores: {len(followers)}")

    follower_ids = set(followers.keys())
    not_following_back = [u for uid, u in following.items() if uid not in follower_ids]
    print(f"[!] Cuentas que no te siguen de vuelta: {len(not_following_back)}")

    exempt_over_file = get_exempt_followers_file(min_followers)
    exempt_over_min: list[str] = []
    exempt_private: list[str] = []
    to_unfollow: list[tuple[int, str]] = []

    # Cargar cuentas ya analizadas si existen para permitir reanudar
    processed_candidates = set()
    if CANDIDATES_FILE.exists():
        processed_candidates = set(CANDIDATES_FILE.read_text(encoding="utf-8").splitlines())
    processed_over_min = set()
    for potential_file in [exempt_over_file, Path("exempt_over_2k.txt")]:
        if potential_file.exists():
            for line in potential_file.read_text(encoding="utf-8").splitlines():
                if line:
                    processed_over_min.add(line.split()[0].replace("@", ""))
    processed_private = set()
    if EXEMPT_PRIVATE_FILE.exists():
        processed_private = set(EXEMPT_PRIVATE_FILE.read_text(encoding="utf-8").splitlines())

    already_processed = processed_candidates | processed_over_min | processed_private

    # Abrir archivos en modo append con autoflush para guardar en tiempo real
    f_over = exempt_over_file.open("a", encoding="utf-8")
    f_priv = EXEMPT_PRIVATE_FILE.open("a", encoding="utf-8")
    f_cand = CANDIDATES_FILE.open("a", encoding="utf-8")

    print(f"\n[*] Inspeccionando perfiles para filtrar excepciones (umbral: >{min_followers} seguidores)...")
    total = len(not_following_back)
    try:
        for idx, user_short in enumerate(not_following_back, start=1):
            username = user_short.username
            if username in already_processed:
                print(f"[{idx:4d}/{total:4d}] @{username:<25} -> YA CLASIFICADO (saltando)")
                continue

            try:
                info = cl.user_info(user_short.pk)
                username = info.username
                follower_count = info.follower_count
                is_private = info.is_private

                status_str = f"Seguidores: {follower_count:>6} | Privada: {str(is_private):<5}"

                if follower_count > min_followers:
                    exempt_over_min.append(f"{username} ({follower_count} seguidores)")
                    f_over.write(f"{username} ({follower_count} seguidores)\n")
                    f_over.flush()
                    print(f"[{idx:4d}/{total:4d}] @{username:<25} {status_str} -> EXENTO (>{min_followers})")
                elif is_private:
                    exempt_private.append(username)
                    f_priv.write(f"{username}\n")
                    f_priv.flush()
                    print(f"[{idx:4d}/{total:4d}] @{username:<25} {status_str} -> EXENTO (Privada)")
                else:
                    to_unfollow.append((info.pk, username))
                    f_cand.write(f"{username}\n")
                    f_cand.flush()
                    print(f"[{idx:4d}/{total:4d}] @{username:<25} {status_str} -> CANDIDATO UNFOLLOW")

                time.sleep(random.uniform(*sleep_range))
            except Exception as err:
                print(f"[{idx:4d}/{total:4d}] Error al inspeccionar @{user_short.username}: {err}")
                time.sleep(10.0)
    finally:
        f_over.close()
        f_priv.close()
        f_cand.close()

    return exempt_over_min, exempt_private, to_unfollow


def send_notification(title: str, message: str, urgency: str = "normal"):
    """Envía una notificación de escritorio en Wayland/Hyprland."""
    try:
        import subprocess
        subprocess.run(["notify-send", "-u", urgency, title, message], check=False)
    except Exception:
        pass


def record_unfollow(username: str, pk: int):
    """Registra cada unfollow de forma inmediata en unfollowed.txt, CSV y JSON con timestamp."""
    import datetime
    import json

    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. unfollowed.txt
    with UNFOLLOWED_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{username}\n")

    # 2. unfollowed_history.csv
    csv_exists = UNFOLLOWED_CSV_FILE.exists()
    with UNFOLLOWED_CSV_FILE.open("a", encoding="utf-8") as f:
        if not csv_exists:
            f.write("timestamp,username,user_id\n")
        f.write(f'"{now_iso}","{username}",{pk}\n')

    # 3. unfollowed_history.json
    history = []
    if UNFOLLOWED_JSON_FILE.exists():
        try:
            history = json.loads(UNFOLLOWED_JSON_FILE.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.append({"timestamp": now_iso, "username": username, "user_id": pk})
    UNFOLLOWED_JSON_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def get_unfollowed_today() -> int:
    """Calcula cuántas cuentas se han dado de baja hoy consultando unfollowed_history.csv."""
    import datetime
    if not UNFOLLOWED_CSV_FILE.exists():
        return 0
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    count = 0
    try:
        lines = UNFOLLOWED_CSV_FILE.read_text(encoding="utf-8").splitlines()
        for line in lines[1:]:  # Omitir header
            if line.startswith(f'"{today_str}'):
                count += 1
    except Exception:
        pass
    return count


def execute_unfollows(
    cl: Client,
    candidates: list[tuple[int, str]],
    limit: int = 180,
    sleep_range: tuple[float, float] = (30.0, 70.0),
    ignore_daily_quota: bool = False,
):
    daily_quota = limit
    already_done_today = get_unfollowed_today()

    if ignore_daily_quota:
        remaining_quota = limit
        print(f"\n[*] Modo lote forzado: procesando {remaining_quota} cuentas en esta sesión.")
        print(f"[*] Ya completadas hoy previamente: {already_done_today} cuentas.")
    else:
        remaining_quota = max(0, daily_quota - already_done_today)
        print(f"\n[*] Meta diaria: {daily_quota} cuentas.")
        print(f"[*] Ya completadas hoy: {already_done_today} cuentas.")
        print(f"[*] Cuota restante a procesar en esta sesión: {remaining_quota} cuentas.")

    if remaining_quota == 0:
        print(f"[+] ¡La meta diaria de {daily_quota} cuentas ya se cumplió el día de hoy! Nada por hacer hasta mañana.")
        send_notification(
            "Instagram Cleaner: Cuota al día",
            f"La meta diaria de {daily_quota} ya está cumplida hoy ({already_done_today} bajas realizadas).",
        )
        return

    count = 0
    error_occurred = False
    error_message = ""

    total_pendientes = len(candidates)
    num_a_procesar = min(remaining_quota, total_pendientes)

    # Notificación de inicio con información clara de reanudación
    if ignore_daily_quota:
        send_notification(
            "Instagram Cleaner: Iniciado",
            f"Comenzando lote manual de {num_a_procesar} cuentas.\n(Ya iban {already_done_today} hoy)\nPendientes totales: {total_pendientes}",
        )
    elif already_done_today > 0:
        send_notification(
            "Instagram Cleaner: Reanudando Lote",
            f"Reanudando tras reinicio.\nYa van {already_done_today}/{daily_quota} hoy.\nProcesando las {num_a_procesar} restantes.\nPendientes totales: {total_pendientes}",
        )
    else:
        send_notification(
            "Instagram Cleaner: Iniciado",
            f"Comenzando lote diario.\nObjetivos de hoy: {num_a_procesar} cuentas.\nPendientes totales: {total_pendientes}",
        )

    for pk, username in candidates:
        if count >= remaining_quota:
            if ignore_daily_quota:
                print(f"[!] Lote de {remaining_quota} alcanzado para esta sesión ({already_done_today + count} procesadas hoy en total).")
            else:
                print(f"[!] Meta diaria de {daily_quota} alcanzada para hoy ({already_done_today + count} procesadas).")
            break

        try:
            cl.user_unfollow(pk)
            count += 1
            record_unfollow(username, pk)
            total_hoy = already_done_today + count
            target_desc = f"{remaining_quota}" if ignore_daily_quota else f"{daily_quota}"
            print(f"[{count:2d}/{remaining_quota:2d}] (Hoy: {total_hoy}/{target_desc}) Dejaste de seguir a @{username}")

            if count < remaining_quota:
                wait_time = random.uniform(*sleep_range)
                print(f"         Esperando {wait_time:.1f} segundos...")
                time.sleep(wait_time)
        except Exception as err:
            error_occurred = True
            error_message = str(err)
            print(f"[-] Error al dejar de seguir a @{username}: {err}")
            break

    total_hoy_final = already_done_today + count
    print(f"\n[+] Sesión finalizada: {count} procesadas en esta sesión. Total hoy: {total_hoy_final}.")

    pendientes_restantes = total_pendientes - count
    if error_occurred:
        send_notification(
            "Instagram Cleaner: Alerta / Fallback",
            f"El lote se detuvo tras {count} en esta sesión ({total_hoy_final} hoy) debido a un error:\n{error_message[:100]}\nQuedan {pendientes_restantes} pendientes en total.",
            urgency="critical",
        )
    elif count >= remaining_quota or pendientes_restantes == 0:
        send_notification(
            "Instagram Cleaner: Lote Cumplido",
            f"¡Lote de {count} cuentas cumplido al 100%! ({total_hoy_final} hoy en total).\nQuedan {pendientes_restantes} pendientes en total.",
        )
    else:
        send_notification(
            "Instagram Cleaner: Sesión Detenida",
            f"Se procesaron {count} cuentas en esta sesión ({total_hoy_final} hoy).\nQuedan {pendientes_restantes} pendientes.",
        )


def parse_arguments():
    parser = argparse.ArgumentParser(description="Limpiador seguro de seguidos en Instagram.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Ejecuta los unfollows reales. Si no se especifica, corre en modo de simulación (DRY-RUN).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Límite máximo de unfollows por ejecución (por defecto: 50).",
    )
    parser.add_argument(
        "--min-followers",
        type=int,
        default=None,
        help="Umbral mínimo de seguidores para eximir una cuenta (por defecto: pregunta interactiva o 2000).",
    )
    parser.add_argument(
        "--reset-session",
        action="store_true",
        help="Elimina la sesión guardada y solicita una nueva cookie sessionid.",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Borra los archivos de resultados (.txt) previos para reiniciar la clasificación desde cero.",
    )
    parser.add_argument(
        "--ignore-daily-quota",
        action="store_true",
        help="Ignora la cuota diaria acumulada y ejecuta el límite completo indicado con --limit en esta sesión.",
    )
    return parser.parse_args()


TO_UNFOLLOW_FILE = Path("to_unfollow.txt")


def load_pending_unfollows(cl: Client) -> list[tuple[int, str]]:
    """Carga los objetivos pendientes desde to_unfollow.txt (o candidates_to_unfollow.txt)."""
    target_file = TO_UNFOLLOW_FILE if TO_UNFOLLOW_FILE.exists() else CANDIDATES_FILE
    if not target_file.exists():
        print(f"[-] No se encontró archivo de objetivos ({target_file.name}). Ejecuta primero la auditoría.")
        return []

    target_usernames = set()
    for line in target_file.read_text(encoding="utf-8").splitlines():
        uname = line.split()[0].replace("@", "").strip()
        if uname:
            target_usernames.add(uname)

    # Excluir privadas por seguridad
    if EXEMPT_PRIVATE_FILE.exists():
        privates = set(EXEMPT_PRIVATE_FILE.read_text(encoding="utf-8").splitlines())
        target_usernames -= privates

    # Excluir las ya dadas de baja
    already_unfollowed = set()
    if UNFOLLOWED_LOG_FILE.exists():
        already_unfollowed = set(UNFOLLOWED_LOG_FILE.read_text(encoding="utf-8").splitlines())
    target_usernames -= already_unfollowed

    print(f"\n[*] Objetivos en lista pendientes por procesar: {len(target_usernames)}")
    print("[*] Verificando con tu lista actual de seguidos en Instagram...")
    following = cl.user_following(cl.user_id)
    username_to_pk = {user.username.lower(): user.pk for user in following.values()}

    final_targets = []
    for uname in sorted(target_usernames):
        pk = username_to_pk.get(uname.lower())
        if pk:
            final_targets.append((pk, uname))

    print(f"[+] Total verificados que aún sigues activamente: {len(final_targets)}")
    return final_targets


def generate_final_report():
    """Genera un reporte markdown en el $HOME del usuario cuando todo está al 100%."""
    import datetime
    import subprocess

    report_file = Path.home() / "INSTAGRAM_CLEANUP_REPORT.md"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_unfollowed = 0
    if UNFOLLOWED_LOG_FILE.exists():
        total_unfollowed = len(UNFOLLOWED_LOG_FILE.read_text(encoding="utf-8").splitlines())

    total_private = 0
    if EXEMPT_PRIVATE_FILE.exists():
        total_private = len(EXEMPT_PRIVATE_FILE.read_text(encoding="utf-8").splitlines())

    content = f"""# Reporte de Limpieza de Instagram

- **Fecha de finalización:** {now_str}
- **Estado:** 100% Completado con éxito
- **Total de cuentas dadas de baja:** {total_unfollowed}
- **Cuentas privadas conservadas:** {total_private}

Todos los objetivos de tu lista fueron procesados y dados de baja exitosamente.
El temporizador de systemd ya puede ser desactivado con:
```bash
systemctl --user disable --now instagram-cleaner.timer
```
"""
    report_file.write_text(content, encoding="utf-8")
    print(f"\n[+] Reporte final generado en: {report_file.resolve()}")

    try:
        subprocess.run(
            ["notify-send", "Instagram Cleaner", "¡Limpieza al 100% completada! Reporte generado en tu home."],
            check=False,
        )
    except Exception:
        pass

    # Auto-desactivar el temporizador para que no siga despertando en vano
    try:
        print("[*] Desactivando automáticamente instagram-cleaner.timer...")
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "instagram-cleaner.timer"],
            check=False,
        )
    except Exception as e:
        print(f"[!] No se pudo auto-desactivar el timer: {e}")


def main():
    args = parse_arguments()

    if args.reset_session:
        for f in [SESSION_FILE, Path(".sessionid")]:
            if f.exists():
                f.unlink()
                print(f"[*] Archivo de sesión eliminado: {f.name}")
        print("[+] Sesión reiniciada. Ahora puedes ingresar una nueva cuenta.")

    if args.clear_cache:
        to_delete = [EXEMPT_PRIVATE_FILE, CANDIDATES_FILE, TO_UNFOLLOW_FILE, Path("exempt_over_2k.txt")]
        to_delete.extend(Path(".").glob("exempt_over_*.txt"))
        for f in set(to_delete):
            if f.exists():
                f.unlink()
                print(f"[*] Archivo borrado: {f.name}")
        print("[+] Listas anteriores limpiadas.")

    cl = get_client()

    # Si se pasa --execute, ejecutar directamente usando los archivos ya generados
    if args.execute:
        targets = load_pending_unfollows(cl)
        if not targets:
            print("[+] ¡No hay cuentas pendientes por dar de baja! Todo está al 100%.")
            generate_final_report()
            return

        print(f"\n[*] Ejecutando lote de bajas (máximo {args.limit} para esta sesión)...")
        execute_unfollows(
            cl,
            targets,
            limit=args.limit,
            ignore_daily_quota=args.ignore_daily_quota,
        )

        # Comprobar si tras este lote ya no quedan pendientes
        remaining = load_pending_unfollows(cl)
        if not remaining:
            print("[+] ¡Limpieza completada al 100%!")
            generate_final_report()
        return

    # Si no es --execute, corre el modo auditoría
    if args.min_followers is not None:
        min_followers = args.min_followers
    else:
        try:
            raw = input("\nUmbral mínimo de seguidores para no dejar de seguir [Enter para 2000]: ").strip()
            min_followers = int(raw) if raw.isdigit() else 2000
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado por el usuario.")
            sys.exit(0)

    print(f"[*] Cuentas con más de {min_followers:,} seguidores serán eximidas.")

    exempt_over_min, exempt_private, candidates = analyze_relationships(
        cl, min_followers=min_followers
    )
    exempt_over_file = get_exempt_followers_file(min_followers)

    print("\n" + "=" * 50)
    print("RESUMEN DE AUDITORÍA")
    print("=" * 50)
    print(f"Exentos con más de {min_followers:,} seguidores : {len(exempt_over_min)} (guardado en {exempt_over_file.resolve()})")
    print(f"Exentos por ser cuenta privada      : {len(exempt_private)} (guardado en {EXEMPT_PRIVATE_FILE.resolve()})")
    print(f"Candidatos para dejar de seguir     : {len(candidates)} (guardado en {CANDIDATES_FILE.resolve()})")
    print("=" * 50)
    print("\n[MODO SIMULACIÓN / DRY-RUN]")
    print("No se ha ejecutado ningún unfollow.")
    print("Para ejecutar bajas reales en lotes diarios, usa:")
    print("  uv run main.py --execute --limit 180")


if __name__ == "__main__":
    main()
