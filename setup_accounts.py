import argparse
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Deteksi lokasi Chrome di Windows
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome() -> str:
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    return "chrome.exe"


def setup_account(account_id: int):
    profile_dir = os.path.join(BASE_DIR, "profiles", f"account_{account_id}")
    os.makedirs(profile_dir, exist_ok=True)
    chrome_exe = find_chrome()

    print("=" * 65)
    print(f" [LOGIN SETUP] Claude Akun #{account_id}")
    print(f" Profile Directory : {profile_dir}")
    print(f" Chrome Executable : {chrome_exe}")
    print("=" * 65)
    print("Membuka Google Chrome asli (Native Mode, bebas deteksi debugger)...")
    print("Petunjuk:")
    print(" 1. Klik 'Continue with Google' dan login dengan akun Gmail Anda.")
    print(" 2. Selesaikan login hingga masuk ke dashboard utama claude.ai.")
    print(" 3. Setelah selesai, TUTUP jendela Chrome tersebut.")
    print("=" * 65)

    # Jalankan Chrome asli secara native tanpa CDP / debugger flags
    args = [
        chrome_exe,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://claude.ai/login",
    ]

    try:
        proc = subprocess.Popen(args)
        print("\n>>> Jendela Chrome sudah terbuka.")
        print(">>> Silakan login, lalu TUTUP jendela Chrome tersebut atau tekan ENTER di sini jika sudah selesai.")
        input("\nTekan ENTER jika Anda sudah selesai login di browser... ")

        # Cek apakah proses masih jalan
        if proc.poll() is None:
            print("Menutup browser...")
            proc.terminate()
            time.sleep(1)

        print(f"\n[SUKSES] Sesi Akun #{account_id} telah tersimpan permanen di folder profil!")
    except Exception as e:
        print(f"Gagal membuka Chrome: {e}")


def main():
    parser = argparse.ArgumentParser(description="Setup login session for Claude accounts (Native Mode)")
    parser.add_argument("--account", type=int, choices=[1, 2, 3, 4], help="ID Akun (1, 2, 3, atau 4)")
    args = parser.parse_args()

    if args.account:
        setup_account(args.account)
    else:
        print("\n--- MENU SETUP LOGIN AKUN CLAUDE (NATIVE CHROME) ---")
        print("1. Login Akun #1")
        print("2. Login Akun #2")
        print("3. Login Akun #3")
        print("4. Login Akun #4")
        print("5. Keluar")
        choice = input("Pilih akun (1-4): ").strip()
        if choice in ["1", "2", "3", "4"]:
            setup_account(int(choice))
        else:
            print("Keluar.")


if __name__ == "__main__":
    main()
