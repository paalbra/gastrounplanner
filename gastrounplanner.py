"""
Script to fetch GastroPlanner shifts and export as iCal.
"""
import argparse
import collections
import datetime
import hashlib
import logging
import pathlib
import re
import sys
import textwrap
import uuid

if sys.version_info >= (3, 11):
    import tomllib
else:
    # pre-3.11 compatibilty import - requires tomli
    import tomli as tomllib

import requests
from bs4 import BeautifulSoup


Shift = collections.namedtuple("Shift", ["name", "shift_name", "start", "end"])


#
# iCalendar formatting for Shifts
#

PRODID = "-//github.com/paalbra//NONSGML gastrounplanner//EN"
LINESEP = "\r\n"  # CRLF


def _format_dt(dt):
    """ Format a RFC-5545 (3.3.5) - date with local time. """
    return dt.strftime("%Y%m%dT%H%M%S")


def _generate_vevent_lines(shift):
    """ Shift to RFC-5545 (3.6.1) Event Component lines. """
    ident = f"{shift.shift_name}{shift.start}{shift.end}"
    uid = str(uuid.UUID(hashlib.md5(ident.encode("utf-8")).hexdigest()))
    start_str = _format_dt(shift.start)
    end_str = _format_dt(shift.end)
    yield "BEGIN:VEVENT"
    yield f"UID:{uid}"
    yield f"SUMMARY:{shift.shift_name}"
    yield f"DTSTAMP:{start_str}"
    yield f"DTSTART:{start_str}"
    yield f"DTEND:{end_str}"
    yield "END:VEVENT"


def _generate_vcalendar_lines(shifts):
    """ Shift list to RFC-5545 (3.4) iCalendar object lines. """
    yield "BEGIN:VCALENDAR"
    yield "VERSION:2.0"
    yield f"PRODID:{PRODID}"
    for shift in shifts:
        yield from _generate_vevent_lines(shift)
    yield "END:VCALENDAR"
    yield ""  # end with a linesep


def format_ical_shifts(shifts):
    """
    Format a RFC-5545 iCalendar object from a list of Shifts.

    :type shifts: iterable[Shift]

    :rtype: str
    """
    return LINESEP.join(_generate_vcalendar_lines(shifts))


#
# Shift lookup, parsing, and export
#


END_OF_DAY = datetime.time.max.replace(microsecond=0)
""" End of day value. """


def _parse_time(value, time_format="%H:%M"):
    # datetime.time.strptime is introduced in 3.14
    dt = datetime.datetime.strptime(value, time_format)
    return dt.time()


def parse_timespan(raw_value, at_date, truncate=False):
    """
    Parse a time range string into a naive datetime tuple.

    :param str raw_value: time range to parse, e.g. "19:00-23:00"
    :param date at_date: start date for the time range
    :param bool truncate: truncate to END_OF_DAY if time range passes midnight

    :rtype: tuple[datetime.datetime, datetime.datetime]
    :returns: start, end
    """
    logging.debug("parsing timespan=%s (at=%s, truncate=%r)",
                  repr(raw_value), at_date.isoformat(), repr(truncate))
    start_date = end_date = at_date

    start_time_str, end_time_str = raw_value.split("-")
    start_time = _parse_time(start_time_str)
    end_time = _parse_time(end_time_str)

    if end_time <= start_time:
        # Timestamp passes midnight - we either truncate to end of day, or
        # push the end-date to next day
        if truncate:
            end_time = END_OF_DAY
        else:
            end_date += datetime.timedelta(days=1)

    return (
        datetime.datetime.combine(start_date, start_time),
        datetime.datetime.combine(end_date, end_time),
    )


def parse_shifts(content, at_date, truncate=False):
    """
    Parse day shifts into Shift tuples.

    :param str content: page content
    :param datetime.date at_date: see parse_timespan
    :param bool truncate: see parse_timespan

    :rtype: iterator[Shift]
    """
    soup = BeautifulSoup(content, "html.parser")

    for tr in soup.find_all("tr", {"class": "timetracker_row_expand"}):
        # Each tr is a single shift.
        # The children tds contain data about the shift.

        logging.debug("parsing shift/html table row: %s", tr)

        tds = tr.find_all("td")

        # Some shifts have some extra weird values after the third one
        name, _, shift_name = [element.text for element in tds[0].children][:3]

        if shift_name == "":
            logging.warning("skipping empty shift?: %s", repr(tr))
            continue

        shift_timespan = tds[1].text
        start, end = parse_timespan(shift_timespan, at_date, truncate)

        yield Shift(name, shift_name, start, end)


