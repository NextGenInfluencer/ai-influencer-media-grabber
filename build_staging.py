import os
import sys
import shutil
import urllib.request
import zipfile
import subprocess
import stat
import time
import hashlib

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(ROOT_DIR, "dist")
CACHE_DIR = os.path.join(DIST_DIR, "cache")
STAGING_DIR = os.path.abspath(os.environ.get("MEDIA_GRABBER_STAGING_DIR") or os.path.join(DIST_DIR, "app_staging"))
OUTPUT_DIR = os.path.abspath(os.environ.get("MEDIA_GRABBER_OUTPUT_DIR") or DIST_DIR)
PYTHON_DIR = os.path.join(STAGING_DIR, "python_runtime")

EMBED_URL = "https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

DOWNLOAD_HASHES = {
    EMBED_URL: '97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297',
    GET_PIP_URL: 'fb24e693bab954209a063d90953621412ccad4a500905a726286e038f508ddf6',
    'https://nodejs.org/dist/v26.9.0/win-x64/node.exe': '8490398f5e0082772dfb0ae5a6ebdff98a97696a20cb9778b4f82eec79b6d0a1',
}

def verify_download(url, path):
    with open(path, 'rb') as handle:
        actual = hashlib.sha256(handle.read()).hexdigest()
    if actual != DOWNLOAD_HASHES[url]:
        raise RuntimeError('Download checksum mismatch: ' + url)

def download_file(url, dest_path, desc="File"):
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
        verify_download(url, dest_path)
        print(f"[{desc}] Using cached: {os.path.basename(dest_path)}")
        return
    print(f"[{desc}] Downloading from {url}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp, open(dest_path, 'wb') as out:
        shutil.copyfileobj(resp, out)
    verify_download(url, dest_path)
    print(f"[{desc}] Download complete ({os.path.getsize(dest_path) // 1024} KB)")

def remove_readonly(func, path, excinfo):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

def clean_directory(dir_path):
    expected = os.path.realpath(STAGING_DIR)
    allowed_roots = (os.path.realpath(DIST_DIR), os.path.realpath(os.path.join(ROOT_DIR, "audit_artifacts")))
    if os.path.realpath(dir_path) != expected or not any(os.path.commonpath([expected, a]) == a and expected != a for a in allowed_roots):
        raise ValueError('Refusing to clean outside the staging directory')
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
    print(" AI Influencer Media Grabber - Staging Builder v3.2.2")
    print("=======================================================\n")

    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # 1. Clean previous staging
    print("Cleaning previous staging directory...")
    clean_directory(STAGING_DIR)

    os.makedirs(STAGING_DIR, exist_ok=True)
    os.makedirs(PYTHON_DIR, exist_ok=True)

    # 2. Download embedded Python & get-pip
    embed_zip = os.path.join(CACHE_DIR, "python-3.13.16-embed-amd64.zip")
    get_pip_py = os.path.join(CACHE_DIR, "get-pip.py")
    download_file(EMBED_URL, embed_zip, "Python 3.13 Embed")
    download_file(GET_PIP_URL, get_pip_py, "get-pip.py")

    # 3. Extract Python Embed
    print("Extracting Python Embed to staging...")
    with zipfile.ZipFile(embed_zip, 'r') as z:
        z.extractall(PYTHON_DIR)

    # 4. Enable site-packages in python313._pth
    pth_file = os.path.join(PYTHON_DIR, "python313._pth")
    if os.path.exists(pth_file):
        with open(pth_file, 'r') as f:
            lines = f.readlines()
        with open(pth_file, 'w') as f:
            for line in lines:
                if "import site" in line:
                    f.write("import site\n")
                else:
                    f.write(line)
            f.write(".\n..\nLib\\site-packages\n")
        print("Configured python313._pth for site-packages.")

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
    res = subprocess.run([python_exe, "-m", "pip", "install", "--only-binary=:all:", "-r", req_file, "--no-warn-script-location", "-q"], cwd=PYTHON_DIR)
    if res.returncode != 0:
        print("ERROR: Failed to install requirements in embedded python!")
        sys.exit(1)

    node_path = os.path.join(CACHE_DIR, 'node-v26.9.0.exe')
    download_file('https://nodejs.org/dist/v26.9.0/win-x64/node.exe', node_path, 'Node runtime')
    os.makedirs(os.path.join(STAGING_DIR, 'node_runtime'), exist_ok=True)
    shutil.copy2(node_path, os.path.join(STAGING_DIR, 'node_runtime', 'node.exe'))

    # 7. Copy Application Code & Assets
    print("Copying application files...")
    # The updater and installer share the application payload manifest.
    from safe_update import FILES, DIRECTORIES
    files_to_copy = sorted(FILES | {
        'launch-silent.vbs', 'run.bat', 'install_ai.bat', 'RELEASE_NOTES.md'
    })
    for fn in files_to_copy:
        src = os.path.join(ROOT_DIR, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(STAGING_DIR, fn))

    dirs_to_copy = sorted(DIRECTORIES)
    for dn in dirs_to_copy:
        src = os.path.join(ROOT_DIR, dn)
        dst = os.path.join(STAGING_DIR, dn)
        if os.path.exists(src):
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=lambda path, names: ['custom'] if os.path.normpath(path) == os.path.normpath(os.path.join(ROOT_DIR, 'static', 'fonts')) else [])

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
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Inno Setup 6", "ISCC.exe"),
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
    print("Building dist\\AI-Influencer-Media-Grabber-v3.2.2-Setup.exe ...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    res = subprocess.run([iscc, "/Q", f"/DMyStagingDir={STAGING_DIR}", f"/DMyOutputDir={OUTPUT_DIR}", iss_file], cwd=ROOT_DIR)
    if res.returncode != 0:
        print("[ERROR] Inno Setup compilation failed!")
        return False

    output_exe = os.path.join(OUTPUT_DIR, "AI-Influencer-Media-Grabber-v3.2.2-Setup.exe")
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

