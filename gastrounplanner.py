import argparse
import collections
import datetime
import re
import tomllib

import requests
from bs4 import BeautifulSoup


Shift = collections.namedtuple("Shift", ["name", "shift_name", "start", "end"])


def parse_timespan(time_range, date):
    # Parses a simple time range string, like "19:00-23:00", to an end and start time.
    # It needs the date for the start time.

    date_str = datetime.datetime.strftime(date, "%Y-%m-%d")
    start_time_str, end_time_str = time_range.split("-")

    start_time = datetime.datetime.strptime(f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M")
    end_time = datetime.datetime.strptime(f"{date_str} {end_time_str}", "%Y-%m-%d %H:%M")

    if end_time <= start_time:
        # Adjust end day if we are passing midnight, like "21:00-01:00".
        end_time += datetime.timedelta(days=1)

    return start_time, end_time


def parse_shifts(content, date, truncate=False):
    # The shift data itself only knows what timespan the shifts are.
    # We therefore have to know which day it is through "date".
    # "truncate" will make sure no shift passes midnight (end them 23:59:59 same day).

    date_str = datetime.datetime.strftime(date, "%Y-%m-%d")

    shifts = []
    soup = BeautifulSoup(content, "html.parser")

    for tr in soup.find_all("tr", {"class": "timetracker_row_expand"}):
        # Each tr is a single shift. The children tds contain data about the shift.

        tds = tr.find_all("td")

        name, _, shift_name = [element.text for element in tds[0].children]
        shift_timespan = tds[1].text
        start_time, end_time = parse_timespan(shift_timespan, date)

        if truncate:
            start_time, end_time = truncate_to_day(start_time, end_time)

        shifts.append(Shift(name, shift_name, start_time, end_time))

    return shifts


def shifts2ical(shifts):
    ical = "BEGIN:VCALENDAR\n"

    for shift in shifts:
        ical += "BEGIN:VEVENT\n"
        ical += f"SUMMARY: {shift.shift_name}\n"
        ical += f"DTSTART: {datetime.datetime.strftime(shift.start, '%Y%m%dT%H%M%S')}\n"
        ical += f"DTEND: {datetime.datetime.strftime(shift.end, '%Y%m%dT%H%M%S')}\n"
        ical += "END:VEVENT\n"

    ical += "END:VCALENDAR\n"

    return ical


def truncate_to_day(start_time, end_time):
    # Truncate end times to 23:59:59 of start time if they pass midnight.
    if end_time.date() > start_time.date():
        end_time = datetime.datetime.combine(start_time.date(), datetime.datetime.max.time().replace(microsecond=0))

    return start_time, end_time


class GastroUnplanner():
    def __init__(self, base_url):
        self.base_url = base_url

        self.session = requests.session()
        self.logged_in = False
        self.truncate = True

    def login(self, login_email, login_password):
        login_url = self.base_url + "index.php?controller=TimeSheet"
        response = self.session.post(login_url, data={"login_email": login_email, "login_password": login_password, "login_user": 1}, allow_redirects=False)

        if response.status_code == 303 and response.headers["Location"] == self.base_url + "index.php?controller=TimeSheet&action=welcome":
            self.logged_in = True
        else:
            raise Exception("Unable to login to: %s", repr(login_url))

    def get_shifts(self, days_since, days_until, name_filter=None):
        if not self.logged_in:
            return

        shifts_url = self.base_url + "index.php?controller=TimeSheet&action=getPersonalList"
        today = datetime.datetime.today().date()
        all_shifts = []

        for days in range(days_since, days_until):
            date = today + datetime.timedelta(days=days)
            response = self.session.post(shifts_url, data={"year": date.year, "month": date.month, "day": date.day}, headers={"X-Requested-With": "XMLHttpRequest"})
            all_shifts.extend(parse_shifts(response.text, date, truncate=self.truncate))

        if name_filter:
            shifts = [shift for shift in all_shifts if re.search(name_filter, shift.name)]
        else:
            shifts = all_shifts

        return shifts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Creates an ical from a https://gastroplanner.eu/ instance.")
    parser.add_argument("config")
    parser.add_argument("--output", help="Output to file rather than stdout")
    parser.add_argument("--since", type=int, default=-7)
    parser.add_argument("--until", type=int, default=30)
    args = parser.parse_args()

    with open(args.config, "rb") as f:
        config = tomllib.load(f)

    gu = GastroUnplanner(config["url"])
    gu.login(config["email"], config["password"])
    # Get shifts. Since 7 days ago and until 30 days forward, by default.
    shifts = gu.get_shifts(args.since, args.until, name_filter=config.get("name_filter"))

    ical = shifts2ical(shifts)

    if args.output:
        with open(args.output, "w") as f:
            f.write(ical)
    else:
        print(ical, end="")