class GastroUnplanner(object):
    """ Log in and find Shifts in GastroPlanner. """

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/") + "/"
        self.session = requests.session()
        self.logged_in = False
        self.truncate = True

    @property
    def login_url(self):
        """ login url (login POST target). """
        return self.base_url + "index.php?controller=TimeSheet"

    @property
    def login_redir_url(self):
        """ login redirect url (expected login redirect). """
        return self.base_url + "index.php?controller=TimeSheet&action=welcome"

    @property
    def shifts_url(self):
        """ shifts url (list shifts at a given date). """
        return (self.base_url +
                "index.php?controller=TimeSheet&action=getPersonalList")

    def login(self, login_email, login_password):
        """ Perform a login for the current session. """
        logging.debug("logging in")
        response = self.session.post(
            self.login_url,
            data={
                "login_email": login_email,
                "login_password": login_password,
                "login_user": 1,
            },
            allow_redirects=False,
        )
        if (response.status_code == 303
                and response.headers["Location"] == self.login_redir_url):
            self.logged_in = True
        else:
            raise RuntimeError("Unable to login to: " + repr(self.login_url))

    def get_shifts_at(self, date):
        """
        Get shifts at a given date.

        :type date: datetime.date

        :rtype: iterator[Shift]
        """
        logging.debug("Looking up shifts at %s", date.isoformat())
        response = self.session.post(
            self.shifts_url,
            data={
                "year": date.year,
                "month": date.month,
                "day": date.day,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        return parse_shifts(response.text, date, truncate=self.truncate)

    def get_shifts(self, days_since, days_until):
        """
        Get shifts in a given date range.

        :param int days_since:
            start date, in days relative to today

        :param int days_until:
            end date, non-inclusive, in days relative to today

        :rtype: iterator[Shift]
        """
        if not self.logged_in:
            return
        today = datetime.date.today()
        dates = (
            today + datetime.timedelta(days=d)
            for d in range(days_since, days_until)
        )
        for date in dates:
            yield from self.get_shifts_at(date)


class ShiftExport(object):
    """ Export settings for a list of shifts. """

    def __init__(self, pattern, filename):
        """
        :param re.Pattern pattern: regex search pattern for Shift.name
        :param pathlib.Path filename: filename to write shifts to
        """
        self.pattern = pattern
        self.filename = filename

    def select_shifts(self, iterable):
        """ Select matching shifts from an iterable of shifts. """
        for shift in iterable:
            if self.pattern.search(shift.name):
                yield shift

    def write_shifts(self, shifts):
        """ Write a list of shifts to the given file. """
        content = format_ical_shifts(shifts)
        with open(self.filename, "w") as f:
            f.write(content)
            logging.info("Wrote %d events to %s", len(shifts), f)

    @classmethod
    def from_config(cls, export):
        """ Get ShiftExport from a config entry. """
        pattern = re.compile(export['name_filter'])
        filename = pathlib.Path(export['file_path'])
        return cls(pattern, filename)


#
# Logging / verbosity setup
#


LOG_FORMAT = "%(levelname)s - %(name)s - %(message)s"
LOG_VERBOSITY = (
    logging.ERROR,
    logging.WARNING,
    logging.INFO,
    logging.DEBUG,
)


def get_log_level(verbosity):
    verbosity_idx = max(0, min(len(LOG_VERBOSITY) - 1, verbosity))
    return LOG_VERBOSITY[verbosity_idx]


class JournaldFormatter(logging.Formatter):
    """
    This formatter prefixes log records with a priority prefix for journald.

    Otherwise the formatter works just like the default Formatter class.  Note
    that any formatting errors (incorrect format strings, etc...) are dealt
    with by the log handler, and won't be prefixed correctly.
    """

    level_priority_map = {
        logging.DEBUG: 7,    # debug
        logging.INFO: 6,     # info
        logging.WARNING: 4,  # warning
        logging.ERROR: 3,    # err
    }

    @classmethod
    def get_priority(cls, levelno):
        """ Get journald priority for a given logging level. """
        if levelno in cls.level_priority_map:
            return cls.level_priority_map[levelno]
        # pull down in-between levelno (ERROR-1 -> WARNING):
        for target_level in sorted(cls.level_priority_map, reverse=True):
            if levelno >= target_level:
                return cls.level_priority_map[target_level]
        # pull up levelno lower than min(level_priority_map):
        return cls.level_priority_map[min(cls.level_priority_map)]

    def format(self, record):
        prefix = "<{}>".format(self.get_priority(record.levelno))
        lines = super().format(record).split("\n")
        return "\n".join(prefix + line for line in lines)


def setup_logging(verbosity=0, journald=False):
    """ Configure logging from verbosity. """
    root = logging.getLogger()
    if root.handlers:
        return

    formatter_class = JournaldFormatter if journald else logging.Formatter

    if verbosity < 0:
        root.addHandler(logging.NullHandler())
    else:
        # This is more or less basicConfig() with *only* a format
        # setting and a custom Formatter class.
        handler = logging.StreamHandler()
        formatter = formatter_class(LOG_FORMAT, None, "%")
        handler.setFormatter(formatter)
        root.addHandler(handler)

    level = get_log_level(int(verbosity))
    root.setLevel(level)


def add_verbosity_args(parser):
    """ Add verbosity args to an ArgumentParser. """
    group = parser.add_argument_group(
        "verbosity",
        textwrap.dedent(
            """
            Adjust debug output to stderr.

            Debug output is controlled by logging, and each -v flag includes
            more log levels:  ERROR (default), WARNING (-v), INFO (-vv), DEBUG
            (-vvv).  Disable all logging with -q.
            """
        ).lstrip(),
    )

    mutex = group.add_mutually_exclusive_group()
    mutex.add_argument(
        "-v",
        action="count",
        dest="verbosity",
        help="increase verbosity",
    )
    mutex.add_argument(
        "-q",
        action="store_const",
        const=-1,
        dest="verbosity",
        help="suppress all debug output",
    )
    mutex.set_defaults(verbosity=0)

    group.add_argument(
        "--journald",
        action="store_true",
        help="use journald format (priority prefix)",
    )

    return group


#
# Script
#


arg_parser = argparse.ArgumentParser(
    description=textwrap.dedent(
        """
        Create iCal feeds from a https://gastroplanner.eu/ instance.

        Writes one RFC-5545 (iCalendar) feed for each *export* in the mandatory
        *config*.
        """
    ).lstrip(),
    formatter_class=argparse.RawDescriptionHelpFormatter,
)
arg_parser.add_argument(
    "config",
    help="A TOML config (required)",
)

range_args = arg_parser.add_argument_group(
    "date range",
    "Select date range for shifts to include, relative to today",
)
range_args.add_argument(
    "--since",
    type=int,
    default=-7,
    help="Start at today + %(metavar)s days (default: %(default)s)",
    metavar="N",
)
range_args.add_argument(
    "--until",
    type=int,
    default=30,
    help=("End at today + %(metavar)s days - not inclusive"
          " (default: %(default)s)"),
    metavar="N",
)
del range_args

add_verbosity_args(arg_parser)


def main(argv=None):
    args = arg_parser.parse_args(argv)
    setup_logging(args.verbosity, args.journald)

    logging.info("start")

    with open(args.config, "rb") as f:
        config = tomllib.load(f)

    exports = tuple(ShiftExport.from_config(e) for e in config['exports'])
    logging.info("generating %d exports...", len(exports))
    if not exports:
        logging.error("no exports in config")
        raise SystemExit(1)

    gu = GastroUnplanner(config["url"])
    gu.login(config["email"], config["password"])

    all_shifts = list(gu.get_shifts(args.since, args.until))
    logging.info("found %d total shifts", len(all_shifts))

    for export in exports:
        shifts = list(export.select_shifts(all_shifts))
        export.write_shifts(shifts)

    logging.info("done")


if __name__ == "__main__":
    main()
