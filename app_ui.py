# app_ui.py
import streamlit as st

from agro_agent.config import get_settings
from agro_agent.crop_rules import crop_profile_hint, normalize_crop
from agro_agent import farms
from agro_agent import plan_history
from agro_agent.geocode import forward_geocode, reverse_geocode
from agro_agent.geolocation_link import geolocation_link
from agro_agent.geo_utils import validate_coordinates
from agro_agent.map_ui import render_interactive_map
from agro_agent.report import (
    SOIL_MOISTURE_DISCLAIMER,
    build_plan_markdown,
    build_plan_pdf,
    error_stage_heading,
    fmt_num,
    forecast_arrays,
    format_result_location,
    irrigation_hint_line,
    plan_source_label,
    soil_moisture_disclaimer_lines,
    urgency_badge_html,
    urgency_caption,
)
from agro_agent.runner import ensure_plan_content
from agro_agent.regions import (
    ONE_TIME_GPS_REGION_ID,
    get_map_pins,
    get_region,
    resolve_map_click,
)
from agro_agent.runner import run_agro_workflow

DEFAULT_CENTER = (27.7172, 85.3240)  # Kathmandu
DEFAULT_ZOOM = 11
MAP_HEIGHT = 360


def _init_session_state() -> None:
    defaults = {
        "active_lat": DEFAULT_CENTER[0],
        "active_lon": DEFAULT_CENTER[1],
        "active_crop": "Maize",
        "active_radius_m": 500.0,
        "loaded_farm_id": None,
        "place_name": "Kathmandu",
        "country": "Nepal",
        "active_name": "Kathmandu",
        "map_center": list(DEFAULT_CENTER),
        "map_zoom": DEFAULT_ZOOM,
        "location_source": "default",
        "last_map_click_key": None,
        "last_manual_lat": None,
        "last_manual_lon": None,
        "last_geo_key": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if (
        st.session_state.location_source == "default"
        and abs(st.session_state.active_lat - 20.0) < 0.01
        and abs(st.session_state.active_lon - 0.0) < 0.01
    ):
        st.session_state.active_lat = DEFAULT_CENTER[0]
        st.session_state.active_lon = DEFAULT_CENTER[1]
        st.session_state.map_center = list(DEFAULT_CENTER)
        st.session_state.map_zoom = DEFAULT_ZOOM
        st.session_state.place_name = "Kathmandu"
        st.session_state.country = "Nepal"
        st.session_state.active_name = "Kathmandu"
        st.session_state.last_manual_lat = DEFAULT_CENTER[0]
        st.session_state.last_manual_lon = DEFAULT_CENTER[1]


def _sync_coord_widgets(lat: float, lon: float) -> None:
    st.session_state.last_manual_lat = float(lat)
    st.session_state.last_manual_lon = float(lon)


def _set_map_view(lat: float, lon: float, zoom: int | None = None) -> None:
    st.session_state.map_center = [lat, lon]
    if zoom is not None:
        st.session_state.map_zoom = zoom


def _apply_custom_location(
    lat: float,
    lon: float,
    *,
    source: str,
    crop: str | None = None,
    radius_m: float | None = None,
    place_name: str | None = None,
    country: str | None = None,
    name: str | None = None,
    zoom: int | None = None,
    pan_map: bool = True,
) -> None:
    st.session_state.active_lat = lat
    st.session_state.active_lon = lon
    st.session_state.loaded_farm_id = None
    st.session_state.location_source = source
    if crop is not None:
        st.session_state.active_crop = normalize_crop(crop)
    if radius_m is not None:
        st.session_state.active_radius_m = float(radius_m)
    if place_name is not None:
        st.session_state.place_name = place_name
    if country is not None:
        st.session_state.country = country
    if name is not None:
        st.session_state.active_name = name
    _sync_coord_widgets(lat, lon)
    if pan_map:
        _set_map_view(lat, lon, zoom=zoom)


def _apply_farm(farm: dict, *, source: str = "farm", pan_map: bool = True) -> None:
    _apply_custom_location(
        farm["latitude"],
        farm["longitude"],
        source=source,
        crop=farm["crop"],
        radius_m=farm["radius_m"],
        place_name=farm.get("place_name", ""),
        country=farm.get("country", ""),
        name=farm["name"],
        zoom=13 if pan_map else None,
        pan_map=pan_map,
    )
    st.session_state.loaded_farm_id = farm["region_id"]


def _apply_map_click(lat: float, lon: float) -> None:
    resolved = resolve_map_click(lat, lon)

    if resolved.get("farm_id"):
        farm = farms.get_farm(resolved["farm_id"])
        if farm:
            _apply_farm(farm, source="click", pan_map=False)
        return

    st.session_state.active_lat = lat
    st.session_state.active_lon = lon
    st.session_state.loaded_farm_id = None
    st.session_state.location_source = "click"
    st.session_state.active_name = f"{lat:.4f}, {lon:.4f}"
    _sync_coord_widgets(lat, lon)

    geo = reverse_geocode(lat, lon)
    st.session_state.place_name = geo["place_name"]
    st.session_state.country = geo["country"]
    st.session_state.active_name = geo["place_name"]


def _workflow_args_from_state() -> dict:
    if st.session_state.loaded_farm_id:
        region_id = st.session_state.loaded_farm_id
        region_meta = get_region(region_id)
        region_name = region_meta["display_name"] if region_meta else st.session_state.active_name
        region_district = region_meta.get("district", "") if region_meta else ""
    else:
        region_id = ONE_TIME_GPS_REGION_ID
        region_meta = None
        region_name = st.session_state.active_name
        region_district = st.session_state.place_name or st.session_state.country

    return {
        "region_id": region_id,
        "region_mode": "custom",
        "region_name": region_name,
        "region_district": region_district,
        "latitude": st.session_state.active_lat,
        "longitude": st.session_state.active_lon,
        "crop": st.session_state.active_crop,
        "radius_m": st.session_state.active_radius_m,
        "place_name": st.session_state.place_name,
        "country": st.session_state.country,
        "region_meta": region_meta,
    }


def _active_mode_label() -> str:
    if st.session_state.loaded_farm_id:
        return "Saved farm"
    return "Live Open-Meteo"


def _render_weather_summary(data: dict, urgency: str, radius_m: float | None) -> None:
    st.subheader("Current conditions")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Soil moisture", fmt_num(data.get("current_soil_moisture_pct"), "%"))
    c2.metric("Temperature", fmt_num(data.get("average_temp_celsius"), "°C"))
    c3.metric("Humidity", fmt_num(data.get("current_humidity_pct"), "%", decimals=0))
    c4.metric("Rain next 3 days", fmt_num(data.get("forecast_rain_mm_3d"), " mm"))

    crop = data.get("recommended_crop") or data.get("profile_used") or "—"
    profile = data.get("profile_used") or crop
    matched = data.get("profile_matched")
    if matched is True:
        profile_note = f"Crop: {crop} (profile matched: {profile})"
    elif matched is False:
        profile_note = f"Crop: {crop} (using {profile} defaults)"
    else:
        profile_note = f"Crop: {crop}"
    season = data.get("season_label")
    if season:
        profile_note += f" · Season: {season}"
    st.caption(profile_note)

    for note in soil_moisture_disclaimer_lines(data):
        st.caption(note)

    hint = irrigation_hint_line(data, urgency, radius_m)
    if hint:
        st.info(hint)


def _render_forecast_table(data: dict) -> None:
    rain, temps = forecast_arrays(data)
    if not rain and not temps:
        return

    st.subheader("3-day outlook")
    day_count = max(len(rain), len(temps))
    rows = []
    for i in range(day_count):
        rain_val = rain[i] if i < len(rain) else None
        temp_val = temps[i] if i < len(temps) else None
        rows.append(
            {
                "Day": f"Day {i + 1}",
                "Rain (mm)": fmt_num(rain_val),
                "Max temp (°C)": fmt_num(temp_val),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_pipeline_expander(pipeline: dict) -> None:
    guardrail = pipeline.get("guardrail", "unknown")
    mcp = pipeline.get("mcp", "unknown")
    coordinator = pipeline.get("coordinator", "unknown")

    guardrail_label = {
        "cleared": "Security check passed",
        "blocked": "Security check blocked",
    }.get(guardrail, f"Security check: {guardrail}")

    mcp_label = {
        "invoked": "Live weather loaded (Open-Meteo)",
        "no_metrics_seen": "Weather data not received",
        "failed": "Weather API failed",
    }.get(mcp, f"Weather step: {mcp}")

    coordinator_label = {
        "complete": "Irrigation plan generated",
        "failed": "Plan generation failed",
        "quota_exceeded": "Plan generation failed (API quota)",
    }.get(coordinator, f"Coordinator: {coordinator}")

    with st.expander("Technical pipeline", expanded=False):
        st.markdown(f"- {guardrail_label}")
        st.markdown(f"- {mcp_label}")
        st.markdown(f"- {coordinator_label}")


def _render_error_result(result: dict, pipeline: dict) -> None:
    stage = result.get("stage", "")
    heading = error_stage_heading(stage)
    st.error(f"**{heading}**")
    st.markdown(result.get("message", "An error occurred."))
    if pipeline.get("guardrail") == "cleared" and stage == "coordinator":
        st.warning(
            "Guardrail and weather setup succeeded; the failure was in the "
            "Gemini coordinator step."
        )


def _render_success_result(
    result: dict,
    wf: dict,
    region_meta: dict | None,
) -> None:
    result = ensure_plan_content(result, wf.get("crop", "Maize"))

    data = result.get("data") or {}
    if data.get("error"):
        st.warning(f"Weather data issue: {data['error']}")

    st.write(f"**Location:** {format_result_location(wf, region_meta)}")

    urgency = result.get("irrigation_urgency", "UNKNOWN")
    plan_source = result.get("plan_source", "unknown")
    st.markdown(
        f"**Irrigation urgency:** {urgency_badge_html(urgency)}",
        unsafe_allow_html=True,
    )
    st.caption(urgency_caption(urgency))
    st.write(plan_source_label(plan_source))

    reasoning = (result.get("reasoning") or "").strip()
    if reasoning:
        st.info(f"**Irrigation plan:** {reasoning}")

    st.subheader("Recommended actions")
    actions = result.get("actions") or []
    for action in actions:
        st.markdown(f"- {action}")

    risks = result.get("risks") or []
    if risks:
        st.subheader("Risks")
        for risk in risks:
            st.markdown(f"- {risk}")

    if data and not data.get("error"):
        _render_weather_summary(data, urgency, wf.get("radius_m"))
        _render_forecast_table(data)

    _render_pipeline_expander(result.get("pipeline", {}))

    md_report = build_plan_markdown(result, wf, region_meta)
    pdf_report = build_plan_pdf(result, wf, region_meta)
    export_col1, export_col2 = st.columns(2)
    with export_col1:
        st.download_button(
            "Download report (.md)",
            data=md_report,
            file_name="irrigation_report.md",
            mime="text/markdown",
        )
    with export_col2:
        st.download_button(
            "Download report (.pdf)",
            data=pdf_report,
            file_name="irrigation_report.pdf",
            mime="application/pdf",
        )

    with st.expander("Preview report", expanded=False):
        st.code(md_report, language="markdown")

    if data:
        with st.expander("Raw MCP data", expanded=False):
            st.json(data)


st.set_page_config(
    page_title="AgroCloud Intelligence",
    layout="wide",
    initial_sidebar_state="collapsed",
)

get_settings.cache_clear()
settings = get_settings()
_init_session_state()

st.title("Agents For Good: Agro-Climate Intelligence System")
st.markdown("### Production-Grade Multi-Agent Decision Framework")

st.sidebar.header("Agent Configuration")
st.sidebar.success("Antigravity ADK 2.0 Active")
if settings.has_api_key():
    st.sidebar.success(f"Gemini configured ({settings.agro_model})")
else:
    st.sidebar.error("GOOGLE_API_KEY missing — add to .env")
st.sidebar.info("MCP: stdio subprocess via ADK McpToolset")
st.sidebar.info("Live weather via Open-Meteo")
st.sidebar.caption(SOIL_MOISTURE_DISCLAIMER)
st.sidebar.caption("Click the map to pick a location anywhere in the world.")

st.subheader("Farm & Zone Map")
st.caption(
    "Click empty map area (not on pins) to set location — zoom stays unchanged. "
    "Blue circles = saved farms."
)

pins = get_map_pins()
map_data = render_interactive_map(
    tuple(st.session_state.map_center),
    int(st.session_state.map_zoom),
    pins,
    active_lat=st.session_state.active_lat,
    active_lon=st.session_state.active_lon,
    active_radius_m=st.session_state.active_radius_m,
    location_source=st.session_state.location_source,
    height=MAP_HEIGHT,
)

if map_data and map_data.get("last_clicked"):
    click = map_data["last_clicked"]
    click_lat = float(click["lat"])
    click_lon = float(click["lng"])
    click_key = (round(click_lat, 6), round(click_lon, 6))
    if click_key != st.session_state.last_map_click_key:
        st.session_state.last_map_click_key = click_key
        _apply_map_click(click_lat, click_lon)
        st.rerun()

if st.session_state.active_radius_m:
    hectares = 3.14159 * (st.session_state.active_radius_m / 100) ** 2 / 100
    st.caption(
        f"Active field radius: {st.session_state.active_radius_m:.0f} m (~{hectares:.2f} ha)"
    )

st.markdown(
    f"**Active location:** {st.session_state.active_name} · "
    f"{st.session_state.place_name}, {st.session_state.country} · "
    f"`{st.session_state.active_lat:.4f}, {st.session_state.active_lon:.4f}` · "
    f"{_active_mode_label()}"
)

control_col, farm_col = st.columns([3, 2])

with control_col:
    loc_title_col, loc_link_col = st.columns([1, 1.4], vertical_alignment="bottom")
    with loc_title_col:
        st.subheader("Location")
    with loc_link_col:
        st.markdown(
            """
            <style>
            iframe[title="geolocation_link.geolocation_link"] {
                border: none !important;
                background: transparent !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        location = geolocation_link("Use current location", key="geo_link")

    with st.form("place_search_form", clear_on_submit=False):
        input_col, go_col = st.columns([5, 1], vertical_alignment="bottom")
        with input_col:
            place_query = st.text_input(
                "Search place",
                placeholder="London, UK",
            )
        with go_col:
            search_submitted = st.form_submit_button(
                "Go",
                type="primary",
                use_container_width=True,
            )

    if search_submitted and place_query.strip():
        with st.spinner("Searching..."):
            result = forward_geocode(place_query)
        if result.get("error"):
            st.error(result["error"])
        else:
            _apply_custom_location(
                result["latitude"],
                result["longitude"],
                source="search",
                place_name=result["place_name"],
                country=result["country"],
                name=result["place_name"],
                zoom=12,
            )
            st.rerun()

    if isinstance(location, dict) and location.get("latitude") is not None:
        gps_lat = float(location["latitude"])
        gps_lon = float(location["longitude"])
        geo_key = (round(gps_lat, 5), round(gps_lon, 5))
        if st.session_state.last_geo_key != geo_key:
            st.session_state.last_geo_key = geo_key
            with st.spinner("Resolving GPS location..."):
                geo = reverse_geocode(gps_lat, gps_lon)
            _apply_custom_location(
                gps_lat,
                gps_lon,
                source="gps",
                place_name=geo["place_name"],
                country=geo["country"],
                name=f"GPS ({geo['place_name']})",
                zoom=14,
            )
        st.caption("GPS set — click map to fine-tune.")
    elif isinstance(location, dict) and location.get("error"):
        st.caption("GPS unavailable — use map click or place search.")

    lat_col, lon_col = st.columns(2)
    with lat_col:
        manual_lat = st.number_input(
            "Latitude",
            value=float(st.session_state.active_lat),
            format="%.5f",
        )
    with lon_col:
        manual_lon = st.number_input(
            "Longitude",
            value=float(st.session_state.active_lon),
            format="%.5f",
        )

    if (
        st.session_state.last_manual_lat is not None
        and st.session_state.last_manual_lon is not None
        and (
            manual_lat != st.session_state.last_manual_lat
            or manual_lon != st.session_state.last_manual_lon
        )
    ):
        ok, reason = validate_coordinates(manual_lat, manual_lon)
        if ok:
            with st.spinner("Updating location..."):
                geo = reverse_geocode(manual_lat, manual_lon)
            _apply_custom_location(
                manual_lat,
                manual_lon,
                source="manual",
                place_name=geo["place_name"],
                country=geo["country"],
                name=geo["place_name"],
                zoom=13,
            )
        else:
            st.error(reason)
    st.session_state.last_manual_lat = manual_lat
    st.session_state.last_manual_lon = manual_lon

with farm_col:
    st.subheader("Crop & field")
    active_crop = st.text_input(
        "Crop",
        value=st.session_state.active_crop,
    )
    st.session_state.active_crop = normalize_crop(active_crop)
    st.caption(crop_profile_hint(st.session_state.active_crop))

    active_radius = st.number_input(
        "Field radius (meters)",
        min_value=50,
        max_value=5000,
        value=int(st.session_state.active_radius_m),
        step=50,
    )
    st.session_state.active_radius_m = float(active_radius)

    with st.expander("Save / load farms", expanded=False):
        farm_name = st.text_input("Farm name", placeholder="My Wheat Field")
        if st.button("Save current location as farm", type="secondary"):
            ok, reason = validate_coordinates(
                st.session_state.active_lat, st.session_state.active_lon
            )
            if not farm_name.strip():
                st.error("Farm name is required.")
            elif not ok:
                st.error(reason)
            else:
                geo = reverse_geocode(
                    st.session_state.active_lat, st.session_state.active_lon
                )
                farm = farms.create_farm(
                    name=farm_name.strip(),
                    crop=st.session_state.active_crop,
                    latitude=st.session_state.active_lat,
                    longitude=st.session_state.active_lon,
                    radius_m=st.session_state.active_radius_m,
                    place_name=geo["place_name"],
                    country=geo["country"],
                )
                _apply_farm(farm, source="farm")
                st.success(
                    f"Saved **{farm['name']}** at {geo['place_name']}, {geo['country']}."
                )
                st.rerun()

        saved = farms.list_farms()
        if saved:
            st.markdown("**My farms**")
            for farm in saved:
                col_a, col_b, col_c = st.columns([3, 1, 1])
                with col_a:
                    st.caption(
                        f"{farms.format_farm_label(farm)} · {farm['crop']} · "
                        f"{farm['radius_m']:.0f} m"
                    )
                with col_b:
                    if st.button("Load", key=f"load_{farm['region_id']}"):
                        _apply_farm(farm, source="farm")
                        st.rerun()
                with col_c:
                    if st.button("Delete", key=f"del_{farm['region_id']}"):
                        farms.delete_farm(farm["region_id"])
                        if st.session_state.loaded_farm_id == farm["region_id"]:
                            st.session_state.loaded_farm_id = None
                        st.rerun()

        if st.session_state.loaded_farm_id:
            runs = plan_history.list_plan_runs(st.session_state.loaded_farm_id)
            if runs:
                st.markdown("**Plan history** (last 10 runs)")
                for run in runs:
                    ts = run["created_at"][:16].replace("T", " ")
                    snippet = run["reasoning_snippet"][:80]
                    if len(run["reasoning_snippet"]) > 80:
                        snippet += "…"
                    st.caption(
                        f"{ts} · **{run['urgency']}** · {run['crop']} — {snippet or 'No summary'}"
                    )

user_prompt = st.text_area(
    "Custom Strategy Request",
    "Generate a sustainable optimization plan for this sector.",
)
run_btn = st.button("Trigger Agent Network", type="primary")

st.subheader("Agent System Logs & Outputs")

if run_btn:
    wf = _workflow_args_from_state()
    with st.status("Running ADK workflow...", expanded=True) as status:
        st.caption("1. Validating input and security guardrail…")
        st.caption("2. Fetching live weather from Open-Meteo…")
        st.caption("3. Generating irrigation plan with Gemini…")
        result = run_agro_workflow(
            user_prompt,
            wf["region_id"],
            region_name=wf["region_name"],
            region_district=wf["region_district"],
            region_mode="custom",
            latitude=wf["latitude"],
            longitude=wf["longitude"],
            crop=wf["crop"],
            radius_m=wf["radius_m"],
            place_name=wf["place_name"],
            country=wf["country"],
        )
        if result["status"] == "success":
            status.update(label="Pipeline complete", state="complete")
        elif result["status"] == "blocked":
            status.update(label="Security Guardrail: BLOCKED", state="error")
        else:
            status.update(label="Workflow error", state="error")

    if result["status"] == "success":
        result = ensure_plan_content(result, wf["crop"])
        plan_history.save_plan_run(
            wf["region_id"],
            urgency=result.get("irrigation_urgency", "UNKNOWN"),
            crop=wf["crop"],
            latitude=wf["latitude"],
            longitude=wf["longitude"],
            place_name=wf.get("place_name", ""),
            reasoning=result.get("reasoning", ""),
            user_prompt=user_prompt,
        )

    st.session_state.last_result = result
    st.session_state.last_wf = wf
    st.session_state.last_region_meta = wf["region_meta"] or {
        "display_name": wf["region_name"],
        "district": wf["region_district"],
        "crop": wf["crop"],
        "latitude": wf["latitude"],
        "longitude": wf["longitude"],
        "place_name": wf["place_name"],
        "country": wf["country"],
    }

if st.session_state.get("last_result"):
    result = st.session_state.last_result
    region_meta = st.session_state.get("last_region_meta")
    wf = st.session_state.get("last_wf", {})
    pipeline = result.get("pipeline", {})

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
            st.error(f"**{error_stage_heading('guardrail')}**")
            st.markdown(result.get("message", "Input blocked by guardrail."))
        elif result["status"] == "error":
            _render_error_result(result, pipeline)
        else:
            _render_success_result(result, wf, region_meta)
