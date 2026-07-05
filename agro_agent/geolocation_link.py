import os

import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(__file__), "components", "geolocation_link")
_geolocation_link = components.declare_component("geolocation_link", path=_COMPONENT_DIR)


def geolocation_link(label: str = "Use current location", *, key: str | None = None) -> dict | None:
    """Clickable text link that requests browser GPS and returns {latitude, longitude} or {error}."""
    result = _geolocation_link(label=label, default=None, key=key)
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    return None
