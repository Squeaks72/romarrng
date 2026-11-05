"""ROMarr's window onto ROM Hub — the plugin layer of the Cartridge ecosystem.

ROMarr acquires games; ROM Hub is where the *sources* it can acquire from live,
as sandboxed, backend-agnostic plugins. This module is the thin bridge: it reads
the Hub's plugin catalogue and installed state through the Hub's own Python API
(the same one its CLI uses), so the ROMarr UI can show every plugin, install one,
and turn it on or off — without ROMarr reimplementing any of the Hub's logic.

Everything here is read-through-then-act: the source of truth stays the Hub's
registry on disk (`$ROM_HUB_HOME`). ROMarr never edits it directly.
"""
from __future__ import annotations

import dataclasses
import contextvars
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_PLUGIN_RUNTIME_CONTEXT = contextvars.ContextVar(
    "romarr_hub_plugin_runtime", default=None)
_PLUGIN_RUNTIME_LOCK = threading.Lock()
_PLUGIN_RUNTIME_INSTALLED = False
_PLUGIN_BOOTSTRAP = """\
import os, resource, sys, sysconfig
file_limit = 64 * 1024 * 1024
file_soft, file_hard = resource.getrlimit(resource.RLIMIT_FSIZE)
if file_hard != resource.RLIM_INFINITY:
    file_limit = min(file_limit, file_hard)
resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
cwd = os.path.realpath(os.getcwd())
sys.path[:] = [p for p in sys.path if p and os.path.realpath(p) != cwd]
for key in ("purelib", "platlib"):
    path = sysconfig.get_paths().get(key)
    if path and path not in sys.path:
        sys.path.append(path)
# Do not run .pth or sitecustomize hooks from installed packages before the
# filesystem policy. The trusted hook is supplied through ROMARR's private
# PYTHONPATH and installs Landlock before the Hub runner or plugin is loaded.
import sitecustomize
# Load the trusted SDK runner and all of its imports before making the plugin
# directory importable. A plugin can contain a package named rom_hub_sdk or a
# dependency such as pydantic; neither may run before the SDK installs its own
# network/exec filter.
import rom_hub_sdk.runner as trusted_runner
plugin_dir = os.environ.pop("ROMARR_HUB_PLUGIN_DIR", "")
if not plugin_dir:
    raise RuntimeError("ROMarr Hub plugin directory is missing")
sys.path.insert(0, plugin_dir)
trusted_runner.main()
"""

# ROM Hub keeps its state (catalog cache, installed plugins) under this home.
# ROMarr gives it a stable directory it owns so state survives restarts.
HOME = Path(os.environ.get("ROM_HUB_HOME", "/opt/romarr/.rom-hub"))
os.environ.setdefault("ROM_HUB_HOME", str(HOME))


def _backend_env() -> dict:
    """Hand ROMarr's own library credentials to the Hub.

    ROMarr already knows which library it files into and how to authenticate to
    it; the Hub needs the same thing to run `import` and `enrich`. Left to
    itself the Hub reads its own variables and finds nothing, so a plugin
    installed from the Hub tab could be listed but never used. The names differ
    by one word -- ROMarr reads ROMM_USERNAME, the Hub reads ROMM_USER -- so the
    mapping is explicit rather than assumed.
    """
    env = {}
    url = os.environ.get("LIBRARY_URL") or os.environ.get("ROMM_URL", "")
    user = os.environ.get("LIBRARY_USERNAME") or os.environ.get("ROMM_USERNAME", "")
    pw = os.environ.get("LIBRARY_PASSWORD") or os.environ.get("ROMM_PASSWORD", "")
    kind = (os.environ.get("LIBRARY_KIND") or "romm").strip().lower()
    if url:
        env["ROMM_URL"] = url
        env["ROM_HUB_BACKEND"] = kind
    # A plugin is third-party code. It does not get the library password unless
    # the operator opts in; by default it can search and fetch, and ROMarr does
    # the filing itself.
    if os.environ.get("ROMARR_PLUGIN_BACKEND_CREDENTIALS") == "1":
        if user:
            env["ROMM_USER"] = user
        if pw:
            env["ROMM_PASSWORD"] = pw
    return env


def _import():
    """Import the Hub lazily so ROMarr still starts if it isn't installed."""
    from rom_hub import catalog_sources, registry  # noqa: WPS433
    return catalog_sources, registry


