"""Find the "다음에 변경" (remind me later) action on dhlottery's password-change notice page.

The page could not be inspected ahead of time (it only appears when the site decides to show it),
so the action is read from the page itself: a link, a form submit, or an AJAX call in the button's
click handler. Anything ambiguous returns None and the run stops with a clear alert instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from urllib.parse import urlsplit

DEFER_TEXT = "다음에"
STATIC = re.compile(r"\.(?:js|css|png|jpe?g|gif|svg|ico|woff2?)(?:\?|$)", re.IGNORECASE)
PATH = re.compile(r"""["'](/[A-Za-z0-9_./-]+)["']""")


@dataclass(frozen=True)
class DeferAction:
    method: str
    path: str
    kind: str  # link | form | ajax
    data: dict = field(default_factory=dict)


def _attrs(tag: str) -> dict:
    return {k.lower(): v for k, v in re.findall(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""", tag)}


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _scripts(html: str) -> str:
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL))


def _site_path(value: str) -> str | None:
    value = value.strip()
    if not value or value.startswith(("#", "javascript:")):
        return None
    parts = urlsplit(value)
    if parts.scheme and (parts.scheme != "https" or not parts.netloc.endswith("dhlottery.co.kr")):
        return None
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    return None if not path.startswith("/") or STATIC.search(path) else path


def _forms(html: str) -> dict:
    forms = {}
    for tag, body in re.findall(r"(<form\b[^>]*>)(.*?)</form>", html, flags=re.IGNORECASE | re.DOTALL):
        attrs = _attrs(tag)
        inputs = {a.get("name"): a.get("value", "") for a in map(_attrs, re.findall(r"<input\b[^>]*>", body, flags=re.IGNORECASE)) if a.get("name")}
        forms[attrs.get("id") or attrs.get("name") or f"form{len(forms)}"] = {
            "action": attrs.get("action", ""), "method": attrs.get("method", "post").upper(), "inputs": inputs}
    return forms


def page_structure(html: str) -> dict:
    """Names and paths only, never input values: safe for public logs."""
    forms = _forms(html)
    buttons = [_text(b)[:20] for _, b in re.findall(r"<(button|a)\b[^>]*>(.*?)</\1>", html, flags=re.IGNORECASE | re.DOTALL) if "변경" in _text(b)]
    return {
        "forms": [{"id": k, "action": _site_path(f["action"]) or "", "inputs": sorted(f["inputs"])} for k, f in forms.items()],
        "buttons": buttons[:6],
        "script_paths": sorted({p.split("?")[0] for p in PATH.findall(_scripts(html)) if _site_path(p)})[:12],
    }


def _handler_body(scripts: str, attrs: dict) -> str:
    onclick = attrs.get("onclick", "")
    name = re.match(r"\s*(?:javascript:)?\s*([A-Za-z_$][\w$.]*)\s*\(", onclick)
    if name:
        start = re.search(r"function\s+" + re.escape(name.group(1).split(".")[-1]) + r"\s*\(", scripts)
        if not start:
            start = re.search(re.escape(name.group(1).split(".")[-1]) + r"\s*[:=]\s*function\s*\(", scripts)
        if start:
            return scripts[start.end():start.end() + 1500]
        return onclick
    if attrs.get("id"):
        start = re.search(r"""["']#""" + re.escape(attrs["id"]) + r"""["']\s*\)\s*\.\s*(?:click|on)\s*\(""", scripts)
        if start:
            return scripts[start.end():start.end() + 1500]
    return ""


def find_defer_action(html: str) -> DeferAction | None:
    candidates = [(tag, body) for tag, _, body in re.findall(r"(<(button|a)\b[^>]*>)(.*?)</\2>", html, flags=re.IGNORECASE | re.DOTALL)
                  if DEFER_TEXT in _text(body)]
    if len(candidates) != 1:
        return None  # Missing or ambiguous: never guess between buttons.
    attrs = _attrs(candidates[0][0])
    href = _site_path(attrs.get("href", ""))
    if href:
        return DeferAction("GET", href, "link")
    body = _handler_body(_scripts(html), attrs)
    if not body:
        return None
    forms = _forms(html)
    if re.search(r"\.submit\s*\(", body):
        form_id = re.search(r"""(?:\$\(\s*["']#|getElementById\(\s*["'])([\w-]+)""", body)
        form = forms.get(form_id.group(1)) if form_id else None
        action = re.search(r"""attr\(\s*["']action["']\s*,\s*["']([^"']+)["']""", body)
        path = _site_path(action.group(1) if action else (form or {}).get("action", ""))
        if not form or not path:
            return None
        return DeferAction("POST" if form["method"] != "GET" else "GET", path, "form", form["inputs"])
    paths = [p for p in PATH.findall(body) if _site_path(p)]
    if not paths:
        return None
    if re.search(r"location\.(?:href|replace)", body) and not re.search(r"ajax|sendHttp", body):
        return DeferAction("GET", paths[0], "link")
    method = "POST" if re.search(r"""["']?(?:method|type)["']?\s*:\s*["']POST["']""", body, re.IGNORECASE) else "GET"
    return DeferAction(method, paths[0], "ajax")
