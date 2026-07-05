from typing import Any

import folium
from streamlit_folium import st_folium


def build_folium_map(
    center: tuple[float, float],
    zoom: int,
    pins: list[dict[str, Any]],
    *,
    active_lat: float | None = None,
    active_lon: float | None = None,
    active_radius_m: float | None = None,
    location_source: str | None = None,
) -> folium.Map:
    folium_map = folium.Map(location=list(center), zoom_start=zoom, tiles="OpenStreetMap")

    for pin in pins:
        radius = float(pin.get("radius_m", 500))
        folium.Circle(
            location=[pin["lat"], pin["lon"]],
            radius=radius,
            color="#3388ff",
            fill=True,
            fill_opacity=0.15,
            popup=f"{pin['name']} ({radius:.0f} m)",
        ).add_to(folium_map)
        folium.Marker(
            location=[pin["lat"], pin["lon"]],
            popup=pin["name"],
            tooltip=pin["name"],
            icon=folium.Icon(color="blue", icon="home", prefix="fa"),
        ).add_to(folium_map)

    if active_lat is not None and active_lon is not None:
        if active_radius_m:
            folium.Circle(
                location=[active_lat, active_lon],
                radius=float(active_radius_m),
                color="#e74c3c",
                fill=True,
                fill_opacity=0.12,
            ).add_to(folium_map)

        icon_color = "cadetblue" if location_source == "gps" else "red"
        folium.Marker(
            location=[active_lat, active_lon],
            popup="Active location",
            tooltip="Active location",
            icon=folium.Icon(color=icon_color, icon="map-pin", prefix="fa"),
        ).add_to(folium_map)

    return folium_map


def render_interactive_map(
    center: tuple[float, float],
    zoom: int,
    pins: list[dict[str, Any]],
    *,
    active_lat: float | None = None,
    active_lon: float | None = None,
    active_radius_m: float | None = None,
    location_source: str | None = None,
    height: int = 450,
) -> dict[str, Any] | None:
    folium_map = build_folium_map(
        center,
        zoom,
        pins,
        active_lat=active_lat,
        active_lon=active_lon,
        active_radius_m=active_radius_m,
        location_source=location_source,
    )
    return st_folium(
        folium_map,
        center=list(center),
        zoom=zoom,
        key="agro_map",
        width=None,
        height=height,
        returned_objects=["last_clicked"],
    )
