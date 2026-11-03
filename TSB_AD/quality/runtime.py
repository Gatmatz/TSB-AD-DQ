"""Private runtime for the pollution frameworks, built on first use.

JENGA needs Python <3.10 and Icewafl needs Java 11 and `apache-flink==1.17.0` (Python <=3.10), so both run as
subprocesses in one isolated environment under the cache directory (`$TSBAD_HOME`, default `~/.cache/tsbad`):

    env/       Python 3.10 venv (uv) with jenga, apache-flink, pandas, numpy, scikit-learn, setuptools<81
    jdk/       Temurin 11, only if no Java 8/11 is found
    Icewafl/   chri-schi/Icewafl at a pinned commit

The first call needs network access. Overrides: ICEWAFL_PYTHON / JENGA_PYTHON (an interpreter for that framework
only), ICEWAFL_HOME and JAVA_HOME; each replaces just that part. TSBAD_AUTO_SETUP=0 fails with instructions
instead of downloading.
"""

import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ICEWAFL_COMMIT = "0da3e31374cf3e5fb0dc57946998c30ab344386f"
ICEWAFL_URL = f"https://github.com/chri-schi/Icewafl/archive/{ICEWAFL_COMMIT}.zip"
JDK_URL = "https://api.adoptium.net/v3/binary/latest/11/ga/{os}/{arch}/jdk/hotspot/normal/eclipse"
ENV_PACKAGES = ["apache-flink==1.17.0", "pandas", "numpy", "scikit-learn", "setuptools<81"]


def cache_dir():
    return Path(os.environ.get("TSBAD_HOME") or Path.home() / ".cache" / "tsbad")


def _log(msg):
    print(f"[TSB_AD.quality] {msg}", file=sys.stderr, flush=True)


def _auto_setup():
    return os.environ.get("TSBAD_AUTO_SETUP", "1") != "0"


def _require_auto(what):
    if not _auto_setup():
        raise RuntimeError(
            f"{what} is missing and TSBAD_AUTO_SETUP=0. Run `TSB_AD.quality.runtime.setup()` once "
            "or unset TSBAD_AUTO_SETUP."
        )


def _java_ok(java_home):
    java = Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")
    if not java.is_file():
        return False
    out = subprocess.run([str(java), "-version"], capture_output=True, text=True).stderr
    m = re.search(r'version "(\d+)(?:\.(\d+))?', out)
    return bool(m) and (m.group(1) in ("8", "11") or (m.group(1) == "1" and m.group(2) == "8"))


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "TSB_AD.quality"})  # Adoptium rejects the default
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def java_home():
    """Java 8/11 home: `$JAVA_HOME`, a `java` on PATH, or a Temurin 11 downloaded to the cache."""
    env = os.environ.get("JAVA_HOME")
    if env and _java_ok(env):
        return env
    on_path = shutil.which("java")
    if on_path:
        home = Path(on_path).resolve().parent.parent
        if _java_ok(home):
            return str(home)
    jdk = cache_dir() / "jdk"
    if jdk.is_dir() and _java_ok(jdk):
        return str(jdk)
    _require_auto("Java 8/11")
    system = {"Linux": "linux", "Darwin": "mac", "Windows": "windows"}[platform.system()]
    arch = {"x86_64": "x64", "AMD64": "x64", "arm64": "aarch64", "aarch64": "aarch64"}[platform.machine()]
    _log("downloading Temurin JDK 11 (one-time) ...")
    cache_dir().mkdir(parents=True, exist_ok=True)
    archive = cache_dir() / "jdk-download"
    _download(JDK_URL.format(os=system, arch=arch), archive)
    tmp = cache_dir() / "jdk-tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    if zipfile.is_zipfile(archive):
        zipfile.ZipFile(archive).extractall(tmp)
    else:
        with tarfile.open(archive) as t:
            t.extractall(tmp)
    archive.unlink()
    root = next(tmp.iterdir())
    if system == "mac":  # Contents/Home layout
        root = root / "Contents" / "Home"
    shutil.rmtree(jdk, ignore_errors=True)
    shutil.move(str(root), str(jdk))
    shutil.rmtree(tmp, ignore_errors=True)
    return str(jdk)


def _uv():
    exe = shutil.which("uv")
    if exe:
        return [exe]
    try:
        import uv  # noqa: F401  (pip dependency of the `quality` extra)
    except ImportError as e:
        raise RuntimeError("`uv` is needed to build the pollution environment: pip install uv") from e
    return [sys.executable, "-m", "uv"]


def env_python(framework=None):
    """Interpreter for `framework` ('icewafl' or 'jenga'): its `*_PYTHON` override, else the cached venv
    that has both."""
    override = os.environ.get({"icewafl": "ICEWAFL_PYTHON", "jenga": "JENGA_PYTHON"}.get(framework, ""))
    if override:
        return override
    env = cache_dir() / "env"
    py = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    ready = env / ".ready"
    if ready.is_file():
        return str(py)
    _require_auto("The pollution environment")
    _log("creating Python 3.10 environment with jenga + apache-flink (one-time) ...")
    cache_dir().mkdir(parents=True, exist_ok=True)
    uv = _uv()
    subprocess.run(uv + ["venv", "--python", "3.10", "--clear", str(env)], check=True)
    subprocess.run(uv + ["pip", "install", "--python", str(py)] + ENV_PACKAGES, check=True)
    # JENGA's metadata pins Python <3.10 and lists far more dependencies than we use: install it without them
    subprocess.run(uv + ["pip", "install", "--python", str(py), "--no-deps", "jenga"], check=True)
    ready.write_text("ok")
    return str(py)


def icewafl_home():
    env = os.environ.get("ICEWAFL_HOME")
    if env and (Path(env) / "src").is_dir():
        return env
    home = cache_dir() / "Icewafl"
    if (home / "src").is_dir():
        return str(home)
    _require_auto("The Icewafl source")
    _log("fetching Icewafl source (one-time) ...")
    cache_dir().mkdir(parents=True, exist_ok=True)
    archive = cache_dir() / "icewafl.zip"
    _download(ICEWAFL_URL, archive)
    tmp = cache_dir() / "icewafl-tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    zipfile.ZipFile(archive).extractall(tmp)
    archive.unlink()
    shutil.move(str(next(tmp.iterdir())), str(home))
    shutil.rmtree(tmp, ignore_errors=True)
    return str(home)


def setup():
    """Builds everything now instead of at the first `pollute` call. Returns the locations."""
    return {"python": env_python(), "java_home": java_home(), "icewafl_home": icewafl_home()}
