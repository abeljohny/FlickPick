"""
Client for the NWS API.

The API key is stored in a Databricks secret scope (see setup_secrets.py) and
resolved at runtime via the Databricks SDK - it is never stored in code, env
files, or app.yaml.
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import requests
from databricks.sdk import WorkspaceClient

_w = WorkspaceClient()

logger = logging.getLogger(__name__)
 
NWS_BASE_URL = "https://api.weather.gov"

USER_AGENT = "databricks-day-2-hw (contact: 10260252+abeljohny@users.noreply.github.com)"

_DEFAULT_TIMEOUT_SECS = 15
_DEFAULT_SLEEP_SECS = .25

@dataclass
class GridPoint:
    lat: float
    lon: float
    grid_id: str
    grid_x: int
    grid_y: int
    forecast_url: str
    forecast_hourly_url: str
    state: Optional[str] = None
    city: Optional[str] = None


def _stable_id(*parts: str) -> str:
    raw = "|".join(p or "" for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class WeatherClient:
    """Harvests unstructured weather text from the NWS API and normalizes it into document records."""


    def __init__(self, base_url: str | None = None, timeout: int = _DEFAULT_TIMEOUT_SECS):
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": USER_AGENT, 
                "Accept": "application/geo+json"
            }
        )

    
    def geocode(self, location: str) -> tuple[float, float] | None:
        """location is always assumed to be a latitude, longitude pair"""
        if "," in location:
            parts = [p.strip() for p in location.split(",")]
            if len(parts) == 2:
                lat, lon = float(parts[0]), float(parts[1])
                return lat, lon
        return None
    

    def resolve_grid_point(self, lat: float, lon: float) -> GridPoint:
        """GET /points/{lat},{lon} -> office/grid coordinates + forecast URLs."""
        resp = self._session.get(
            f"{NWS_BASE_URL}/points/{lat:.4f},{lon:.4f}",
            timeout=_DEFAULT_TIMEOUT_SECS,
        )
        time.sleep(_DEFAULT_SLEEP_SECS)
        resp.raise_for_status()
        props = resp.json()["properties"]
        return GridPoint(
            lat=lat,
            lon=lon,
            grid_id=props["gridId"],
            grid_x=props["gridX"],
            grid_y=props["gridY"],
            forecast_url=props["forecast"],
            forecast_hourly_url=props["forecastHourly"],
            state=props.get("relativeLocation", {})
            .get("properties", {})
            .get("state"),
            city=props.get("relativeLocation", {})
            .get("properties", {})
            .get("city"),
        )        


    def active_alerts(self, lat: float, lon: float) -> list[dict[str, Any]]:
        """GET /alerts/active?point={lat},{lon} -> active alerts covering
        this point. Using the point filter (rather than ?area=STATE) keeps
        results scoped to the actual location instead of the whole state."""
        resp = self._session.get(
            f"{NWS_BASE_URL}/alerts/active",
            params={"point": f"{lat:.4f},{lon:.4f}"},
            timeout=_DEFAULT_TIMEOUT_SECS,
        )
        time.sleep(_DEFAULT_SLEEP_SECS)
        resp.raise_for_status()
        return resp.json().get("features", [])
    

    def forecast_periods(self, grid: GridPoint) -> list[dict[str, Any]]:
        """GET /gridpoints/{office}/{x},{y}/forecast -> multi-day narrative forecast periods."""
        resp = self._session.get(grid.forecast_url, timeout=_DEFAULT_TIMEOUT_SECS)
        time.sleep(_DEFAULT_SLEEP_SECS) 
        resp.raise_for_status()
        payload = resp.json()
        return payload["properties"]["periods"], payload["properties"].get("updated")
    
    
    @staticmethod
    def normalize_alert(feature: dict[str, Any], location: str) -> dict[str, Any]:
        props = feature.get("properties", {})
        description = (props.get("description") or "").strip()
        instruction = (props.get("instruction") or "").strip()
        narrative_text = description
        if instruction:
            narrative_text = f"{description}\n\nWhat to do: {instruction}".strip()
        return {
            "id": props.get("id") or feature.get("id"),
            "location": location,
            "source_type": "alert",
            "headline": props.get("headline") or props.get("event"),
            "narrative_text": narrative_text,
            "issued_at": props.get("sent"),
            "effective_at": props.get("effective"),
            "payload": feature,
            "synced_at": _now_iso(),
        }


    @staticmethod
    def normalize_forecast_period(period: dict[str, Any], location: str, updated_at: Optional[str]) -> dict[str, Any]:
        dedup_key = _stable_id(location, str(period.get("number")), updated_at or "")
        headline = f"{period.get('name')}: {period.get('shortForecast')}"
        payload = {**period, "location": location, "forecast_updated": updated_at}
 
        return {
            "id": f"forecast-{dedup_key}",
            "location": location,
            "source_type": "forecast",
            "headline": headline,
            "narrative_text": (period.get("detailedForecast") or "").strip(),
            "issued_at": updated_at,
            "effective_at": period.get("startTime"),
            "payload": payload,
            "synced_at": _now_iso(),
        }

    
    def documents_for_location(self, location: str, limit: int = 50) -> list[dict[str, Any]]:
        coords = self.geocode(location)
        if not coords:
            logger.warning("skipping location=%r — geocode failed", location)
            return []
        lat, lon = coords

        docs: list[dict[str, Any]] = []

        try:
            for feature in self.active_alerts(lat, lon):
                docs.append(self.normalize_alert(feature, location))
        except requests.HTTPError as e:
            logger.warning("alerts fetch failed for %r: %s", location, e)

        try:
            grid = self.resolve_grid_point(lat, lon)
            periods, updated_at = self.forecast_periods(grid)
            for period in periods:
                docs.append(
                    self.normalize_forecast_period(period, location, updated_at)
                )
        except requests.HTTPError as e:
            logger.warning("forecast fetch failed for %r: %s", location, e)
 
        return docs[:limit]

    
    def documents(self, locations: Iterable[str], limit: int = 50) -> list[dict[str, Any]]:
        """Harvest across multiple locations. `limit` is applied per
        location, mirroring how /weather/sync's request body is shaped."""
        all_docs: list[dict[str, Any]] = []
        for location in locations:
            all_docs.extend(self.documents_for_location(location, limit=limit))
        return all_docs
    