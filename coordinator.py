from datetime import datetime, timedelta
import logging
import unicodedata
from zoneinfo import ZoneInfo

import aiohttp
from bs4 import BeautifulSoup

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BASE_URL, CONF_DATABASE, CONF_PASSWORD, CONF_USERNAME, LOGIN_URL

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=1)

TZ_STOCKHOLM = ZoneInfo("Europe/Stockholm")

SWEDISH_MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4,
    "maj": 5, "juni": 6, "juli": 7, "augusti": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}


def _strip_diacritics(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _safe_float(value: str) -> float | None:
    cleaned = value.replace(",", ".").replace("\xa0", "").strip()
    if not cleaned or cleaned == "-":
        return None
    return float(cleaned)


def _build_domain_path(database: str, username: str) -> str:
    url_database = _strip_diacritics(database)
    return f"/domains/{url_database}/objects/{username}"


def _parse_daily_table(html: str) -> list[tuple[str, float]]:
    soup = BeautifulSoup(html, "html.parser")
    tbody = soup.find("tbody")
    if not tbody:
        return []
    rows = []
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        date_str = cells[0].get_text(strip=True)
        kwh = _safe_float(cells[1].get_text(strip=True))
        if kwh is not None:
            rows.append((date_str, kwh))
    return rows


async def async_validate_credentials(
    username: str, password: str, database: str
) -> None:
    jar = aiohttp.CookieJar(unsafe=True)
    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        await _async_login(session, username, password, database)


async def _async_login(
    session: aiohttp.ClientSession,
    username: str,
    password: str,
    database: str,
) -> None:
    async with session.get(BASE_URL) as resp:
        resp.raise_for_status()
        html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    token_input = soup.find("input", {"name": "__RequestVerificationToken"})
    if not token_input:
        raise UpdateFailed("Could not find antiforgery token on login page")

    token = token_input["value"]

    form_data = {
        "RentableObjectNumber": username,
        "Password": password,
        "DatabaseName": database,
        "RememberMe": "true",
        "__RequestVerificationToken": token,
    }

    async with session.post(LOGIN_URL, data=form_data, allow_redirects=True) as resp:
        resp.raise_for_status()
        if "/account/logon" in str(resp.url).lower():
            raise ConfigEntryAuthFailed("Login failed - check credentials")


class EcoguardCoordinator(DataUpdateCoordinator[dict]):
    historical_entries: list[tuple[datetime, float]]
    historical_cost_entries: list[tuple[datetime, float, float]]

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Ecoguard Insight",
            update_interval=UPDATE_INTERVAL,
        )
        self._username = entry.data[CONF_USERNAME]
        self._password = entry.data[CONF_PASSWORD]
        self._database = entry.data[CONF_DATABASE]
        self._domain_path = _build_domain_path(self._database, self._username)
        self._session: aiohttp.ClientSession | None = None
        self._cached_month_entries: list[tuple[datetime, float]] = []
        self._cached_month_rates: dict[tuple[int, int], float] = {}
        self._cached_months: set[tuple[int, int]] = set()
        self.historical_entries = []
        self.historical_cost_entries = []

    async def async_shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        await super().async_shutdown()

    async def _new_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            await self._session.close()
        jar = aiohttp.CookieJar(unsafe=True)
        self._session = aiohttp.ClientSession(cookie_jar=jar)
        await _async_login(self._session, self._username, self._password, self._database)
        return self._session

    async def _async_update_data(self) -> dict:
        try:
            session = await self._new_session()

            data: dict = {}
            for name, fetch in [
                ("yearly", self._fetch_yearly),
                ("monthly", self._fetch_monthly),
                ("pricelists", self._fetch_pricelists),
                ("historical", self._fetch_historical),
            ]:
                try:
                    await fetch(session, data)
                except Exception:
                    _LOGGER.exception("Failed to fetch %s data", name)

            return data

        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error fetching data: {err}") from err

    async def _fetch_yearly(
        self, session: aiohttp.ClientSession, data: dict
    ) -> None:
        url = f"{BASE_URL}{self._domain_path}/consumption/ViewLatestYearConsumptionTable?UtilityCode=ELEC"
        async with session.get(url) as resp:
            resp.raise_for_status()
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        tbody = soup.find("tbody")
        if not tbody:
            return

        rows = tbody.find_all("tr")
        for i, row in enumerate(rows, start=1):
            cells = row.find_all("td")
            if len(cells) >= 3:
                name_text = cells[0].get_text(strip=True)
                kwh_text = cells[1].get_text(strip=True)
                cost_text = cells[2].get_text(strip=True)
                data[f"month_{i}_name"] = name_text
                data[f"month_{i}_kwh"] = _safe_float(kwh_text)
                data[f"month_{i}_cost"] = _safe_float(cost_text)

        data["yearly_month_count"] = len(rows)

    async def _fetch_monthly(
        self, session: aiohttp.ClientSession, data: dict
    ) -> None:
        url = f"{BASE_URL}{self._domain_path}/consumption/ViewCurrentMonthTable?UtilityCode=ELEC"
        async with session.get(url) as resp:
            resp.raise_for_status()
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        tbody = soup.find("tbody")
        if not tbody:
            return

        rows = tbody.find_all("tr")
        total_kwh = 0.0
        today_kwh = None
        today_date = None
        day_count = len(rows)

        daily_entries = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
                date_text = cells[0].get_text(strip=True)
                kwh_val = _safe_float(cells[1].get_text(strip=True))
                daily_entries.append({"date": date_text, "kwh": kwh_val})
                if kwh_val is not None:
                    total_kwh += kwh_val
                    today_kwh = kwh_val
                    today_date = date_text

        data["current_month_total_kwh"] = round(total_kwh, 3)
        data["current_month_day_count"] = day_count
        data["current_month_daily"] = daily_entries
        data["today_kwh"] = today_kwh
        data["today_date"] = today_date

    async def _fetch_historical(
        self, session: aiohttp.ClientSession, data: dict
    ) -> None:
        month_count = data.get("yearly_month_count", 0)
        new_months: list[tuple[int, int, int]] = []
        for i in range(1, month_count + 1):
            name = data.get(f"month_{i}_name")
            if not name:
                continue
            parts = name.lower().split()
            if len(parts) != 2:
                continue
            month_num = SWEDISH_MONTHS.get(parts[0])
            if not month_num:
                continue
            try:
                year = int(parts[1])
            except ValueError:
                continue

            kwh_total = data.get(f"month_{i}_kwh")
            cost_total = data.get(f"month_{i}_cost")
            if kwh_total and cost_total:
                self._cached_month_rates[(year, month_num)] = cost_total / kwh_total

            if (year, month_num) not in self._cached_months:
                ts = int(datetime(year, month_num, 1, tzinfo=TZ_STOCKHOLM).timestamp())
                new_months.append((year, month_num, ts))

        for year, month_num, ts in new_months:
            url = f"{BASE_URL}{self._domain_path}/consumption/ViewMonthTable/{ts}?UtilityCode=ELEC"
            async with session.get(url) as resp:
                resp.raise_for_status()
                html = await resp.text()

            for date_str, kwh in _parse_daily_table(html):
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ_STOCKHOLM)
                except ValueError:
                    continue
                self._cached_month_entries.append((dt, kwh))

            self._cached_months.add((year, month_num))

        current_rate = data.get("price_per_kwh", 0.0) or 0.0
        today = datetime.now(TZ_STOCKHOLM).date()

        current_entries: list[tuple[datetime, float]] = []
        for entry in data.get("current_month_daily", []):
            date_str = entry.get("date")
            kwh = entry.get("kwh")
            if not date_str or kwh is None:
                continue
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ_STOCKHOLM)
            except ValueError:
                continue
            if dt.date() == today:
                continue
            current_entries.append((dt, kwh))

        hourly_url = f"{BASE_URL}{self._domain_path}/consumption/ViewLatestDayTable?utilityCode=ELEC"
        async with session.get(hourly_url) as resp:
            resp.raise_for_status()
            hourly_html = await resp.text()

        hourly_soup = BeautifulSoup(hourly_html, "html.parser")
        hourly_tbody = hourly_soup.find("tbody")
        hourly_entries: list[tuple[datetime, float]] = []
        if hourly_tbody:
            for row in hourly_tbody.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                time_range = cells[0].get_text(strip=True)
                kwh = _safe_float(cells[1].get_text(strip=True))
                if kwh is None:
                    continue
                try:
                    hour = int(time_range.split(":")[0])
                except ValueError:
                    continue
                dt = datetime(today.year, today.month, today.day, hour, tzinfo=TZ_STOCKHOLM)
                hourly_entries.append((dt, kwh))

        all_entries = self._cached_month_entries + current_entries + hourly_entries
        all_entries.sort(key=lambda x: x[0])
        self.historical_entries = all_entries

        cost_entries: list[tuple[datetime, float, float]] = []
        for dt, kwh in all_entries:
            rate = self._cached_month_rates.get((dt.year, dt.month), current_rate)
            cost_entries.append((dt, kwh, rate))
        self.historical_cost_entries = cost_entries

    async def _fetch_pricelists(
        self, session: aiohttp.ClientSession, data: dict
    ) -> None:
        url = f"{BASE_URL}{self._domain_path}/pricelists"
        async with session.get(url) as resp:
            resp.raise_for_status()
            json_data = await resp.json()

        pricelists = json_data.get("PriceLists", [])
        if not pricelists:
            return

        pl = pricelists[0]
        components = pl.get("Components", [])
        if components:
            data["price_per_kwh"] = components[0].get("Rate")
        data["price_valid_from"] = pl.get("Interval")
