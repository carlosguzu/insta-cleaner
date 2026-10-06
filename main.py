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


def get_exempt_followers_file(min_followers: int) -> Path:
    if min_followers == 2000 and Path("exempt_over_2k.txt").exists():
        return Path("exempt_over_2k.txt")
    return Path(f"exempt_over_{min_followers}.txt")


def get_client(session_file: Path = SESSION_FILE) -> Client:
    cl = Client()

    # 1. Intentar cargar sesión guardada previamente
    if session_file.exists():
        print(f"[*] Cargando sesión persistida desde: {session_file.resolve()}")
        try:
            cl.load_settings(session_file)
            if cl.sessionid:
                cl.login_by_sessionid(cl.sessionid)
                print(f"[+] Sesión cargada exitosamente para @{cl.username} (ID: {cl.user_id}).")
                return cl
        except Exception as err:
            print(f"[!] Sesión guardada no válida o expirada ({err}). Solicitando sessionid...")

    # 2. Obtener sessionid de variable de entorno, archivo .sessionid o prompt interactivo oculto
    session_id = os.getenv("IG_SESSIONID")
    session_file_txt = Path(".sessionid")

    if not session_id and session_file_txt.exists():
        session_id = session_file_txt.read_text(encoding="utf-8").strip()

    if not session_id:
        print("\nPara autenticarte de forma segura sin contraseña:")
        print("1. Abre Instagram en tu navegador habitual.")
        print("2. Abre DevTools (F12) -> Almacenamiento/Storage (o Aplicación) -> Cookies -> https://www.instagram.com")
        print("3. Copia el valor de la cookie 'sessionid'.")
        session_id = getpass.getpass("\nPega tu cookie sessionid (la entrada no se mostrará en pantalla): ").strip()

    if not session_id:
        print("[-] Error: sessionid no proporcionado.")
        sys.exit(1)

    try:
        print("[*] Validando sessionid con Instagram...")
        cl.login_by_sessionid(session_id)
        cl.dump_settings(session_file)
        print(f"[+] Autenticación exitosa como @{cl.username} (ID: {cl.user_id}).")
        print(f"[+] Sesión guardada en: {session_file.resolve()}")
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


def execute_unfollows(
    cl: Client,
    candidates: list[tuple[int, str]],
    limit: int = 50,
    sleep_range: tuple[float, float] = (30.0, 70.0),
):
    print(f"\n[*] Iniciando proceso de unfollow (Límite para esta ejecución: {limit})...")
    count = 0
    unfollowed_log = []

    for pk, username in candidates:
        if count >= limit:
            print(f"[!] Límite de {limit} alcanzado para evitar bloqueos de Instagram.")
            break

        try:
            cl.user_unfollow(pk)
            count += 1
            unfollowed_log.append(username)
            print(f"[{count:2d}/{limit:2d}] Dejaste de seguir a @{username}")

            if count < limit:
                wait_time = random.uniform(*sleep_range)
                print(f"         Esperando {wait_time:.1f} segundos...")
                time.sleep(wait_time)
        except Exception as err:
            print(f"[-] Error al dejar de seguir a @{username}: {err}")
            break

    if unfollowed_log:
        with UNFOLLOWED_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write("\n".join(unfollowed_log) + "\n")

    print(f"\n[+] Total de cuentas dadas de baja en esta sesión: {count}")


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
            print("[+] ¡No hay cuentas pendientes por dar de baja!")
            return

        print(f"\n[*] Ejecutando lote de bajas (máximo {args.limit} para esta sesión)...")
        execute_unfollows(cl, targets, limit=args.limit)
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