def available() -> bool:
    try:
        _import()
        return True
    except Exception:
        return False


def _installed_slugs(registry) -> dict:
    """slug -> {enabled, version, commit} for what's installed, best-effort."""
    out = {}
    try:
        reg = registry.Registry(HOME)
        for p in reg.installed():
            # InstalledPlugin: slug, path, manifest, enabled, config, commit.
            # The installed version lives in the plugin's own manifest.
            slug = getattr(p, "slug", None)
            manifest = getattr(p, "manifest", {}) or {}
            if slug:
                out[slug] = {
                    "enabled": bool(getattr(p, "enabled", True)),
                    "version": manifest.get("version", "") if isinstance(manifest, dict) else "",
                    "commit": (getattr(p, "commit", "") or "")[:8],
                }
    except Exception:
        pass
    return out


def plugins() -> dict:
    """The whole plugin catalogue, annotated with install/enabled state.

    Shape mirrors ROMarr's other list endpoints: {"items": [...], "error": ...}.
    Each item is safe to render directly in the Hub tab.
    """
    try:
        catalog_sources, registry = _import()
    except Exception as exc:
        return {"items": [], "error": f"ROM Hub is not installed: {exc}"}

    try:
        merged = catalog_sources.load_all(HOME)
    except Exception as exc:
        return {"items": [], "error": f"could not read the plugin catalog: {exc}"}

    installed = _installed_slugs(registry)
    items = []
    for sourced in merged.entries:
        e = getattr(sourced, "entry", sourced)
        d = dataclasses.asdict(e) if dataclasses.is_dataclass(e) else dict(vars(e))
        slug = d.get("slug")
        inst = installed.get(slug)
        items.append({
            "slug": slug,
            "name": d.get("name") or slug,
            "author": d.get("author") or "",
            "version": d.get("version") or "",
            "repository": d.get("repository") or "",
            "capabilities": list(d.get("capabilities") or []),
            "network": list(d.get("network") or []),
            "description": d.get("description") or "",
            "key_required": bool(d.get("key_required")),
            "platforms": list(d.get("platforms") or []),
            "installed": inst is not None,
            "enabled": inst["enabled"] if inst else False,
        })
    items.sort(key=lambda x: (not x["installed"], x["slug"]))
    return {
        "items": items,
        "installed_count": sum(1 for i in items if i["installed"]),
        "total": len(items),
        "error": None,
    }


#: Environment a plugin subprocess is allowed to inherit.
#:
#: It used to get `dict(os.environ, ...)` -- ROMarr's entire environment, which
#: is where ROMARR_API_KEY, ROMARR_PASSWORD, PROWLARR_API_KEY, QBITTORRENT_PASS
#: and LIBRARY_PASSWORD all live. A plugin needs a library to import into; it
#: has no business holding the key to ROMarr itself or the password to the
#: torrent client, and "it is probably fine" is not a trust boundary.
#:
#: Only what a process needs to run at all is passed through, plus the library
#: credentials `_backend_env` hands over deliberately. Anything else a plugin
#: wants has to be configured on the plugin.
_ENV_PASSTHROUGH = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR",
                    "SYSTEMROOT", "TEMP", "TMP",
                    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                    "http_proxy", "https_proxy", "no_proxy")



#: Setuid helper that runs a plugin as a separate, unprivileged uid. It is the
#: confinement used when the kernel has no Landlock (Unraid): the plugin cannot
#: read ROMarr's 0600 state file, which holds every credential ROMarr has.
_PLUGIN_LAUNCHER = "/usr/local/libexec/romarr-plugin-launch"
_PLUGIN_UID = 10001
_UID_ISOLATION_CACHE: tuple | None = None


