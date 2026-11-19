"""Read the public France Student status page.

The status page (https://status.francestudent.org/) is served by Better
Stack and rendered on the server, so the service states can be read from
the HTML without any private API.
"""

import html
import logging
import re
import urllib.request


logger = logging.getLogger("france_student_bridge.status")

STATUS_URL = "https://status.francestudent.org/"

# The state of a service is carried by the aria-label of its status icon.
_STATE_RE = re.compile(r'aria-label="([^"]+)"')
# A service row ends with the service name in a truncating div.
_NAME_RE = re.compile(r"class='[^']*truncate[^']*'>\s*([^<]+?)\s*</div>")
# A section header carries the group name in a span.
_SECTION_RE = re.compile(r"<span class='truncate'>([^<]+)</span>")
_UPDATED_RE = re.compile(r"Dernière mise à jour[^<]*?([0-9]{1,2}\s+\w+\s+[0-9]{4}[^<]*?UTC)")

# The states Better Stack uses, in French.
_KNOWN_STATES = {
    "opérationnel",
    "temps d'arrêt",
    "temps d'arrêt partiel",
    "maintenance en cours",
    "maintenance planifiée",
    "performance dégradée",
    "aucun incident",
    "opérationnel dégradé",
}


def _normalise(value):
    text = html.unescape(value or "").strip().lower()
    return text.replace("’", "'").replace("&#39;", "'")


def parse_status(markup):
    """Extract the service list and their states from the status page."""
    services = []
    updated = None
    match = _UPDATED_RE.search(markup)
    if match:
        updated = html.unescape(match.group(1)).strip()

    for state_match in _STATE_RE.finditer(markup):
        state = html.unescape(state_match.group(1)).strip()
        if _normalise(state) not in _KNOWN_STATES:
            continue
        window = markup[max(0, state_match.start() - 1200):state_match.start()]
        names = list(_NAME_RE.finditer(window))
        sections = list(_SECTION_RE.finditer(window))
        if sections and (not names or sections[-1].start() > names[-1].start()):
            name = html.unescape(sections[-1].group(1)).strip()
            kind = "section"
        elif names:
            name = html.unescape(names[-1].group(1)).strip()
            kind = "service"
        else:
            continue
        services.append({"name": name, "status": state, "kind": kind})

    overall = "unknown"
    offre_ia = None
    for entry in services:
        if entry["kind"] != "section":
            continue
        if overall == "unknown":
            overall = entry["status"]
        if _normalise(entry["name"]).startswith("offre ia"):
            offre_ia = entry["status"]
            break

    degraded = [
        entry for entry in services
        if entry["kind"] == "service"
        and _normalise(entry["status"]) != "opérationnel"
    ]
    return {
        "url": STATUS_URL,
        "updated": updated,
        "overall": overall,
        "offre_ia": offre_ia,
        "services": services,
        "degraded": degraded,
        "healthy": not degraded,
    }


def fetch_status(timeout=20):
    """Fetch and parse the status page. Never raises."""
    request = urllib.request.Request(
        STATUS_URL,
        headers={"User-Agent": "france-student-bridge/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            markup = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("status_fetch_failed error=%s", type(exc).__name__)
        return {
            "url": STATUS_URL,
            "updated": None,
            "overall": "unknown",
            "services": [],
            "degraded": [],
            "healthy": None,
            "error": type(exc).__name__,
        }
    return parse_status(markup)
