# app_ui.py
import pandas as pd
import streamlit as st
from streamlit_geolocation import streamlit_geolocation

from agro_agent.config import get_settings
from agro_agent.crop_rules import get_crop_list
from agro_agent import farms
from agro_agent.geocode import reverse_geocode
from agro_agent.geo_utils import validate_coordinates
from agro_agent.regions import (
    ONE_TIME_GPS_REGION_ID,
    format_region_label,
    get_map_pins,
    get_region,
    get_select_options,
    region_id_for_label,
    region_mode_for_label,
    find_nearest_region,
)
from agro_agent.runner import run_agro_workflow

st.set_page_config(page_title="AgroCloud Intelligence", layout="wide")

get_settings.cache_clear()
settings = get_settings()

if "selected_region_label" not in st.session_state:
    select_options = get_select_options()
    st.session_state.selected_region_label = select_options[0]["label"]

st.title("Agents For Good: Agro-Climate Intelligence System")
st.markdown("### Production-Grade Multi-Agent Decision Framework")

st.sidebar.header("Agent Configuration")
st.sidebar.success("Antigravity ADK 2.0 Active")
if settings.has_api_key():
    st.sidebar.success(f"Gemini configured ({settings.agro_model})")
else:
    st.sidebar.error("GOOGLE_API_KEY missing — add to .env")
st.sidebar.info("MCP: stdio subprocess via ADK McpToolset")
st.sidebar.info("Security Mode: Strict guardrail + Pydantic validation")
st.sidebar.caption("Custom farms use live Open-Meteo weather.")

map_col, control_col = st.columns([3, 2])

with map_col:
    st.subheader("Farm & Zone Map")
    pins = get_map_pins()
    selected_region_id = region_id_for_label(st.session_state.selected_region_label)
    map_rows = []
    for pin in pins:
        is_selected = pin["region_id"] == selected_region_id
        map_rows.append(
            {
                "lat": pin["lat"],
                "lon": pin["lon"],
                "name": pin["name"],
                "selected": is_selected,
            }
        )
    if map_rows:
        st.map(pd.DataFrame(map_rows), latitude="lat", longitude="lon", size=80)
        selected_pin = next((p for p in pins if p["region_id"] == selected_region_id), None)
        if selected_pin and selected_pin.get("kind") == "custom":
            radius = selected_pin.get("radius_m", 0)
            hectares = 3.14159 * (radius / 100) ** 2 / 100
            st.caption(
                f"**{selected_pin['name']}** — field radius {radius:.0f} m "
                f"(~{hectares:.2f} ha)"
            )
        elif selected_pin:
            st.caption(f"**{selected_pin['name']}** — Nepal registry zone")
    else:
        st.info("No zones or farms to display yet.")