def uid_isolation_state() -> tuple[bool, str]:
    """Whether plugins can run as a separate uid, proved by actually doing it."""
    global _UID_ISOLATION_CACHE
    if _UID_ISOLATION_CACHE is not None:
        return _UID_ISOLATION_CACHE
    result: tuple[bool, str]
    try:
        st = os.stat(_PLUGIN_LAUNCHER)
        if not (st.st_mode & 0o4000) or st.st_uid != 0:
            result = (False, "plugin launcher is not installed setuid root")
        elif st.st_mode & 0o001:
            result = (False, "plugin launcher is executable by everyone")
        elif not os.access(_PLUGIN_LAUNCHER, os.X_OK):
            result = (False, "plugin launcher is not executable by ROMarr's user")
        elif os.getuid() == _PLUGIN_UID:
            result = (False, "ROMarr itself runs as the plugin uid")
        else:
            p = subprocess.run([_PLUGIN_LAUNCHER, sys.executable, "-c",
                                "import os;print(os.getuid(),os.getgid(),"
                                "len(os.getgroups()))"],
                               capture_output=True, text=True, timeout=15)
            if p.stdout.split() != [str(_PLUGIN_UID), str(_PLUGIN_UID), "0"]:
                result = (False, "plugin launcher did not drop privileges: "
                          + (p.stderr.strip() or p.stdout.strip())[:120])
            else:
                result = (True, f"plugins run as uid {_PLUGIN_UID}, "
                          "separate from ROMarr")
    except Exception as err:  # noqa: BLE001
        result = (False, f"plugin launcher unavailable ({err.__class__.__name__})")
    _UID_ISOLATION_CACHE = result
    return result


def _uid_mode() -> bool:
    """True when this host has no Landlock and plugins go through the launcher."""
    try:
        from .plugin_runtime.landlock import probe as probe_landlock
        if probe_landlock()[0]:
            return False
    except Exception:  # noqa: BLE001
        pass
    return uid_isolation_state()[0]


def sandbox_state() -> tuple[bool, str]:
    """Whether ROM Hub can confine a plugin here, and why not if it cannot.

    The Hub runs each plugin as a subprocess whose only route outward is an RPC
    back to the host, checked against the hosts that plugin declared. ROMarr
    adds Landlock filesystem rules to the Hub's seccomp network/exec boundary.
    Both have to be available before plugin work starts by default.

    Reported rather than assumed, so the Plugins page can say which of the two
    states an install is actually in.
    """
    uid_ok = False
    try:
        from .plugin_runtime.landlock import probe as probe_landlock
        files_ok, files_why = probe_landlock()
        if not files_ok:
            uid_ok, uid_why = uid_isolation_state()
            if not uid_ok:
                return False, (f"filesystem confinement unavailable: {files_why}; "
                               f"uid isolation unavailable: {uid_why}")
    except Exception as err:  # noqa: BLE001
        return False, f"filesystem confinement probe failed: {err.__class__.__name__}"
    try:
        from .plugin_runtime.scratch import probe as probe_scratch
        scratch_ok, scratch_why = probe_scratch()
        if not scratch_ok:
            return False, f"bounded plugin scratch unavailable: {scratch_why}"
    except Exception as err:  # noqa: BLE001
        return False, f"plugin scratch probe failed: {err.__class__.__name__}"
    try:
        from rom_hub.sandbox import probe
    except Exception as err:  # noqa: BLE001 - the Hub may not be installed
        return False, f"ROM Hub is not available ({err.__class__.__name__})"
    try:
        return probe()
    except Exception as err:  # noqa: BLE001
        detail = str(err).strip()
        suffix = f": {detail}" if detail else ""
        return False, f"sandbox probe failed: {err.__class__.__name__}{suffix}"


def _plugin_env() -> dict:
    """The environment a plugin subprocess runs with.

    Built by allowlist rather than by subtraction: a denylist silently stops
    covering anything added later, and the thing added later is exactly the
    credential nobody thought about.
    """
    env = {name: os.environ[name] for name in _ENV_PASSTHROUGH
           if name in os.environ}
    env["ROM_HUB_HOME"] = str(HOME)
    ok, why = sandbox_state()
    if not ok:
        if os.environ.get("ROMARR_ALLOW_UNSANDBOXED_PLUGINS") != "1":
            raise RuntimeError(
                "ROM Hub plugin confinement is unavailable: " + why
                + ". Enable Linux Landlock, a finite tmpfs for plugin scratch, "
                "and pyseccomp, or explicitly set "
                "ROMARR_ALLOW_UNSANDBOXED_PLUGINS=1 to run without it.")
        log.warning("running plugins WITHOUT confinement by explicit operator "
                    "choice: %s", why)
        env["ROM_HUB_ALLOW_UNSANDBOXED"] = "1"
    env.update(_backend_env())
    return env


