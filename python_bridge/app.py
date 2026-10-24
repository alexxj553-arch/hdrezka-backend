"""Local adapter around the community hdrezka-api package.

This integration intentionally uses feature detection: third-party API names can
change between versions. It does not attempt to bypass DRM or access controls.
"""
from __future__ import annotations

import inspect
import os
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="HDRezka Python Bridge", version="0.1.0")
_ALLOWED_HOSTS = {
    host.strip().lower()
    for host in os.getenv("HDREZKA_ALLOWED_HOSTS", "rezka.ag,hdrezka.ag").split(",")
    if host.strip()
}


def validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(400, "url must be an https URL")
    host = parsed.hostname.lower()
    if not any(host == allowed or host.endswith("." + allowed) for allowed in _ALLOWED_HOSTS):
        raise HTTPException(400, "URL host is not in HDREZKA_ALLOWED_HOSTS")
    return value


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
    for attr in ("title", "name", "url", "poster", "image", "year", "type", "description"):
        found = getattr(value, attr, None)
        if isinstance(found, (str, int, float, bool)):
            return {attr: found}
    return str(value)


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
    return {"ok": True, "library_installed": installed}


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
    target = validate_url(url)
    client = library()
    # The documented library supports get(url=...), while some versions use positional URL.
    try:
        result = call_method(client, ("get",), url=target)
    except HTTPException as first_error:
        try:
            result = call_method(client, ("get",), target)
        except HTTPException:
            raise first_error
    return {"item": item_to_dict(result), "details": safe_value(result)}


@app.get("/translations")
def translations(url: str):
    target = validate_url(url)
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
    target = validate_url(url)
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
        kwargs = {}
        if quality:
            kwargs["quality"] = quality
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
