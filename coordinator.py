from datetime import timedelta
import logging
import unicodedata

import aiohttp
from bs4 import BeautifulSoup

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BASE_URL, CONF_DATABASE, CONF_PASSWORD, CONF_USERNAME, LOGIN_URL

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=1)


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

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(cookie_jar=jar)
        return self._session

    async def async_shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        await super().async_shutdown()

    async def _async_update_data(self) -> dict:
        try:
            if self._session and not self._session.closed:
                await self._session.close()
            jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(cookie_jar=jar)
            session = self._session
            await _async_login(session, self._username, self._password, self._database)

            data: dict = {}
            await self._fetch_yearly(session, data)
            await self._fetch_monthly(session, data)
            await self._fetch_pricelists(session, data)
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