def _plugin_runtime_context(process) -> dict:
    """Private paths the child may use during one PluginProcess lifetime."""
    runtime_dir = Path(__file__).with_name("plugin_runtime").resolve(strict=True)
    if not (runtime_dir / "sitecustomize.py").is_file():
        raise RuntimeError("trusted ROMarr plugin bootstrap is missing")

    plugin_dir = Path(process.plugin_dir).resolve(strict=True)
    plugin_root = (HOME / "plugins").resolve(strict=True)
    if not plugin_dir.is_dir() or plugin_dir == plugin_root \
            or not plugin_dir.is_relative_to(plugin_root):
        raise RuntimeError("installed plugin path escapes the ROM Hub plugin directory")

    assets = []
    for value in (getattr(process, "data_assets", {}) or {}).values():
        asset = Path(value).resolve(strict=True)
        if not asset.is_file():
            raise RuntimeError("ROM Hub data asset is not a regular file")
        assets.append(str(asset))

    from .plugin_runtime.scratch import tmpfs_root
    scratch = Path(tempfile.mkdtemp(
        prefix="romarr-hub-plugin-", dir=str(tmpfs_root()))).resolve()
    # tempfile.mkdtemp creates this private to the owning process user (0700).
    child_env = {
        "HOME": str(scratch),
        "TMPDIR": str(scratch),
        "TEMP": str(scratch),
        "TMP": str(scratch),
        "PYTHONPATH": str(runtime_dir),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "ROMARR_HUB_LANDLOCK": "1",
        "ROMARR_HUB_PLUGIN_DIR": str(plugin_dir),
        "ROMARR_HUB_DATA_ASSETS": json.dumps(assets),
        "ROMARR_HUB_SCRATCH": str(scratch),
    }
    if _uid_mode():
        # The plugin runs as another uid, so it must be able to use its own
        # scratch directory. The name is random and the parent is a private
        # tmpfs; the plugin uid is the only other user that exists to see it.
        os.chmod(scratch, 0o777)
        child_env["ROMARR_HUB_ISOLATION"] = "uid"
        child_env["ROMARR_HUB_PROTECT"] = os.environ.get(
            "ROMARR_DATA", "/config/romarr.json")
        child_env.pop("ROMARR_HUB_LANDLOCK", None)
    return {"plugin_dir": plugin_dir, "scratch": scratch,
            "child_env": child_env}


def _remove_plugin_scratch(process) -> None:
    scratch = getattr(process, "_romarr_plugin_scratch", None)
    if scratch:
        shutil.rmtree(scratch, ignore_errors=True)
        process._romarr_plugin_scratch = None


def _install_plugin_runtime_hardening(plugin_process, broker_host) -> None:
    """Make every Hub plugin start through the trusted Landlock bootstrap.

    ROM Hub's own runner installs seccomp before importing plugin code. Its
    current command starts Python from the plugin directory, though, which
    would allow a plugin-provided ``sitecustomize.py`` to run before that
    filter. This wrapper removes the working directory from ``sys.path`` and
    calls the trusted ``sitecustomize`` under ``-S`` before loading the SDK
    runner. The runner's package and imports are resolved while only trusted
    paths are available; plugin imports are enabled only afterward. ContextVars
    keep per-plugin paths isolated across Hub's fan-out threads.
    """
    global _PLUGIN_RUNTIME_INSTALLED
    if _PLUGIN_RUNTIME_INSTALLED:
        return
    with _PLUGIN_RUNTIME_LOCK:
        if _PLUGIN_RUNTIME_INSTALLED:
            return

        original_environment = broker_host.plugin_environment
        original_start = plugin_process.start
        original_close = plugin_process.close
        original_popen = subprocess.Popen

        def plugin_environment(base=None):
            env = original_environment(base)
            runtime = _PLUGIN_RUNTIME_CONTEXT.get()
            if runtime is not None:
                env.update(runtime["child_env"])
            return env

        def guarded_popen(args, *args_tail, **kwargs):
            runtime = _PLUGIN_RUNTIME_CONTEXT.get()
            if runtime is None:
                return original_popen(args, *args_tail, **kwargs)
            expected = [sys.executable, "-m", "rom_hub_sdk.runner"]
            cwd = kwargs.get("cwd")
            try:
                resolved_cwd = Path(cwd).resolve(strict=True)
            except (OSError, TypeError):
                resolved_cwd = None
            if list(args) != expected or resolved_cwd != runtime["plugin_dir"]:
                raise RuntimeError("unsupported ROM Hub plugin runner command")
            command = [sys.executable, "-S", "-c", _PLUGIN_BOOTSTRAP]
            if runtime["child_env"].get("ROMARR_HUB_ISOLATION") == "uid":
                command = [_PLUGIN_LAUNCHER] + command
            return original_popen(command, *args_tail, **kwargs)

        def start_confined(process):
            runtime = _plugin_runtime_context(process)
            process._romarr_plugin_scratch = runtime["scratch"]
            token = _PLUGIN_RUNTIME_CONTEXT.set(runtime)
            try:
                return original_start(process)
            except BaseException:
                _remove_plugin_scratch(process)
                raise
            finally:
                _PLUGIN_RUNTIME_CONTEXT.reset(token)

        def close_confined(process):
            try:
                return original_close(process)
            finally:
                _remove_plugin_scratch(process)

        broker_host.plugin_environment = plugin_environment
        plugin_process.start = start_confined
        plugin_process.close = close_confined
        subprocess.Popen = guarded_popen
        _PLUGIN_RUNTIME_INSTALLED = True


