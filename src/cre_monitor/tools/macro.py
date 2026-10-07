"""Macro-economic data tools backed by official, keyless public APIs.

* ``boe_series``  - Bank of England Interactive Statistical Database (IADB)
  CSV endpoint. Daily series such as Bank Rate and gilt yields.
* ``ons_series``  - ONS time-series JSON endpoint
  (``https://www.ons.gov.uk/<path>/timeseries/<cdid>/<dataset>/data``).
* ``london_employment`` - Nomis (ONS labour market statistics) API,
  Annual Population Survey employment rate for the London region.

All three endpoints were verified live in October 2026. Series codes are
centralised in :data:`BOE_SERIES` / :data:`ONS_SERIES` so colleagues can add
indicators without touching the parsing code.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta

from langchain_core.tools import tool
from pydantic import BaseModel

from cre_monitor.config import get_settings
from cre_monitor.tools._http import http_get
from cre_monitor.tools.fixtures import load_json

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Series catalogues  (friendly name -> provider code + metadata)
# --------------------------------------------------------------------------

#: Bank of England IADB series codes.
BOE_SERIES: dict[str, dict[str, str]] = {
    "bank_rate": {"code": "IUDBEDR", "label": "Official Bank Rate (%)"},
    "sonia": {"code": "IUDSOIA", "label": "SONIA overnight rate (%)"},
    "gilt_10y_yield": {"code": "IUDMNPY", "label": "10-year nominal gilt par yield (%)"},
}

#: ONS time series: path segment, CDID and dataset id. Find new ones at
#: https://www.ons.gov.uk/timeseriestool - the URL contains all three parts.
ONS_SERIES: dict[str, dict[str, str]] = {
    "cpih_yoy": {
        "path": "economy/inflationandpriceindices", "cdid": "l55o", "dataset": "mm23",
        "freq": "months", "label": "CPIH annual rate (%)",
    },
    "cpi_yoy": {
        "path": "economy/inflationandpriceindices", "cdid": "d7g7", "dataset": "mm23",
        "freq": "months", "label": "CPI annual rate (%)",
    },
    "unemployment_rate": {
        "path": "employmentandlabourmarket/peoplenotinwork/unemployment", "cdid": "mgsx",
        "dataset": "lms", "freq": "months", "label": "UK unemployment rate 16+ (%)",
    },
    "gdp_growth_qoq": {
        "path": "economy/grossdomesticproductgdp", "cdid": "ihyq", "dataset": "qna",
        "freq": "quarters", "label": "UK real GDP growth, quarter on quarter (%)",
    },
}

BOE_URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
ONS_URL = "https://www.ons.gov.uk/{path}/timeseries/{cdid}/{dataset}/data"
#: London region = geography 2013265927; variable 45 = employment rate 16-64.
NOMIS_URL = (
    "https://www.nomisweb.co.uk/api/v01/dataset/NM_17_5.data.csv"
    "?geography=2013265927&variable=45&measures=20599&time=latest,prevyear"
    "&select=date_name,obs_value"
)


class Observation(BaseModel):
    """One dated value of a time series."""

    period: str  # "2026-10-06", "2026-08" or "2026-Q2"
    value: float


class Series(BaseModel):
    """A named time series plus provenance (for citations)."""

    name: str
    label: str
    source: str
    url: str
    observations: list[Observation]

    @property
    def latest(self) -> Observation | None:
        return self.observations[-1] if self.observations else None


# --------------------------------------------------------------------------
# Fetchers
# --------------------------------------------------------------------------


def _fixture_series(name: str) -> Series:
    return Series(**load_json("macro_series.json")[name])


def fetch_boe(name: str, months: int = 24) -> Series:
    """Daily BoE series for the last ``months`` months (empty days dropped)."""
    if get_settings().cre_offline:
        return _fixture_series(name)
    meta = BOE_SERIES[name]
    start = (date.today() - timedelta(days=31 * months)).strftime("%d/%b/%Y")
    params = {
        "csv.x": "yes", "Datefrom": start, "Dateto": "now", "SeriesCodes": meta["code"],
        "CSVF": "TN", "UsingCodes": "Y", "VPD": "Y", "VFD": "N",
    }
    resp = http_get(BOE_URL, params=params)
    obs = []
    for row in csv.DictReader(io.StringIO(resp.text)):
        raw = (row.get(meta["code"]) or "").strip()
        if not raw:  # BoE leaves today's value blank until published
            continue
        day = datetime.strptime(row["DATE"].strip(), "%d %b %Y").date()
        obs.append(Observation(period=day.isoformat(), value=float(raw)))
    return Series(name=name, label=meta["label"], source="Bank of England", url=str(resp.url), observations=obs)


def fetch_ons(name: str, last_n: int = 12) -> Series:
    """Most recent ``last_n`` observations of an ONS time series."""
    if get_settings().cre_offline:
        return _fixture_series(name)
    meta = ONS_SERIES[name]
    url = ONS_URL.format(**meta)
    data = http_get(url).json()
    obs = []
    for item in data.get(meta["freq"], [])[-last_n:]:
        # ONS dates look like "2026 AUG" (monthly) or "2026 Q2" (quarterly).
        year, _, part = item["date"].partition(" ")
        if meta["freq"] == "months":
            period = f"{year}-{datetime.strptime(part.title(), '%b').month:02d}"
        else:
            period = f"{year}-{part}"
        obs.append(Observation(period=period, value=float(item["value"])))
    return Series(name=name, label=meta["label"], source="ONS", url=url.replace("/data", ""), observations=obs)


def fetch_london_employment() -> Series:
    """London 16-64 employment rate (APS), latest and one year earlier."""
    if get_settings().cre_offline:
        return _fixture_series("london_employment_rate")
    resp = http_get(NOMIS_URL)
    obs = [
        Observation(period=row["DATE_NAME"], value=float(row["OBS_VALUE"]))
        for row in csv.DictReader(io.StringIO(resp.text))
    ]
    return Series(
        name="london_employment_rate", label="London employment rate, aged 16-64 (%)",
        source="ONS Annual Population Survey via Nomis", url="https://www.nomisweb.co.uk/",
        observations=obs,
    )


def format_series(s: Series, max_points: int = 12) -> str:
    """Compact text rendering of a series for the LLM (latest points only)."""
    if not s.observations:
        return f"{s.label}: no data returned."
    pts = s.observations
    # Daily series are long: thin them to roughly month-end points.
    if len(pts) > max_points:
        step = max(1, len(pts) // max_points)
        pts = pts[::-1][::step][::-1]
        if pts[-1] != s.observations[-1]:
            pts.append(s.observations[-1])
    body = ", ".join(f"{o.period}: {o.value:g}" for o in pts[-max_points:])
    return f"{s.label} [source: {s.source}, {s.url}]\nLatest {s.latest.period} = {s.latest.value:g}\n{body}"


# --------------------------------------------------------------------------
# LangChain tools
# --------------------------------------------------------------------------


@tool
def boe_series(name: str, months: int = 24) -> str:
    """Get a Bank of England interest-rate series (official source).

    Args:
        name: One of "bank_rate", "sonia", "gilt_10y_yield".
        months: How many months of history to return (default 24).
    """
    if name not in BOE_SERIES:
        return f"Unknown series {name!r}. Options: {', '.join(BOE_SERIES)}"
    try:
        return format_series(fetch_boe(name, months))
    except Exception as exc:  # noqa: BLE001
        return f"Bank of England fetch failed: {exc}"


@tool
def ons_series(name: str) -> str:
    """Get an official UK economic indicator from the Office for National Statistics.

    Args:
        name: One of "cpih_yoy", "cpi_yoy", "unemployment_rate", "gdp_growth_qoq",
            or "london_employment_rate" (London 16-64 employment rate via Nomis).
    """
    try:
        if name == "london_employment_rate":
            return format_series(fetch_london_employment())
        if name not in ONS_SERIES:
            return f"Unknown series {name!r}. Options: {', '.join(ONS_SERIES)}, london_employment_rate"
        return format_series(fetch_ons(name))
    except Exception as exc:  # noqa: BLE001
        return f"ONS fetch failed: {exc}"
