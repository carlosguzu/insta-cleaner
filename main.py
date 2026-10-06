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
EXEMPT_OVER_2K_FILE = Path("exempt_over_2k.txt")
EXEMPT_PRIVATE_FILE = Path("exempt_private.txt")
CANDIDATES_FILE = Path("candidates_to_unfollow.txt")
UNFOLLOWED_LOG_FILE = Path("unfollowed.txt")


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

    exempt_over_2k: list[str] = []
    exempt_private: list[str] = []
    to_unfollow: list[tuple[int, str]] = []

    # Cargar cuentas ya analizadas si existen para permitir reanudar
    processed_candidates = set()
    if CANDIDATES_FILE.exists():
        processed_candidates = set(CANDIDATES_FILE.read_text(encoding="utf-8").splitlines())
    processed_over_2k = set()
    if EXEMPT_OVER_2K_FILE.exists():
        for line in EXEMPT_OVER_2K_FILE.read_text(encoding="utf-8").splitlines():
            if line:
                processed_over_2k.add(line.split()[0].replace("@", ""))
    processed_private = set()
    if EXEMPT_PRIVATE_FILE.exists():
        processed_private = set(EXEMPT_PRIVATE_FILE.read_text(encoding="utf-8").splitlines())

    already_processed = processed_candidates | processed_over_2k | processed_private

    # Abrir archivos en modo append con autoflush para guardar en tiempo real
    f_2k = EXEMPT_OVER_2K_FILE.open("a", encoding="utf-8")
    f_priv = EXEMPT_PRIVATE_FILE.open("a", encoding="utf-8")
    f_cand = CANDIDATES_FILE.open("a", encoding="utf-8")

    print("\n[*] Inspeccionando perfiles para filtrar excepciones...")
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

                if follower_count > 2000:
                    exempt_over_2k.append(f"{username} ({follower_count} seguidores)")
                    f_2k.write(f"{username} ({follower_count} seguidores)\n")
                    f_2k.flush()
                    print(f"[{idx:4d}/{total:4d}] @{username:<25} {status_str} -> EXENTO (>2k)")
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
        f_2k.close()
        f_priv.close()
        f_cand.close()

    return exempt_over_2k, exempt_private, to_unfollow


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


def main():
    args = parse_arguments()

    if args.reset_session:
        for f in [SESSION_FILE, Path(".sessionid")]:
            if f.exists():
                f.unlink()
                print(f"[*] Archivo de sesión eliminado: {f.name}")
        print("[+] Sesión reiniciada. Ahora puedes ingresar una nueva cuenta.")

    if args.clear_cache:
        for f in [EXEMPT_OVER_2K_FILE, EXEMPT_PRIVATE_FILE, CANDIDATES_FILE]:
            if f.exists():
                f.unlink()
                print(f"[*] Archivo borrado: {f.name}")
        print("[+] Listas anteriores limpiadas.")

    cl = get_client()

    exempt_over_2k, exempt_private, candidates = analyze_relationships(cl)

    print("\n" + "=" * 50)
    print("RESUMEN DE AUDITORÍA")
    print("=" * 50)
    print(f"Exentos con más de 2.000 seguidores : {len(exempt_over_2k)} (guardado en {EXEMPT_OVER_2K_FILE.resolve()})")
    print(f"Exentos por ser cuenta privada      : {len(exempt_private)} (guardado en {EXEMPT_PRIVATE_FILE.resolve()})")
    print(f"Candidatos para dejar de seguir     : {len(candidates)} (guardado en {CANDIDATES_FILE.resolve()})")
    print("=" * 50)

    if not args.execute:
        print("\n[MODO SIMULACIÓN / DRY-RUN]")
        print("No se ha ejecutado ningún unfollow.")
        print("Para ejecutar bajas reales de forma segura, ejecuta con el flag --execute:")
        print("  uv run main.py --execute")
        return

    execute_unfollows(cl, candidates, limit=args.limit)


if __name__ == "__main__":
    main()