def _run_cli(*args, timeout=180):
    """Run the Hub CLI in ROMarr's own interpreter and capture the result.

    Install/enable/disable are one-shot operations the Hub already implements;
    shelling out to its entry point is the honest way to reuse them without
    copying the registry-mutation code here.

    This subprocess manages the registry; installed plugin code runs later in
    the Hub's own worker boundary. `_plugin_env` refuses to start the CLI when
    filesystem or seccomp confinement is unavailable unless the operator has
    explicitly accepted an unconfined plugin runtime.
    """
    import subprocess
    import sys
    # The Hub ships a `rom-hub` console script next to the interpreter; it has no
    # `python -m rom_hub` entry point. Prefer the script; fall back to the CLI
    # module's main() if the script isn't on PATH.
    script = Path(sys.executable).with_name("rom-hub")
    if script.exists():
        cmd = [str(script), *args]
    else:
        cmd = [sys.executable, "-c",
               "import sys; from rom_hub.cli import main; sys.exit(main())", *args]
    try:
        env = _plugin_env()
    except RuntimeError as exc:
        return {"ok": False, "out": "", "err": str(exc), "code": -1}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        ok = p.returncode == 0
        return {"ok": ok, "out": (p.stdout or "").strip(),
                "err": (p.stderr or "").strip(), "code": p.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "out": "", "err": "timed out", "code": -1}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "out": "", "err": str(exc), "code": -1}


def install(slug: str) -> dict:
    """Install one catalog plugin.

    `plugin install` is non-interactive and takes no confirmation flag; the
    trust warning a human needs is shown in the UI before the button is pressed.
    """
    return _run_cli("plugin", "install", slug)


# ------------------------------------------------------------- search/fetch --
#
# The two in-process bridges the acquisition pipeline needs: `search` asks
# every enabled plugin that declares the capability, and `fetch` downloads one
# chosen result into a staging directory through the plugin's own gated plan.
# Both go through the Hub's own machinery -- PluginProcess, FetchPlan
# allowlisting, HttpDownloader -- so the confinement and network policy a
# plugin runs under are the Hub's, not a copy of them here.

import base64
import json as _json

HUB_SCHEME = "hub://"


def encode_result(row: dict) -> str:
    """A search result as a grabbable URL.

    The download pipeline speaks URLs: `Release.download_url` is what
    `hand_off` gives a client. A hub result is not a URL -- it is a
    (plugin, source_id) pair the plugin can turn back into a FetchPlan -- so
    the whole row rides along, base64-encoded. Opaque by design: nothing
    downstream parses it except `fetch`, and a credential-free encoding keeps
    it safe to store in the ledger and the queue.
    """
    raw = _json.dumps(row, sort_keys=True).encode("utf-8")
    if len(raw) > 65536:
        raise ValueError("Hub result is too large")
    payload = base64.urlsafe_b64encode(raw).decode("ascii")
    return HUB_SCHEME + payload


