import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

TZ_STOCKHOLM = ZoneInfo("Europe/Stockholm")

SWEDISH_MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4,
    "maj": 5, "juni": 6, "juli": 7, "augusti": 8,
    "september": 9, "oktober": 10, "november": 11, "december": 12,
}


def _safe_float(value: str) -> float | None:
    cleaned = value.replace(",", ".").replace("\xa0", "").strip()
    if not cleaned or cleaned == "-":
        return None
    return float(cleaned)


def _strip_diacritics(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _parse_swedish_month(name: str) -> datetime | None:
    parts = name.lower().split()
    if len(parts) != 2:
        return None
    month_num = SWEDISH_MONTHS.get(parts[0])
    if not month_num:
        return None
    try:
        year = int(parts[1])
    except ValueError:
        return None
    return datetime(year, month_num, 1, tzinfo=TZ_STOCKHOLM)


class TestSafeFloat:
    def test_swedish_decimal(self):
        assert _safe_float("213,0") == 213.0

    def test_thousands_separator(self):
        assert _safe_float("1\xa0234,5") == 1234.5

    def test_dash_returns_none(self):
        assert _safe_float("-") is None

    def test_empty_returns_none(self):
        assert _safe_float("") is None

    def test_whitespace(self):
        assert _safe_float(" 42,7 ") == 42.7


class TestStripDiacritics:
    def test_swedish_chars(self):
        assert _strip_diacritics("HSBHisingsKärra") == "HSBHisingsKarra"

    def test_no_diacritics(self):
        assert _strip_diacritics("foobar") == "foobar"

    def test_multiple_diacritics(self):
        assert _strip_diacritics("åäö") == "aao"


class TestParseSwedishMonth:
    def test_all_months(self):
        for name, num in SWEDISH_MONTHS.items():
            result = _parse_swedish_month(f"{name} 2025")
            assert result == datetime(2025, num, 1, tzinfo=TZ_STOCKHOLM)

    def test_case_insensitive(self):
        result = _parse_swedish_month("Januari 2026")
        assert result == datetime(2026, 1, 1, tzinfo=TZ_STOCKHOLM)

    def test_invalid_month(self):
        assert _parse_swedish_month("foo 2025") is None

    def test_invalid_format(self):
        assert _parse_swedish_month("januari") is None

    def test_invalid_year(self):
        assert _parse_swedish_month("januari abc") is None


class TestYearlyTableParsing:
    SAMPLE_HTML = """
    <table class="table mb-0 table-striped">
        <thead><tr><th>Månad</th><th>Förbrukning [kwh]</th><th>Kostnad</th></tr></thead>
        <tbody>
            <tr>
                <td><a href="/ViewMonthTable/123?UtilityCode=ELEC">februari 2025</a></td>
                <td class="text-end">213,0</td>
                <td class="text-end">190,85</td>
            </tr>
            <tr>
                <td><a href="/ViewMonthTable/456?UtilityCode=ELEC">mars 2025</a></td>
                <td class="text-end">220,0</td>
                <td class="text-end">197,12</td>
            </tr>
            <tr>
                <td><a href="/ViewMonthTable/789?UtilityCode=ELEC">januari 2026</a></td>
                <td class="text-end">270,0</td>
                <td class="text-end">507,6</td>
            </tr>
        </tbody>
    </table>
    """

    def _parse_table(self, html):
        soup = BeautifulSoup(html, "html.parser")
        tbody = soup.find("tbody")
        data = {}
        rows = tbody.find_all("tr")
        for i, row in enumerate(rows, start=1):
            cells = row.find_all("td")
            if len(cells) >= 3:
                data[f"month_{i}_name"] = cells[0].get_text(strip=True)
                data[f"month_{i}_kwh"] = _safe_float(cells[1].get_text(strip=True))
                data[f"month_{i}_cost"] = _safe_float(cells[2].get_text(strip=True))
        data["yearly_month_count"] = len(rows)
        return data

    def test_month_count(self):
        data = self._parse_table(self.SAMPLE_HTML)
        assert data["yearly_month_count"] == 3

    def test_first_month(self):
        data = self._parse_table(self.SAMPLE_HTML)
        assert data["month_1_name"] == "februari 2025"
        assert data["month_1_kwh"] == 213.0
        assert data["month_1_cost"] == 190.85

    def test_last_month(self):
        data = self._parse_table(self.SAMPLE_HTML)
        assert data["month_3_name"] == "januari 2026"
        assert data["month_3_kwh"] == 270.0
        assert data["month_3_cost"] == 507.6

    def test_historical_timestamps(self):
        data = self._parse_table(self.SAMPLE_HTML)
        for i in range(1, data["yearly_month_count"] + 1):
            dt = _parse_swedish_month(data[f"month_{i}_name"])
            assert dt is not None
            assert dt.tzinfo == TZ_STOCKHOLM


class TestMonthlyTableParsing:
    SAMPLE_HTML = """
    <table class="table mb-0 table-striped">
        <thead><tr><th>Tid</th><th>Förbrukning [kwh]</th></tr></thead>
        <tbody>
            <tr>
                <td><a href="/ViewDayTable/123">2026-02-01</a></td>
                <td class="text-end">7,000</td>
            </tr>
            <tr>
                <td><a href="/ViewDayTable/456">2026-02-02</a></td>
                <td class="text-end">10,000</td>
            </tr>
            <tr>
                <td><a href="/ViewDayTable/789">2026-02-28</a></td>
                <td class="text-end"></td>
            </tr>
        </tbody>
    </table>
    """

    def _parse_table(self, html):
        soup = BeautifulSoup(html, "html.parser")
        tbody = soup.find("tbody")
        rows = tbody.find_all("tr")
        total_kwh = 0.0
        today_kwh = None
        today_date = None
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
        return {
            "current_month_total_kwh": round(total_kwh, 3),
            "current_month_day_count": len(rows),
            "current_month_daily": daily_entries,
            "today_kwh": today_kwh,
            "today_date": today_date,
        }

    def test_day_count(self):
        data = self._parse_table(self.SAMPLE_HTML)
        assert data["current_month_day_count"] == 3

    def test_total_kwh(self):
        data = self._parse_table(self.SAMPLE_HTML)
        assert data["current_month_total_kwh"] == 17.0

    def test_today_is_last_with_data(self):
        data = self._parse_table(self.SAMPLE_HTML)
        assert data["today_kwh"] == 10.0
        assert data["today_date"] == "2026-02-02"

    def test_daily_entries(self):
        data = self._parse_table(self.SAMPLE_HTML)
        assert len(data["current_month_daily"]) == 3
        assert data["current_month_daily"][0] == {"date": "2026-02-01", "kwh": 7.0}
        assert data["current_month_daily"][2] == {"date": "2026-02-28", "kwh": None}

    def test_daily_timestamps_parseable(self):
        data = self._parse_table(self.SAMPLE_HTML)
        for entry in data["current_month_daily"]:
            dt = datetime.strptime(entry["date"], "%Y-%m-%d").replace(tzinfo=TZ_STOCKHOLM)
            assert dt.tzinfo == TZ_STOCKHOLM


class TestPricelistParsing:
    SAMPLE_JSON = {
        "StatusCode": "0",
        "ShowCost": True,
        "PriceLists": [
            {
                "Interval": "2026-01-01",
                "Components": [
                    {"Rate": 1.88, "RateUnitCode": "kWh", "Name": "Rörlig avgift"}
                ],
            }
        ],
    }

    def test_extract_rate(self):
        pl = self.SAMPLE_JSON["PriceLists"][0]
        assert pl["Components"][0]["Rate"] == 1.88

    def test_extract_interval(self):
        pl = self.SAMPLE_JSON["PriceLists"][0]
        assert pl["Interval"] == "2026-01-01"

    def test_empty_pricelists(self):
        assert len({"PriceLists": []}["PriceLists"]) == 0
