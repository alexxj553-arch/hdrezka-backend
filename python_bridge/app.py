"""HDRezka adapter with configurable mirror registry and safe URL validation.

Mirror checks are best-effort HTTP reachability checks. A reachable mirror does not
guarantee that every page or video endpoint works with the installed third-party
library. No DRM or access-control bypass is attempted.
"""
from __future__ import annotations

import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(title="HDRezka Python Bridge", version="0.2.0")
_LOCK = threading.RLock()
_TIMEOUT = max(1.0, min(float(os.getenv("MIRROR_CHECK_TIMEOUT_SECONDS", "5")), 15.0))
_DEFAULT_MIRRORS = (
    "hdrezka.ag,rezka.ag,hdrezka-fly.net,hdrezka-home.tv,hdrezka-sonic.net,"
    "hdrezka.club,hdrezka.hk,hdrezka.kim,hdrezka.mn,hdrezka.name,hdrezka.sh,"
    "hdrezka.website,hello-rezka.tv,omnirezka.tv,rezka-kz.tv,rezka-ua.co,"
    "rezka-ua.in,rezka-ua.net,rezka-ua.pub,rezka.pub,hdrzk.org"
)
_ALLOWED_HOSTS = {
    host.strip().lower().rstrip(".")
    for host in os.getenv("HDREZKA_ALLOWED_HOSTS", _DEFAULT_MIRRORS).split(",")
    if host.strip()
}
_configured = [f"https://{host}" for host in os.getenv("HDREZKA_MIRRORS", "").split(",") if host.strip()]
_mirrors: list[str] = []
_active_mirror = os.getenv("HDREZKA_ACTIVE_MIRROR", "").strip()
_last_checks: dict[str, dict[str, Any]] = {}


def _host_for(value: str) -> str:
    parsed = urlparse(value if "://" in value else "https://" + value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(400, "Mirror must be an HTTPS URL without credentials")
    if parsed.port not in (None, 443):
        raise HTTPException(400, "Custom mirror ports are not allowed")
    host = parsed.hostname.lower().rstrip(".")
    if not any(host == allowed or host.endswith("." + allowed) for allowed in _ALLOWED_HOSTS):
        raise HTTPException(400, "Mirror host is not in HDREZKA_ALLOWED_HOSTS")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise HTTPException(400, "Mirror must be a domain root, without path/query/fragment")
    return host


def _normalise_mirror(value: str) -> str:
    host = _host_for(value)
    return f"https://{host}"


def _initialise_mirrors() -> None:
    global _active_mirror
    candidates = _configured + [f"https://{host}" for host in sorted(_ALLOWED_HOSTS)]
    seen: set[str] = set()
    for candidate in candidates:
        try:
            mirror = _normalise_mirror(candidate)
        except HTTPException:
            continue
        if mirror not in seen:
            seen.add(mirror)
            _mirrors.append(mirror)
    if _active_mirror:
        try:
            _active_mirror = _normalise_mirror(_active_mirror)
        except HTTPException:
            _active_mirror = ""
    if _active_mirror not in _mirrors:
        _active_mirror = _mirrors[0] if _mirrors else ""


_initialise_mirrors()


class MirrorInput(BaseModel):
    url: str = Field(min_length=4, max_length=300)


def validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(400, "url must be an https URL")
    host = parsed.hostname.lower().rstrip(".")
    if not any(host == allowed or host.endswith("." + allowed) for allowed in _ALLOWED_HOSTS):
        raise HTTPException(400, "URL host is not in HDREZKA_ALLOWED_HOSTS")
    return value


def _mirror_status(mirror: str) -> dict[str, Any]:
    request = Request(mirror, headers={"User-Agent": "HDRezka-Mirror-Checker/1.0", "Range": "bytes=0-0"})
    try:
        with urlopen(request, timeout=_TIMEOUT) as response:
            status = int(response.status)
        return {"url": mirror, "available": status < 500, "http_status": status, "error": None}
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code is not None:
            return {"url": mirror, "available": int(code) < 500, "http_status": int(code), "error": None if int(code) < 500 else f"HTTP {code}"}
        return {"url": mirror, "available": False, "http_status": None, "error": str(exc)[:180]}


def _check_all() -> list[dict[str, Any]]:
    with _LOCK:
        mirrors = list(_mirrors)
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(12, max(1, len(mirrors)))) as pool:
        futures = {pool.submit(_mirror_status, mirror): mirror for mirror in mirrors}
        for future in as_completed(futures):
            mirror = futures[future]
            try:
                results[mirror] = future.result()
            except Exception as exc:
                results[mirror] = {"url": mirror, "available": False, "http_status": None, "error": str(exc)[:180]}
    with _LOCK:
        _last_checks.update(results)
    return [results[mirror] for mirror in mirrors]


def _rewrite_to_active(value: str) -> str:
    target = validate_url(value)
    parsed = urlparse(target)
    with _LOCK:
        active = _active_mirror
    if not active:
        return target
    active_parsed = urlparse(active)
    return urlunparse((active_parsed.scheme, active_parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def library():
    try:
        from HDrezka import HDrezka  # type: ignore
        return HDrezka()
    except Exception as exc:
        raise HTTPException(503, f"hdrezka-api could not be initialized: {exc}") from exc


def call_method(obj: Any, names: tuple[str, ...], *args: Any, **kwargs: Any) -> Any:
    for name in names:
        method = getattr(obj, name, None)
        if callable(method):
            try:
                return method(*args, **kwargs)
            except TypeError:
                continue
    raise HTTPException(501, f"Installed library does not expose a compatible method: {', '.join(names)}")


def safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): safe_value(v) for k, v in value.items()}
    result = {}
    for attr in ("title", "name", "url", "poster", "image", "year", "type", "description"):
        found = getattr(value, attr, None)
        if isinstance(found, (str, int, float, bool)):
            result[attr] = found
    return result or str(value)