def decode_result(url: str) -> dict:
    """The search result inside a `hub://` URL. Raises ValueError if it is
    not one or does not decode -- a corrupt ledger row must fail loudly, not
    silently fetch nothing."""
    if not str(url or "").startswith(HUB_SCHEME):
        raise ValueError("not a hub:// URL")
    if len(url) > 90000:
        raise ValueError("Hub URL is too large")
    try:
        raw = base64.urlsafe_b64decode(
            url[len(HUB_SCHEME):].encode("ascii"))
        row = _json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("undecodable hub URL") from exc
    if not isinstance(row, dict) or not row.get("source_id"):
        raise ValueError("hub URL carries no source_id")
    if not isinstance(row.get("plugin"), str) or not row["plugin"]:
        raise ValueError("hub URL carries no plugin")
    return row


def _unsandboxed() -> bool:
    """Whether Hub calls from this process may run plugins unconfined.

    Apply the same explicit operator opt-in as the CLI bridge.
    """
    ok, why = sandbox_state()
    if not ok:
        if os.environ.get("ROMARR_ALLOW_UNSANDBOXED_PLUGINS") != "1":
            raise RuntimeError("ROM Hub plugin confinement is unavailable: " + why)
        log.warning("ROM Hub calls run WITHOUT confinement by explicit "
                    "operator choice: %s", why)
    return not ok


def searchable_plugins() -> list[str]:
    """Slugs of installed, enabled plugins that declare `search`."""
    try:
        _, registry = _import()
        reg = registry.Registry(HOME)
        return sorted(p.slug for p in reg.installed()
                      if getattr(p, "enabled", True)
                      and "search" in (getattr(p.manifest, "capabilities", ())
                                       or ()))
    except Exception:
        return []


def search(query: str, platform: str | None = None, limit: int = 25,
           timeout: float = 30.0) -> tuple[list[dict], str]:
    """Search every enabled ROM Hub plugin, merged.

    Returns `(rows, error)`. Rows are plain dicts with the Hub's SearchResult
    fields (source_id, title, platform, size_bytes, url, plugin). `error` is
    a string when the Hub itself could not be used at all; a single plugin
    failing is not an error -- the Hub's fan-out already isolates those, and
    "two of three sources answered" is a normal search, not a fault.
    """
    try:
        from rom_hub import registry as _registry
        from rom_hub.broker import host as _broker_host
        from rom_hub.broker.host import PluginProcess
        from rom_hub.broker.fetcher import HttpxFetcher
        from rom_hub.dispatcher import search_all
        from rom_hub.cli import prepare_assets, prepare_secrets
    except Exception as exc:
        return [], f"ROM Hub is not installed: {exc}"
    try:
        _install_plugin_runtime_hardening(PluginProcess, _broker_host)
    except Exception as exc:
        return [], f"ROM Hub filesystem confinement could not start ({type(exc).__name__})"
    try:
        plugins = [p for p in _registry.Registry(HOME).installed()
                   if getattr(p, "enabled", True)
                   and "search" in (getattr(p.manifest, "capabilities", ())
                                    or ())]
    except Exception as exc:
        return [], f"could not read the plugin registry: {exc}"
    if not plugins:
        return [], ""
    fetcher = HttpxFetcher()
    try:
        outcome = search_all(plugins, fetcher=fetcher, query=query,
                             platform=platform, limit=limit, timeout=timeout,
                             assets_for=lambda plugin: prepare_assets(plugin, HOME),
                             secrets_for=lambda plugin: prepare_secrets(plugin, HOME),
                             allow_unsandboxed=_unsandboxed())
    except Exception as exc:
        return [], f"ROM Hub search failed ({type(exc).__name__})"
    finally:
        fetcher.close()
    statuses = getattr(outcome, "statuses", [])
    if statuses and all(not status.ok for status in statuses):
        return [], "All enabled ROM Hub search plugins failed; check their configuration and connectivity."
    rows = []
    for r in outcome.results:
        try:
            rows.append(r.model_dump())
        except Exception:  # pragma: no cover -- pydantic model, always dumps
            rows.append(dict(r))
    return rows, ""


