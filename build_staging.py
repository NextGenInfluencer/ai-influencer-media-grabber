import os
import sys
import shutil
import urllib.request
import zipfile
import subprocess

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(ROOT_DIR, "dist")
CACHE_DIR = os.path.join(DIST_DIR, "cache")
STAGING_DIR = os.path.join(DIST_DIR, "app_staging")
PYTHON_DIR = os.path.join(STAGING_DIR, "python_runtime")

EMBED_URL = "https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

def download_file(url, dest_path, desc="File"):
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
        print(f"[{desc}] Using cached: {os.path.basename(dest_path)}")
        return
    print(f"[{desc}] Downloading from {url}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp, open(dest_path, 'wb') as out:
        shutil.copyfileobj(resp, out)
    print(f"[{desc}] Download complete ({os.path.getsize(dest_path) // 1024} KB)")

def remove_readonly(func, path, excinfo):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

def clean_directory(dir_path):
    if not os.path.exists(dir_path):
        return
    for attempt in range(5):
        try:
            shutil.rmtree(dir_path, onerror=remove_readonly)
            return
        except Exception:
            time.sleep(0.5)
    for root, dirs, files in os.walk(dir_path, topdown=False):
        for f in files:
            p = os.path.join(root, f)
            try:
                os.chmod(p, stat.S_IWRITE)
                os.remove(p)
            except Exception: pass
        for d in dirs:
            p = os.path.join(root, d)
            try:
                os.chmod(p, stat.S_IWRITE)
                os.rmdir(p)
            except Exception: pass

def main():
    print("\n=======================================================")
    print(" AI Influencer Media Grabber - Staging Builder v2.0")
    print("=======================================================\n")

    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # 1. Clean previous staging
    print("Cleaning previous staging directory...")
    clean_directory(STAGING_DIR)

    os.makedirs(STAGING_DIR, exist_ok=True)
    os.makedirs(PYTHON_DIR, exist_ok=True)

    # 2. Download embedded Python & get-pip
    embed_zip = os.path.join(CACHE_DIR, "python-3.10.11-embed-amd64.zip")
    get_pip_py = os.path.join(CACHE_DIR, "get-pip.py")
    download_file(EMBED_URL, embed_zip, "Python 3.10 Embed")
    download_file(GET_PIP_URL, get_pip_py, "get-pip.py")

    # 3. Extract Python Embed
    print("Extracting Python Embed to staging...")
    with zipfile.ZipFile(embed_zip, 'r') as z:
        z.extractall(PYTHON_DIR)

    # 4. Enable site-packages in python310._pth
    pth_file = os.path.join(PYTHON_DIR, "python310._pth")
    if os.path.exists(pth_file):
        with open(pth_file, 'r') as f:
            lines = f.readlines()
        with open(pth_file, 'w') as f:
            for line in lines:
                if "import site" in line:
                    f.write("import site\n")
                else:
                    f.write(line)
            f.write(".\nLib\\site-packages\n")
        print("Configured python310._pth for site-packages.")

    # 5. Install pip into Python Embed
    python_exe = os.path.join(PYTHON_DIR, "python.exe")
    print("Installing pip into portable Python...")
    shutil.copy2(get_pip_py, os.path.join(PYTHON_DIR, "get-pip.py"))
    res = subprocess.run([python_exe, "get-pip.py", "--no-warn-script-location", "-q"], cwd=PYTHON_DIR)
    if res.returncode != 0:
        print("ERROR: Failed to install pip in embedded python!")
        sys.exit(1)
    os.remove(os.path.join(PYTHON_DIR, "get-pip.py"))

    # 6. Install Core Requirements into Python Embed
    req_file = os.path.join(ROOT_DIR, "requirements.txt")
    print("Installing Core dependencies into portable Python (this takes ~15 seconds)...")
    res = subprocess.run([python_exe, "-m", "pip", "install", "-r", req_file, "--no-warn-script-location", "-q"], cwd=PYTHON_DIR)
    if res.returncode != 0:
        print("ERROR: Failed to install requirements in embedded python!")
        sys.exit(1)

    # 7. Copy Application Code & Assets
    print("Copying application files...")
    files_to_copy = [
        "app_local.py",
        "ai_prompter.py",
        "cleaner.py",
        "launch-silent.vbs",
        "run.bat",
        "install_ai.bat",
        "requirements.txt",
        "requirements-ai.txt",
        "README.md",
        "CHANGELOG.md"
    ]
    for fn in files_to_copy:
        src = os.path.join(ROOT_DIR, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(STAGING_DIR, fn))

    dirs_to_copy = ["templates", "assets"]
    for dn in dirs_to_copy:
        src = os.path.join(ROOT_DIR, dn)
        dst = os.path.join(STAGING_DIR, dn)
        if os.path.exists(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)

    # 8. Clean temporary caches from staging
    print("Purging bytecode caches from staging...")
    for root, dirs, files in os.walk(STAGING_DIR):
        for d in list(dirs):
            if d in ("__pycache__", ".git", ".idea", ".vscode"):
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                try: os.remove(os.path.join(root, f))
                except Exception: pass

    print("\n=======================================================")
    print(" [SUCCESS] Staging complete! Ready for Inno Setup.")
    print(f" Output staging directory: {STAGING_DIR}")
    print("=======================================================\n")

def find_iscc():
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    which = shutil.which("iscc")
    if which:
        return which
    return None

def compile_installer():
    print("-------------------------------------------------------")
    print(" Compiling Windows Setup Installer with Inno Setup...")
    print("-------------------------------------------------------")
    iscc = find_iscc()
    if not iscc:
        print("[WARNING] Inno Setup 6 (ISCC.exe) not found on system.")
        print("Attempting to install JRSoftware.InnoSetup via winget...")
        try:
            subprocess.run(["winget", "install", "JRSoftware.InnoSetup", "-e", "--accept-source-agreements", "--accept-package-agreements"], check=True)
            iscc = find_iscc()
        except Exception as e:
            print(f"Winget install attempt failed: {e}")

    if not iscc:
        print("\n[ERROR] Inno Setup 6 Compiler (ISCC.exe) is required to build the .exe installer.")
        print("Please download and install it from: https://jrsoftware.org/isdl.php")
        return False

    iss_file = os.path.join(ROOT_DIR, "installer.iss")
    print(f"Compiler: {iscc}")
    print("Building dist\\AI-Influencer-Media-Grabber-v2.0-Setup.exe ...")
    res = subprocess.run([iscc, "/Q", iss_file], cwd=ROOT_DIR)
    if res.returncode != 0:
        print("[ERROR] Inno Setup compilation failed!")
        return False

    output_exe = os.path.join(DIST_DIR, "AI-Influencer-Media-Grabber-v2.0-Setup.exe")
    if os.path.exists(output_exe):
        size_mb = os.path.getsize(output_exe) / (1024 * 1024)
        print("\n=======================================================")
        print(" [SUCCESS] Windows Installer (.exe) Created Successfully!")
        print(f" Installer: {output_exe}")
        print(f" File Size: {size_mb:.1f} MB ({os.path.getsize(output_exe):,} bytes)")
        print("=======================================================\n")
    return True

if __name__ == "__main__":
    main()
    if "--no-compile" not in sys.argv:
        success = compile_installer()
        if not success:
            sys.exit(1)