with control_col:
    st.subheader("Query Control Panel")
    st.caption(
        "Use device GPS to suggest the nearest Nepal zone or save a custom farm anywhere. "
        "Location works on localhost or HTTPS."
    )

    location = streamlit_geolocation()
    gps_lat: float | None = None
    gps_lon: float | None = None

    if isinstance(location, dict) and location.get("latitude") is not None:
        gps_lat = float(location["latitude"])
        gps_lon = float(location["longitude"])
        geo_key = (round(gps_lat, 5), round(gps_lon, 5))
        st.session_state.gps_lat = gps_lat
        st.session_state.gps_lon = gps_lon
        if st.session_state.get("last_geo_key") != geo_key:
            st.session_state.last_geo_key = geo_key
            region_id, display_name, distance_km = find_nearest_region(gps_lat, gps_lon)
            st.session_state.suggested_region_id = region_id
            st.session_state.suggested_distance_km = distance_km
            st.session_state.selected_region_label = format_region_label(region_id)
        suggested_id = st.session_state.get("suggested_region_id")
        if suggested_id:
            suggested_meta = get_region(suggested_id)
            display_name = (
                suggested_meta["display_name"] if suggested_meta else suggested_id
            )
            distance_km = st.session_state.get("suggested_distance_km", 0.0)
            st.info(
                f"Nearest Nepal zone: **{display_name}** (~{distance_km:.1f} km). "
                "Confirm in the dropdown or save as a custom farm."
            )
    elif isinstance(location, dict) and location.get("error"):
        st.warning(
            "Location permission denied or unavailable. Select a region or enter coordinates."
        )

    with st.expander("Save custom farm", expanded=False):
        farm_name = st.text_input("Farm name", placeholder="My Wheat Field")
        farm_crop = st.selectbox("Crop", get_crop_list(), key="save_farm_crop")
        farm_radius = st.number_input(
            "Field radius (meters)", min_value=50, max_value=5000, value=500, step=50
        )
        use_gps_for_save = st.checkbox(
            "Use current GPS for location",
            value=gps_lat is not None,
            disabled=gps_lat is None,
        )
        manual_lat = st.number_input(
            "Latitude",
            value=gps_lat if gps_lat is not None else 27.7,
            format="%.5f",
            disabled=use_gps_for_save and gps_lat is not None,
        )
        manual_lon = st.number_input(
            "Longitude",
            value=gps_lon if gps_lon is not None else 85.3,
            format="%.5f",
            disabled=use_gps_for_save and gps_lon is not None,
        )

        if st.button("Save farm", type="secondary"):
            save_lat = gps_lat if use_gps_for_save and gps_lat is not None else manual_lat
            save_lon = gps_lon if use_gps_for_save and gps_lon is not None else manual_lon
            ok, reason = validate_coordinates(save_lat, save_lon)
            if not farm_name.strip():
                st.error("Farm name is required.")
            elif not ok:
                st.error(reason)
            else:
                geo = reverse_geocode(save_lat, save_lon)
                farm = farms.create_farm(
                    name=farm_name.strip(),
                    crop=farm_crop,
                    latitude=save_lat,
                    longitude=save_lon,
                    radius_m=float(farm_radius),
                    place_name=geo["place_name"],
                    country=geo["country"],
                )
                st.session_state.selected_region_label = farms.format_farm_label(farm)
                st.success(
                    f"Saved **{farm['name']}** at {geo['place_name']}, {geo['country']}."
                )
                st.rerun()

        saved = farms.list_farms()
        if saved:
            st.markdown("**Saved farms**")
            for farm in saved:
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.caption(
                        f"{farms.format_farm_label(farm)} · {farm['crop']} · "
                        f"{farm['radius_m']:.0f} m"
                    )
                with col_b:
                    if st.button("Delete", key=f"del_{farm['region_id']}"):
                        farms.delete_farm(farm["region_id"])
                        st.rerun()

    select_options = get_select_options()
    region_labels = [option["label"] for option in select_options]
    try:
        default_index = region_labels.index(st.session_state.selected_region_label)
    except ValueError:
        default_index = 0

    selected_label = st.selectbox(
        "Select Target Region",
        region_labels,
        index=default_index,
    )
    st.session_state.selected_region_label = selected_label

    region_id = region_id_for_label(selected_label)
    mode = region_mode_for_label(selected_label)
    region_meta = get_region(region_id)

    workflow_lat: float | None = None
    workflow_lon: float | None = None
    workflow_crop: str | None = None
    workflow_radius: float | None = None
    workflow_place: str | None = None
    workflow_country: str | None = None
    workflow_mode: str | None = None
    workflow_name: str | None = None
    workflow_district: str | None = None

    if mode == "one_time":
        workflow_lat = st.session_state.get("gps_lat")
        workflow_lon = st.session_state.get("gps_lon")
        if workflow_lat is None or workflow_lon is None:
            st.warning("Enable GPS or pick a saved farm / Nepal zone.")
        else:
            workflow_crop = st.selectbox("Crop for this location", get_crop_list())
            geo = reverse_geocode(workflow_lat, workflow_lon)
            workflow_place = geo["place_name"]
            workflow_country = geo["country"]
            workflow_name = f"GPS ({workflow_place})"
            workflow_district = workflow_country
            workflow_mode = "custom"
            st.caption(
                f"One-time location: **{workflow_place}**, {workflow_country} "
                f"({workflow_lat:.4f}, {workflow_lon:.4f})"
            )
    elif mode == "custom" and region_meta:
        workflow_lat = region_meta.get("latitude")
        workflow_lon = region_meta.get("longitude")
        workflow_crop = region_meta.get("crop")
        workflow_radius = region_meta.get("radius_m")
        workflow_place = region_meta.get("place_name")
        workflow_country = region_meta.get("country")
        workflow_name = region_meta.get("display_name")
        workflow_district = region_meta.get("district")
        workflow_mode = "custom"
        st.caption(
            f"Custom farm `{region_id}` · Crop: **{workflow_crop}** · "
            f"{workflow_place or workflow_country}"
        )
    elif region_meta:
        workflow_mode = "registry"
        workflow_name = region_meta["display_name"]
        workflow_district = region_meta["district"]
        workflow_crop = region_meta.get("crop")
        st.caption(
            f"Nepal zone `{region_id}` · Crop: **{region_meta['crop']}** · "
            f"District: **{region_meta['district']}**"
        )

    user_prompt = st.text_area(
        "Custom Strategy Request",
        "Generate a sustainable optimization plan for this sector.",
    )
    run_btn = st.button("Trigger Agent Network", type="primary")