def item_to_dict(item: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("title", "name", "url", "poster", "image", "year", "type", "description", "id"):
        value = getattr(item, key, None)
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
    if not result:
        result["display"] = str(item)
    return result


@app.get("/health")
def health():
    try:
        import HDrezka  # noqa: F401
        installed = True
    except Exception:
        installed = False
    with _LOCK:
        active = _active_mirror
        count = len(_mirrors)
    return {"ok": True, "library_installed": installed, "active_mirror": active, "mirror_count": count}


@app.get("/mirrors")
def get_mirrors():
    with _LOCK:
        mirrors = list(_mirrors)
        active = _active_mirror
        checks = dict(_last_checks)
    return {"active": active, "count": len(mirrors), "mirrors": [
        {"url": url, "active": url == active, **checks.get(url, {"available": None, "http_status": None, "error": None})}
        for url in mirrors
    ]}


@app.post("/mirrors/check")
def check_mirrors():
    checked = _check_all()
    with _LOCK:
        active = _active_mirror
    return {"active": active, "count": len(checked), "mirrors": [
        {**item, "active": item["url"] == active} for item in checked
    ]}


@app.post("/mirrors/select")
def select_mirror(payload: MirrorInput):
    mirror = _normalise_mirror(payload.url)
    with _LOCK:
        if mirror not in _mirrors:
            raise HTTPException(404, "Mirror is not registered. Add it first via POST /mirrors/add.")
        global _active_mirror
        _active_mirror = mirror
    return {"ok": True, "active": mirror}


@app.post("/mirrors/add")
def add_mirror(payload: MirrorInput):
    mirror = _normalise_mirror(payload.url)
    with _LOCK:
        if mirror not in _mirrors:
            _mirrors.append(mirror)
    status = _mirror_status(mirror)
    with _LOCK:
        _last_checks[mirror] = status
    return {"ok": True, "added": True, "mirror": {**status, "active": mirror == _active_mirror}}


@app.get("/search")
def search(q: str = Query(min_length=1, max_length=200), limit: int = Query(default=10, ge=1, le=30)):
    client = library()
    results = call_method(client, ("search",), q)
    if hasattr(results, "get") and callable(results.get):
        try:
            results = results.get()
        except TypeError:
            pass
    if results is None:
        results = []
    if not isinstance(results, (list, tuple)):
        try:
            results = list(results)
        except TypeError:
            results = [results]
    return {"query": q, "count": min(len(results), limit), "items": [item_to_dict(x) for x in results[:limit]]}


@app.get("/item")
def item(url: str):
    target = _rewrite_to_active(url)
    client = library()
    try:
        result = call_method(client, ("get",), url=target)
    except HTTPException as first_error:
        try:
            result = call_method(client, ("get",), target)
        except HTTPException:
            raise first_error
    return {"item": item_to_dict(result), "details": safe_value(result), "requested_url": url, "resolved_url": target}


@app.get("/translations")
def translations(url: str):
    target = _rewrite_to_active(url)
    client = library()
    try:
        media = call_method(client, ("get",), url=target)
    except HTTPException as first_error:
        try:
            media = call_method(client, ("get",), target)
        except HTTPException:
            raise first_error
    player = getattr(media, "player", None)
    if player is None:
        return {"url": target, "translations": [], "supported": False, "note": "Translator metadata is not exposed by the installed library version."}
    options = getattr(player, "translators_dict", None)
    if callable(options):
        options = options()
    return {"url": target, "translations": safe_value(options) if options is not None else [], "supported": options is not None}


@app.get("/streams")
def streams(url: str, quality: str | None = None, translator: str | None = None):
    target = _rewrite_to_active(url)
    client = library()
    try:
        media = call_method(client, ("get",), url=target)
    except HTTPException as first_error:
        try:
            media = call_method(client, ("get",), target)
        except HTTPException:
            raise first_error
    player = getattr(media, "player", None)
    if player is None:
        raise HTTPException(501, "This library version does not expose a player object for the requested item.")
    if translator:
        setter = getattr(player, "set_translate", None)
        if callable(setter):
            try:
                setter(translator)
            except Exception as exc:
                raise HTTPException(400, f"Could not select translator: {exc}") from exc
    loader = getattr(player, "load_video", None)
    if callable(loader):
        kwargs = {"quality": quality} if quality else {}
        try:
            loaded = loader(**kwargs)
        except TypeError:
            loaded = loader()
        except Exception as exc:
            raise HTTPException(502, f"Upstream video loading failed: {exc}") from exc
        if loaded is not None:
            return {"url": target, "quality": quality, "translator": translator, "streams": safe_value(loaded)}
    getter = getattr(player, "get_video_url", None)
    if callable(getter):
        try:
            stream_url = getter(quality=quality) if quality else getter()
        except Exception as exc:
            raise HTTPException(502, f"Could not obtain video URL: {exc}") from exc
        return {"url": target, "quality": quality, "translator": translator, "streams": safe_value(stream_url)}
    raise HTTPException(501, "The installed library version does not expose a recognized stream-loading method.")