def fetch(row: dict, dest_dir) -> dict:
    """Download one search result into `dest_dir` through its plugin.

    The plugin is asked for a FetchPlan -- the Hub re-validates the shape and
    allowlists every URL against the manifest's declared hosts -- and the
    Hub's own downloader streams the files. This is the download half of the
    Hub's `import`; the upload half deliberately does not run here, because
    ROMarr's import pipeline (DAT verification, naming, history, blocklist)
    owns what happens to a finished file.
    """
    from pathlib import Path
    try:
        from rom_hub import registry as _registry
        from rom_hub.broker import host as _broker_host
        from rom_hub.broker.fetcher import HttpxFetcher
        from rom_hub.broker.host import PluginProcess
        from rom_hub.importer import HttpDownloader
        from rom_hub.types import SearchResult
        from rom_hub.cli import prepare_assets, prepare_secrets
    except Exception as exc:
        return {"ok": False, "error": f"ROM Hub is not installed: {exc}",
                "files": []}
    try:
        _install_plugin_runtime_hardening(PluginProcess, _broker_host)
    except Exception as exc:
        return {"ok": False,
                "error": f"ROM Hub filesystem confinement could not start ({type(exc).__name__})",
                "files": []}
    slug = str(row.get("plugin") or "")
    try:
        result = SearchResult(**row)
    except Exception as exc:
        return {"ok": False, "error": f"invalid hub result: {exc}", "files": []}
    try:
        plugin = _registry.Registry(HOME).get(slug)
    except Exception as exc:
        return {"ok": False,
                "error": f"plugin {slug!r} is not installed: {exc}",
                "files": []}
    if not getattr(plugin, "enabled", True):
        return {"ok": False,
                "error": f"plugin {slug!r} is disabled", "files": []}
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    fetcher = HttpxFetcher()
    try:
        with PluginProcess(plugin_dir=plugin.path, manifest=plugin.manifest,
                           config=getattr(plugin, "config", {}) or {},
                           fetcher=fetcher,
                           data_assets=prepare_assets(plugin, HOME),
                           secrets=prepare_secrets(plugin, HOME),
                           allow_unsandboxed=_unsandboxed()) as proc:
            plan = proc.plan(result)
            with HttpDownloader(
                    allowlist=list(getattr(plugin.manifest, "network", [])
                                   or [])) as downloader:
                files = []
                for f in plan.files:
                    destination = (dest / f.relative_path()).resolve()
                    if not destination.is_relative_to(dest.resolve()):
                        raise ValueError("plugin output escapes the staging directory")
                    saved = downloader.download(f.url,
                                                destination,
                                                f.size_bytes)
                    files.append(str(saved))
    except Exception as exc:
        return {"ok": False,
                "error": f"plugin fetch failed ({type(exc).__name__})", "files": []}
    finally:
        fetcher.close()
    return {"ok": True, "error": "", "files": files}


def _set_enabled(slug: str, on: bool) -> dict:
    """Toggle enable/disable through the registry directly — no subprocess."""
    try:
        _, registry = _import()
        reg = registry.Registry(HOME)
        reg.set_enabled(slug, on)
        return {"ok": True, "out": f"{'enabled' if on else 'disabled'} {slug}",
                "err": "", "code": 0}
    except Exception as exc:
        # fall back to the CLI verb
        return _run_cli("plugin", "enable" if on else "disable", slug)


def enable(slug: str) -> dict:
    return _set_enabled(slug, True)


def disable(slug: str) -> dict:
    return _set_enabled(slug, False)


def uninstall(slug: str) -> dict:
    """ROM Hub has no uninstall, and saying so beats a usage dump.

    Neither the CLI nor `registry.Registry` implements one -- `plugin` offers
    install, browse, list, enable, disable, assets, config and secret, and the
    registry has install/get/installed/set_enabled/set_config and nothing that
    removes. Shelling out to `plugin uninstall` therefore printed argparse's
    list of valid choices, which reads like a bug in ROMarr rather than a
    capability the Hub does not have.

    Disabling is the supported way to stop a plugin being used: it drops out of
    the fan-out and any command aimed at it refuses. Removing the directory by
    hand would leave the registry's state.json still listing it, which is why
    that is not done from here either.
    """
    return {
        "ok": False,
        "out": "",
        "err": (
            f"ROM Hub cannot uninstall a plugin: neither its CLI nor its "
            f"registry implements one. Disable {slug!r} instead -- it then "
            f"drops out of search and every command aimed at it refuses. To "
            f"remove it from disk entirely, delete "
            f"$ROM_HUB_HOME/plugins/{slug} and its entry in "
            f"$ROM_HUB_HOME/state.json together; removing only one of the two "
            f"leaves the registry inconsistent."
        ),
        "code": -1,
    }


# Applied at import so in-process Hub calls see the same backend the CLI does.
for _k, _v in _backend_env().items():
    os.environ.setdefault(_k, _v)