st.subheader("Agent System Logs & Outputs")

if run_btn:
    if mode == "one_time" and (workflow_lat is None or workflow_lon is None):
        st.error("GPS location required for one-time mode. Enable location permission.")
    else:
        with st.status("Running ADK workflow...", expanded=True):
            result = run_agro_workflow(
                user_prompt,
                region_id if mode != "one_time" else ONE_TIME_GPS_REGION_ID,
                region_name=workflow_name,
                region_district=workflow_district,
                region_mode=workflow_mode,
                latitude=workflow_lat,
                longitude=workflow_lon,
                crop=workflow_crop,
                radius_m=workflow_radius,
                place_name=workflow_place,
                country=workflow_country,
            )

        st.session_state.last_result = result
        st.session_state.last_region_meta = region_meta or {
            "display_name": workflow_name or region_id,
            "district": workflow_district or "",
            "crop": workflow_crop,
            "latitude": workflow_lat,
            "longitude": workflow_lon,
            "place_name": workflow_place,
            "country": workflow_country,
        }

if st.session_state.get("last_result"):
    result = st.session_state.last_result
    region_meta = st.session_state.get("last_region_meta")
    pipeline = result.get("pipeline", {})
    guardrail_state = pipeline.get("guardrail", "unknown")

    if result["status"] == "blocked":
        status_label = "Security Guardrail: BLOCKED"
        status_state = "error"
    elif result["status"] == "error":
        status_label = "Workflow error"
        status_state = "error"
    else:
        status_label = "Pipeline complete"
        status_state = "complete"

    with st.status(status_label, expanded=True, state=status_state):
        if result["status"] == "blocked":
            st.error(result.get("message", "Input blocked by guardrail."))
        elif result["status"] == "error":
            st.error(result.get("message", "Workflow failed."))
            if pipeline.get("guardrail") == "cleared":
                st.warning(
                    "Guardrail and MCP setup succeeded; the failure was in the "
                    "Gemini coordinator step."
                )
        else:
            if region_meta:
                location_bits = [region_meta.get("display_name", "")]
                if region_meta.get("district"):
                    location_bits.append(f"({region_meta['district']})")
                if region_meta.get("place_name"):
                    location_bits.append(f"— {region_meta['place_name']}")
                st.write(f"**Zone:** {' '.join(b for b in location_bits if b)}")
                if region_meta.get("latitude") and region_meta.get("longitude"):
                    st.caption(
                        f"Coordinates: {region_meta['latitude']:.4f}, "
                        f"{region_meta['longitude']:.4f}"
                    )
            st.write(f"1. Guardrail: **{guardrail_state}**")
            st.write(f"2. MCP tool: **{pipeline.get('mcp', 'unknown')}**")
            st.write(f"3. Coordinator: **{pipeline.get('coordinator', 'unknown')}**")

            st.metric(
                label="Irrigation Urgency Level",
                value=result.get("irrigation_urgency", "UNKNOWN"),
            )

            if result.get("data"):
                st.subheader("MCP Metrics")
                st.json(result["data"])

            if result.get("actions"):
                st.subheader("Recommended Actions")
                for action in result["actions"]:
                    st.markdown(f"- {action}")

            if result.get("risks"):
                st.subheader("Risks")
                for risk in result["risks"]:
                    st.markdown(f"- {risk}")

            if result.get("reasoning"):
                st.info(f"**Coordinator Agent Reasoning:** {result['reasoning']}")
