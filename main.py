from dataclasses import dataclass
from typing import List, Tuple, Union
import math
import re
import requests
import pendulum
import FreeSimpleGUI as sg
import asyncio
import aiohttp
import time, json
import sys
import os
import subprocess
from loguru import logger
from config import ROTA_HOSTNAME, login_info, APIKEY
from bs4 import BeautifulSoup


@dataclass()
class RotaBro:
    shift_id: str
    date: str
    time: str
    type: str
    vols: List[str]
    vol_shift_id: List[str]
    dt_obj: pendulum.DateTime

    def toJSON(self):
        return json.dumps(self, default=lambda i: i.__dict__, sort_keys=True, indent=4)


@dataclass()
class Volunteer:
    id: str
    name: str
    rota: List[str]
    last_shift_scheduled: str = None
    last_update: str = None
    note: str = ""


@dataclass()
class Shift:
    type: str
    dt_obj: pendulum.DateTime


@dataclass()
class DBSCheck:
    name: str
    expiry_date: pendulum.DateTime


async def login() -> aiohttp.ClientSession:
    """
    Returns logged in Session with cookies, for cases where API/basic auth doesn't work
    E.g. the upcoming gaps page (Live bug)
    """
    login_url = f"{ROTA_HOSTNAME}/auth"

    # Need to use cookie login for this, otherwise (basic auth/API) it automatically signs up to displayed shifts - Live bug.
    session = aiohttp.ClientSession()
    payload = {
        "utf8": "✓",
        "account_session[username]": login_info["username"],
        "account_session[password]": login_info["password"],
        "commit": "Log+In",
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    async with session.post(login_url, data=payload, headers=headers) as resp:
        text = await resp.text()
        if "Login failed" in text:
            await session.close()
            raise Exception("Session Login failed")

    return session


async def find_a_shift(
    from_date: pendulum.DateTime, to_date: pendulum.DateTime
) -> List[List[str]]:
    """
    Returns list of shifts with gaps in, or leader gaps between given dates.
    ["Leader", "Date & Time", "with whom"]
    """
    shift_types = ["leader", "hours of need", "duty room"]
    start = from_date.format("YYYY-MM-DD")
    end = to_date.format("YYYY-MM-DD")
    url = f"{ROTA_HOSTNAME}/rota/find_a_shift?start_date={start}&end_date={end}"

    async with await login() as session:
        async with session.get(url) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    gaps = []
    results = soup.find_all("tr")
    if not results:
        logger.error("No shift gaps found between given dates.")
        return
    for x in results:
        cell_text = x.get_text().strip()
        if not cell_text:
            continue
        split_row = cell_text.split("\n")
        split_row = [item.strip() for item in split_row]
        if split_row[0].lower() in shift_types:
            gaps.append(split_row)
    return gaps


# Main sign up function
# Make edits to rota and vol name here
async def make_sign_ups(
    session: requests.Session,
    name: str,
    pattern,
    start_date: pendulum.DateTime,
    rota_length=6,
):
    vol = get_vol_by_name(session, name)
    assert vol
    # pattern = [
    #     ["Monday 19:00-22:00", "Tuesday 19:00-22:00"],
    #     ["OFF"],
    #     ["OFF"],
    #     ["OFF"],
    #     ["Thursday 22:30-01:00"],
    #     ["Thursday 19:00-22:00"],
    #     ["Wednesday 19:00-22:00"],
    #     ["Friday 19:00-22:00"],
    # ]
    # start_date = input("Enter start date (dd.mm.yyyy)\n")
    # start_date = pendulum.from_format(start_date, "DD.MM.YYYY")
    dates = pattern_to_dates(session, pattern, start_date, rota_length)
    rota = await abuild_rota_data(None, start_date, start_date.add(months=rota_length))
    exp, skip = dates_to_shift_ids(dates, rota)
    sign, blocked = verify_shify_ready_for_signup(vol, exp)
    if skip:
        for shift in skip:
            logger.warning(
                f"shift not found on rota: {shift.format('DD MMM YY @ HHmm')}"
            )
    if blocked:
        for shift in blocked:
            # this stuff needs to be added somehow to gui: (x skipped)
            logger.warning(
                f"shift already has 2 vols: {shift.dt_obj.format('DD MMM YY @ HHmm')}"
            )
    if not sign:
        logger.warning(
            "Not able to sign up to any shifts in period, check they're not already signed up/shifts exist/shifts aren't full"
        )
        sg.PopupError("Error - No shifts found")
        return
    for shift in sign:
        logger.info(f"signup for: {shift.dt_obj.format('DD MMM YY @ ddd HHmm')}")
    if (
        sg.PopupOKCancel(
            f"Make {len(sign)} sign ups for {vol.name} ({len(skip) + len(blocked)} shifts skipped)\nStarting with: {sign[0].dt_obj.format('DD MMM YY @ HHmm')}\nEnding with {sign[-1].dt_obj.format('DD MMM YY @ HHmm')}"
        )
        != "OK"
    ):
        return
    logger.info("apost_all")
    res = await apost_all_sign_ups(session, vol, sign)
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # asyncio.run(apost_all_sign_ups(session, vol, sign))
    return res


# Main remove sign up function, untested
# Make edits to remove sign ups here, shouldn't be needed since Live already has decent way of doing this
def remove_sign_ups(session):
    vol = get_vol_by_name(session, "NatashaJ 1928")
    start_date = input("Enter start date (dd.mm.yyyy)\n")
    start_date = pendulum.from_format(start_date, "DD.MM.YYYY")
    end_date = start_date.add(weeks=8)
    # remove_all_sign_ups(session, vol, start_date, end_date)


def get_week_number(session, date: pendulum.DateTime) -> int:
    rota = get_rota(session, date)
    week_num = rota[0].type
    return int(re.search(r"\d+", week_num).group())


def get_week_number_gui(
    session, date: pendulum.DateTime, gui_start=False
) -> Union[int, dict]:
    rota = get_rota(session, date)
    week_num = rota[0].type
    if gui_start:
        vol_shifts = {}
        for shift in rota:
            if shift.dt_obj < pendulum.now() or not shift.vols:
                continue
            for vol in shift.vols:
                if vol == "[sign up]" or "Week" in vol:
                    continue
                if vol in vol_shifts:
                    vol_shifts[vol].append(shift.dt_obj)
                else:
                    vol_shifts[vol] = [shift.dt_obj]
    return int(re.search(r"\d+", week_num).group()), vol_shifts


def rota_pattern_to_dates(
    session: requests.Session,
    pattern,
    start_date: pendulum.DateTime,
    rota_length: int = 6,
) -> List[str]:
    if len(pattern) != 8:
        logger.warning(f"Pattern is {len(pattern)} instead of 8 weeks long")
    end_date = start_date.add(months=rota_length)
    date = start_date.start_of("week")
    week_num = get_week_number(session, date)  # need to load rota to get week number??
    logger.info(f"Week number of {start_date.format('DD.MM.YY')} is {week_num}")
    shifts = []
    for i in range(rota_length * 4):
        week = ((week_num + i - 1) % 8) + 1
        week = f"Week {week}"
        for day in pattern[week]:
            for shift in pattern[week][day]:
                if date > end_date:
                    return shifts
                shift = shift.replace(" ", "")
                shift_start_time = shift.split("-")[0]
                date = date.at(int(shift_start_time[:2]), int(shift_start_time[2:4]))
                if date >= start_date:
                    shifts.append(date)
            date = date.add(days=1)
    return shifts


def pattern_to_dates(
    session: requests.Session,
    pattern,
    start_date: pendulum.DateTime,
    rota_length: int = 6,
) -> List[str]:  # number of months to create shifts for
    """
    Converts a shift pattern into a list of scheduled shift dates.

    Parameters:
    session (requests.Session): An active session for making API requests.
    pattern (iterable): A sequence representing the shift pattern for 8 weeks. Each week contains a list
                        of shifts, where each shift is a string with a day of the week and time
                        e.g. [[Monday 1900-2200], [Tuesday 2200-0100, Thursday 1900-2200]...] there should be 8 elements in outside list for 8 week rota.
    start_date (pendulum.DateTime): The starting date for the schedule, which is adjusted to the nearest Monday.
    rota_length (int, optional): The number of months to generate shifts for. Defaults to 6.

    Returns:
    List[str]: A list of shift datetime strings (in the format "D M YYYY HHmm") for the scheduled shifts.
    """
    if len(pattern) != 8:
        logger.warning(f"Pattern is {len(pattern)} instead of 8 weeks long")
    # for consistency, set start_date as a Monday 0000
    date = start_date.start_of("week")
    # print("Rota fetch for week num... ", end="")
    week_num = get_week_number(
        session, date
    )  # need to load rota to get week number, should find better way than making request here.
    shifts = []
    for i in range(rota_length * 4):
        week = (week_num + i - 1) % 8
        for shift in pattern[week]:
            if isinstance(shift, int):
                pass
            elif len(shift) < 6:
                pass
            else:
                day_of_week = shift.split(" ")[0]
                weekday = pendulum.from_format(day_of_week, "dddd").day_of_week
                shift_time = shift.split(" ")[1].replace(":", "")

                if weekday == 0:
                    # This condition exists as `date` is always a Monday, and if we do date.next("Monday"), like we can do with rest of the days of the week, that will move the shift to following Monday.
                    dt = pendulum.from_format(
                        f"{date.day} {date.month} {date.year} {shift_time.split('-')[0]}",
                        "D M YYYY HHmm",
                        # tz="Europe/London",
                    )
                    if dt > start_date:
                        shifts.append(dt)
                else:
                    real_date = date.next(weekday)
                    dt = pendulum.from_format(
                        f"{real_date.day} {real_date.month} {real_date.year} {shift_time.split('-')[0]}",
                        "D M YYYY HHmm",
                        # tz="Europe/London",
                    )
                    if dt > start_date:
                        shifts.append(dt)

        date = date.add(days=7)
    return shifts


def dates_to_shift_ids(
    pattern: List[pendulum.DateTime], rota: List[RotaBro]
) -> Tuple[RotaBro, pendulum.DateTime]:
    expected_shifts = []
    skipped_shifts = []
    for shift in pattern:
        for check_shift in rota:
            if isinstance(check_shift.dt_obj, str):
                check_shift.dt_obj = pendulum.parse(check_shift.dt_obj)
            if check_shift.dt_obj > shift:
                logger.warning(
                    f"{shift.format('DD MMM HHmm')} not found on rota, {check_shift.dt_obj} > {shift}"
                )
                skipped_shifts.append(shift)
                break
            if check_shift.dt_obj == shift and check_shift.type in [
                "(Duty Room)",
                "(Hours of Need)",
                "(Peer to Peer)",
            ]:
                # print(
                #     f"Matched shift {shift.format('DD MMM HHmm')} shift_id: {check_shift.shift_id}"
                # )
                expected_shifts.append(check_shift)
                break
    return expected_shifts, skipped_shifts


def verify_shify_ready_for_signup(
    volunteer: Volunteer, expected_shifts: List[RotaBro]
) -> Tuple[RotaBro, RotaBro]:
    ready_to_sign_shifts = []
    blocked_shifts = []
    for shift in expected_shifts:
        if shift.dt_obj < pendulum.today():
            continue
        if volunteer.name in shift.vols:
            logger.info(
                f"{volunteer.name} already signed up for {shift.date.format('DD MMM HHmm')}"
            )
        elif "[sign up]" not in shift.vols:
            logger.info(
                f"No room for {volunteer.name} in {shift.date.format('DD MMM HHmm')}, already signed: {shift.vols}"
            )
            blocked_shifts.append(shift)
        else:
            ready_to_sign_shifts.append(shift)
    return ready_to_sign_shifts, blocked_shifts


def get_vol_by_name(s, name: str) -> Volunteer:
    vols = get_active_volunteers()
    for vol in vols:
        if vol.name == name:
            return vol
    return None


def get_vol_by_id(s, id: str) -> Volunteer:
    vols = get_active_volunteers()
    for vol in vols:
        if vol.id == id:
            return vol


def get_vol_shifts_by_name(
    s, name: str, upcoming_only: bool = False
) -> List[pendulum.DateTime]:
    vol = get_vol_by_name(s, name)
    if not vol:
        logger.warning(f"Vol: {name} not found")
        return None
    return get_vol_shifts_by_id(s, vol.id, upcoming_only)


# TODO: if this is still used, the extends needs to be changed as Live changed their site
async def aget_vol_shifts_by_id(
    s, v_id: str, upcoming_only: bool = False, name: str = None
) -> List[pendulum.DateTime]:
    async with s.get(
        f"{ROTA_HOSTNAME}/directory/{v_id}",
    ) as res:
        assert res
        html = await res.read()
        soup = BeautifulSoup(html, "html.parser")

        results = soup.find_all("div", class_="directory_stats_rota")
        if not results:
            return
        shifts = []
        for res in results:
            shifts.extend(
                res.find_all(class_="stats_duty_complete")
            )  # needs to be changed to search for "img" only, no class needed, see adv_get_vol_shifts
        if not shifts:
            return

        # unnecessary line now.. remaking list again later
        shift_titles = [name if name else v_id]
        counted_shifts = ["duty", "tutored", "hours of need", "peer to peer"]

        # TESTING - trying to only count tutored shifts if they're a tutored vol, does this mess up counting somewhere else though#
        if "[T]" in name:
            counted_shifts = ["tutored"]
        else:
            counted_shifts = ["duty", "hours of need", "peer to peer"]
        # END TEST #

        for shift in shifts:
            shift_type = shift.parent.parent.p.string
            if not any(
                c in shift_type.lower() for c in counted_shifts
            ):  # Only count duty and tutored shifts
                continue
            shift_data = shift["title"].split(" to")[0].replace(" - ", "")
            dt_shift_data = pendulum.from_format(
                shift_data, "dddd DD MMMM YYYY [(from] HH:mm"
            )
            if upcoming_only and dt_shift_data < pendulum.today():
                continue
            shift_titles.append(dt_shift_data)

        # for some reason the shifts aren't always grabbed in order, so order them
        sorted_shifts = sorted(shift_titles[1:])
        final_list = [name if name else v_id] + sorted_shifts
        return final_list


def get_vol_shifts_by_id(
    s, v_id: str, upcoming_only: bool = False, name: str = None
) -> List[pendulum.DateTime]:
    res = s.get(
        f"{ROTA_HOSTNAME}/directory/{v_id}",
    )
    soup = BeautifulSoup(res.content, "html.parser")

    results = soup.find_all(class_="directory_stats_rota")
    if not results:
        return
    shifts = []
    for res in results:
        shifts.extend(res.find_all(class_="stats_duty_complete"))
    if not shifts:
        return
    # start array with vol name or id
    shift_titles = [name if name else v_id]
    # only count these shift types
    counted_shifts = ["duty", "tutored", "hours of need"]
    # fill array with dts of shifts
    for shift in shifts:
        if not any(
            c in shift.parent.parent.p.string.lower() for c in counted_shifts
        ):  # element contains shift type (Duty Room, Tutored, Leader etc)
            continue
        shift_data = shift["title"].split(" to")[0].replace(" - ", "")
        dt_shift_data = pendulum.from_format(
            shift_data, "dddd DD MMMM YYYY [(from] HH:mm"
        )
        # if upcoming flag, skip past shifts
        if upcoming_only and dt_shift_data < pendulum.today():
            continue
        shift_titles.append(dt_shift_data)

    return shift_titles


async def aget_all_vol_shifts_by_id(
    vols: List[Volunteer], new_output: bool = False, no_gui: bool = False
) -> List[pendulum.DateTime]:
    auth = aiohttp.BasicAuth(
        login=login_info["username"], password=login_info["password"], encoding="utf-8"
    )
    async with aiohttp.ClientSession(
        auth=auth, connector=aiohttp.TCPConnector(limit=7)
    ) as session:
        tasks = []
        res = []
        i = 0
        for vol in vols:
            if new_output:
                tasks.append(
                    asyncio.create_task(
                        adv_get_vol_shifts(session, vol_id=vol.id, vol_name=vol.name)
                    )
                )
            else:
                tasks.append(
                    asyncio.create_task(
                        aget_vol_shifts_by_id(session, vol.id, name=vol.name)
                    )
                )
        for coro in asyncio.as_completed(tasks):
            res.append(await coro)
            if not no_gui:
                sg.one_line_progress_meter("Downloading data...", i + 1, len(tasks))
            i += 1
        return res


def get_active_volunteers() -> List[Volunteer]:
    res = requests.get(
        f"{ROTA_HOSTNAME}/rota/sign_up_bin",
        headers={"Authorization": f"APIKEY {APIKEY}"},
    )
    soup = BeautifulSoup(res.content, "html.parser")
    results = soup.find_all(class_="dialog-remote")
    vols = []
    for vol in results:
        vol_id = vol["href"].split("/")[-1]
        vol_name = vol["title"]
        if vol_name.strip() == "Week Number":
            continue
        vols.append(Volunteer(id=vol_id, name=vol_name, rota=[]))

    return vols


def post_all_sign_ups(session, volunteer: Volunteer, shifts: List[RotaBro]):
    logger.info(f"Signing up for {len(shifts)} shifts...")
    for shift in shifts:
        form_data = {"vol_id": volunteer.id, "shift_id": shift.shift_id}
        logger.info(f"Signing for: {shift.dt_obj.format('DD MMM YY @ HHmm')}")
        post_sign_up(session, form_data)


async def apost_all_sign_ups(
    _session, volunteer: Volunteer, shifts: List[RotaBro]
) -> List[pendulum.DateTime]:
    auth = aiohttp.BasicAuth(
        login=login_info["username"], password=login_info["password"], encoding="utf-8"
    )
    async with aiohttp.ClientSession(
        auth=auth, connector=aiohttp.TCPConnector(limit=5)
    ) as session:
        tasks = []
        res = []
        i = 0
        for shift in shifts:
            form_data = {"vol_id": volunteer.id, "shift_id": shift.shift_id}
            readable_dt = shift.dt_obj.format("DD MMM YY @ HHmm")
            logger.info(f"Signing {volunteer.name}: {readable_dt}")
            tasks.append(
                asyncio.create_task(apost_sign_up(session, form_data, readable_dt))
            )
        for coro in asyncio.as_completed(tasks):
            res.append(await coro)
            sg.one_line_progress_meter("Signing Up", i + 1, len(tasks))
            i += 1
        logger.info(f"Pushed {volunteer.name}'s rota to site")
    #     responses = await asyncio.gather(*tasks)
    # print(responses)
    success_signs = [
        pendulum.from_format(x, "DD MMM YY [@] HHmm") for x in res if x[:3] != "ERR"
    ]
    fail_signs = [", ".join(x) for x in res if x[:3] == "ERR"]
    if fail_signs:
        sg.Popup(
            f"{len(success_signs)} sign ups made for {volunteer.name}, {len(shifts) - len(success_signs)} errors:\n {fail_signs}",
            keep_on_top=True,
        )
        return success_signs
    sg.Popup(
        f"{len(success_signs)} sign ups made for {volunteer.name}, {len(shifts) - len(success_signs)} with no errors\n",
        keep_on_top=True,
    )
    return success_signs


def remove_all_sign_ups(
    session,
    volunteer: Volunteer,
    date_start: pendulum.DateTime,
    date_end: pendulum.DateTime,
    shift_types: List[str] = None,
) -> int:
    vol_shift_ids_to_remove = []
    # rota = build_rota_data(session, date_start, date_end)

    # If this breaks put back in ^
    rota = asyncio.run(abuild_rota_data(session, date_start, date_end))
    for shift in rota:
        for v, vsid in zip(shift.vols, shift.vol_shift_id):
            if v == volunteer.name:
                if shift_types:
                    if shift.type not in shift_types:
                        continue
                vol_shift_ids_to_remove.append(vsid)
                logger.info(f"Removing from: {shift.date.format('DD MMM YY @ HHmm')}")
    if (
        sg.PopupOK(
            f"Remove {volunteer.name} from {len(vol_shift_ids_to_remove)} shifts"
        )
        != "OK"
    ):
        return
    for i, id in enumerate(vol_shift_ids_to_remove):
        if not sg.one_line_progress_meter(
            "Removing sign up...", i + 1, len(vol_shift_ids_to_remove)
        ):
            break
        post_remove_sign_up(session, id)
    return len(vol_shift_ids_to_remove)


def post_sign_up(session, form_data):  # form_data: vol_id, shift_id
    data = {"volunteer_shift[volunteer_id]": f"{form_data['vol_id']}"}
    r = session.post(f"{ROTA_HOSTNAME}/rota/signup/{form_data['shift_id']}", data)
    logger.info(f"Sign status: {r.ok}")


async def apost_sign_up(
    session, form_data, readable_dt: str
):  # form_data: vol_id, shift_id
    data = {"volunteer_shift[volunteer_id]": f"{form_data['vol_id']}"}
    async with session.post(
        f"{ROTA_HOSTNAME}/rota/signup/{form_data['shift_id']}", data=data
    ) as response:
        if response.status != 200:
            return f"ERR {readable_dt} Status: {response.status}"
        await response.read()
    return readable_dt
    # logger.info(f"in get {form_data}")
    # async with session.get(
    #     f"https://reqres.in/api/products/{form_data}"
    # ) as response:
    #     await asyncio.sleep(1)
    #     assert response.status == 200
    #     r = await response.read()
    #     logger.info(f"received {form_data} res")
    #     return r


def post_remove_sign_up(session, vol_shift_id):  # needs vol-shift-id
    r = session.post(f"{ROTA_HOSTNAME}/rota/pull_out/{vol_shift_id}")


def make_dt_obj(date: pendulum.Date, time: str) -> str:  # 22:00 - 01:00
    hour, minute = time.split(" -")[0].split(":")
    return pendulum.datetime(
        date.year, date.month, date.day, int(hour), int(minute)
    ).__str__()


async def abuild_rota_data(
    cookies=None,
    start_date: pendulum.DateTime = None,
    end_date: pendulum.DateTime = None,
    queue=None,
):
    if not start_date and not end_date:
        start_date = pendulum.today()
        end_date = start_date.add(weeks=4)
    if not end_date:
        end_date = start_date.add(weeks=4)
    if not cookies:
        logger.info("No Cookie login")
        auth = aiohttp.BasicAuth(
            login=login_info["username"],
            password=login_info["password"],
            encoding="utf-8",
        )
    else:
        auth = None
    logger.info(
        f"Building rota from {start_date.to_date_string()} to {end_date.to_date_string()}.."
    )

    rota_period = end_date - start_date
    rota_cycles = math.ceil(rota_period.days / 28)
    tasks = []
    j = 0
    if start_date == end_date:
        rota_cycles = 1
    async with aiohttp.ClientSession(
        auth=auth, cookies=cookies, connector=aiohttp.TCPConnector(limit=5)
    ) as session:
        for i in range(rota_cycles):
            if i == 0:
                tasks.append(
                    asyncio.create_task(
                        aget_rota(
                            session,
                            start_date.add(weeks=i * 4),
                            rota=None,
                            end=end_date,
                        )
                    )
                )
            else:  # subsequent rota start dates need to be start of week, or part of that week will get skipped
                tasks.append(
                    asyncio.create_task(
                        aget_rota(
                            session,
                            start_date.add(weeks=i * 4).start_of("week"),
                            rota=None,
                            end=end_date,
                        )
                    )
                )
        res = await asyncio.gather(*tasks)
    if res == [None]:
        return
    rota = [
        k for l in res for k in l
    ]  # List[List[shift]]->List[shift]    eg. [[shift,shift],[shift,shift,shift]] -> [shift, shift, shift, shift, shift]
    if queue:
        # with open("test_rota.json", "w") as f:
        #     for shift in rota:
        #         f.write(f"{shift.toJSON()},")
        queue.put(rota)
    logger.info("Rota build complete")
    return rota


# TODO: Could be replaced with the real API
async def aget_rota(session, date: pendulum.DateTime, rota=None, end=None):
    if not rota:
        rota = []
    start_date = date.start_of("week")
    if not end:
        end = start_date.add(days=27)
    end_date = min(start_date.add(days=27), end)
    # period = pendulum.period(start_date, end_date)
    period = end_date - start_date
    async with session.get(
        f"{ROTA_HOSTNAME}/rota/for/{date.year}-{date.month}-{date.day}/month",
        allow_redirects=False,
    ) as response:  # TypeError: post() takes 2 positional arguments but 3 were given
        logger.info(
            f"Fetching rota for {start_date.to_date_string()} to {end_date.to_date_string()}.."
        )
        assert response
        html = await response.read()

    # print(res.status_code)

    soup = BeautifulSoup(html, "html.parser")

    for dt in period.range("days"):
        if dt < date:
            continue
        if end is not None and dt > end:
            break
        day = soup.find("td", id=f"day_{dt.format('YYYY_MM_DD')}")
        if not day:
            return
        shifts = day.find_all("div", class_="rota_item")

        for i in range(0, len(shifts), 2):
            time_element = shifts[i].find("div", class_="rota_item_time")
            time = time_element.text.strip()
            dt_obj = make_dt_obj(dt, time)
            detail = shifts[i].find("div", class_="rota_item_detail")
            persons = [person.text.strip() for person in detail.find_all("li")]
            shift_type = detail.find("div", class_="rota_item_time_name").text.strip()
            shift_id = shifts[i + 1]["data-shift-id"]

            vol_shift_id = shifts[i].find_all("li", class_="rota_shift_filled")
            vol_shift_id = [vs["data-volunteer-shift-id"] for vs in vol_shift_id]

            rota.append(
                RotaBro(
                    shift_id=shift_id,
                    date=dt.format("DD MMM YY"),
                    time=time,
                    type=shift_type,
                    vols=persons,
                    vol_shift_id=vol_shift_id,
                    dt_obj=dt_obj,
                )
            )
    return rota


def get_rota(session, date: pendulum.DateTime, rota=None, end=None):
    if not rota:
        rota = []
    start_date = date.start_of("week")
    if not end:
        end = start_date.add(days=27)
    end_date = min(start_date.add(days=27), end)
    logger.info(
        f"Fetching rota for {start_date.to_date_string()} to {end_date.to_date_string()}.."
    )
    # period = pendulum.period(start_date, end_date)
    period = end_date - start_date
    res = session.get(
        f"{ROTA_HOSTNAME}/rota/for/{date.year}-{date.month}-{date.day}/month",
    )

    # print(res.status_code)

    soup = BeautifulSoup(res.content, "html.parser")

    for dt in period.range("days"):
        if dt < date:
            continue
        if end is not None and dt > end:
            break
        day = soup.find("td", id=f"day_{dt.format('YYYY_MM_DD')}")
        shifts = day.find_all("div", class_="rota_item")

        for i in range(0, len(shifts), 2):
            time_element = shifts[i].find("div", class_="rota_item_time")
            time = time_element.text.strip()
            dt_obj = make_dt_obj(dt, time)
            detail = shifts[i].find("div", class_="rota_item_detail")
            persons = [person.text.strip() for person in detail.find_all("li")]
            shift_type = detail.find("div", class_="rota_item_time_name").text.strip()
            shift_id = shifts[i + 1]["data-shift-id"]

            vol_shift_id = shifts[i].find_all("li", class_="rota_shift_filled")
            vol_shift_id = [vs["data-volunteer-shift-id"] for vs in vol_shift_id]

            rota.append(
                RotaBro(
                    shift_id=shift_id,
                    date=dt.format("DD MMM"),
                    time=time,
                    type=shift_type,
                    vols=persons,
                    vol_shift_id=vol_shift_id,
                    dt_obj=dt_obj,
                )
            )
    return rota


async def acreate_multiple_shifts(
    _session, time_list: List[pendulum.DateTime], shift_types: List[str]
):
    auth = aiohttp.BasicAuth(
        login=login_info["username"], password=login_info["password"], encoding="utf-8"
    )
    if shift_types == ["Both"]:
        shift_types = ["(Duty Room)", "(Leader)", "(Hours of Need)"]
    async with aiohttp.ClientSession(
        auth=auth, connector=aiohttp.TCPConnector(limit=5)
    ) as session:
        tasks = []
        res = []
        i = 0
        for times in time_list:
            for shift_type in shift_types:
                tasks.append(
                    asyncio.create_task(
                        acreate_shift(
                            session,
                            start_time=times[0],
                            end_time=times[1],
                            shift_type=shift_type,
                        )
                    )
                )
        for coro in asyncio.as_completed(tasks):
            res.append(await coro)
            sg.one_line_progress_meter("Deleting Shifts", i + 1, len(tasks))
            i += 1
    #     responses = await asyncio.gather(*tasks)
    # print(responses)
    # sg.Popup(f"Shifts added: {responses}")
    sg.Popup(f"Shifts added: {res}")
    return


async def acreate_shift(
    session,
    start_time: pendulum.DateTime,
    end_time: pendulum.DateTime,
    shift_type: str,
) -> str:
    start_str = start_time.format(
        "YYYY-MM-DD[T]HH:mm:ss[Z]"
    )  # time format: 2021-12-20T03:00:00Z
    end_str = end_time.format("YYYY-MM-DD[T]HH:mm:ss[Z]")
    logger.info(
        f"Creating {shift_type} shift on {start_time.format('DD.MM.YY @ HHmm')}-{end_time.format('HHmm')}.."
    )
    form_data = {
        "shift[rota_id]": "",
        "shift[start_datetime]": start_str,
        "shift[all_day]": "0",
        "shift[end_datetime]": end_str,
        "shift[minimum_volunteers]": "",
        "shift[maximum_volunteers]": "",
        "shift[points]": "",
        "shift[recurrence_option]": "",
        "commit": "Create",
    }

    if shift_type.lower() == "(duty)" or shift_type.lower() == "(duty room)":
        form_data["shift[rota_id]"] = "204"  # 8766 = christmas  # 407 = tutored
        form_data["shift[minimum_volunteers]"] = "2"
        form_data["shift[maximum_volunteers]"] = "2"
    elif shift_type.lower() == "(leader)":
        form_data["shift[rota_id]"] = "209"
        form_data["shift[minimum_volunteers]"] = "1"
        form_data["shift[maximum_volunteers]"] = "1"
    elif shift_type.lower() == "(tutored)":
        form_data["shift[rota_id]"] = "407"
        form_data["shift[minimum_volunteers]"] = "1"
        form_data["shift[maximum_volunteers]"] = "1"
        form_data["shift[recurrence_option]"] = "weekly"
    elif shift_type.lower() == "(hours of need)":
        form_data["shift[rota_id]"] = "11017"
        form_data["shift[minimum_volunteers]"] = "2"
        form_data["shift[maximum_volunteers]"] = "2"
    else:
        logger.warning(f"Shift type error: {shift_type}")
        raise TypeError

    async with session.post(
        "{ROTA_HOSTNAME}/admin/shifts", data=form_data
    ) as response:  # TypeError: post() takes 2 positional arguments but 3 were given
        assert response
        tx = await response.read()
        with open("htmlres.html", "wb+") as f:
            f.write(tx)
        confirm = f"{shift_type} - {start_time.format('DD.MM.YY @ HHmm')}"
    return confirm


def create_multiple_shifts(
    session,
    time_list: List[List[pendulum.DateTime]],
    shift_types: List[str],
    window=None,
):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # if window:
    #     window.write_event_value("-CREATION STARTED-", "")
    for i, times in enumerate(time_list):
        if not sg.one_line_progress_meter("Creating Shifts", i + 1, len(time_list)):
            break
        create_shift(
            session, start_time=times[0], end_time=times[1], shift_types=shift_types
        )
        # if window:
        #     window.write_event_value("-CREATION PROGRESS-", f"Creating shifts... {times[0].format('DD.MM.YY')}")
        # time.sleep(2)
        # window["-ADD TEXT-"].update(f"Creating shifts... {times[0].format('DD.MM.YY')}")
    # if window:
    #     window.write_event_value("-CREATION FINISHED-", "")
    return


def create_shift(
    session,
    start_time: pendulum.DateTime,
    end_time: pendulum.DateTime,
    shift_types: List[str],
):
    start_str = start_time.format(
        "YYYY-MM-DD[T]HH:mm:ss[Z]"
    )  # time format: 2021-12-20T03:00:00Z
    end_str = end_time.format("YYYY-MM-DD[T]HH:mm:ss[Z]")
    logger.info(
        f"Creating {shift_types} shift on {start_time.format('DD.MM.YY @ HHmm')}-{end_time.format('HHmm')}.."
    )
    form_data = {
        "shift[rota_id]": "",
        "shift[start_datetime]": start_str,
        "shift[all_day]": "0",
        "shift[end_datetime]": end_str,
        "shift[minimum_volunteers]": "",
        "shift[maximum_volunteers]": "",
        "shift[points]": "",
        "shift[recurrence_option]": "",
        "commit": "Create",
    }
    # TODO Add Night shift when implemented?
    for shift_type in shift_types:
        if shift_type.lower() == "(duty)" or shift_type.lower() == "(duty room)":
            form_data["shift[rota_id"] = "204"
            form_data["shift[minimum_volunteers]"] = "2"
            form_data["shift[maximum_volunteers]"] = "2"
        elif shift_type.lower() == "(leader)":
            form_data["shift[rota_id"] = "209"
            form_data["shift[minimum_volunteers]"] = "1"
            form_data["shift[maximum_volunteers]"] = "1"
        elif shift_type.lower() == "(hours of need)":
            logger.info("add hours of need form data")
            pass
        else:
            logger.warning(f"Shift type error: {shift_type}")
            raise TypeError
        r = session.post(f"{ROTA_HOSTNAME}/admin/shifts", form_data)
        logger.info(f"{shift_type} @ {start_time} , post = {r.ok}")
        return


async def adelete_all_shifts(
    _session,
    start_date: pendulum.DateTime,
    end_date: pendulum.DateTime,
    types: List[str],
    empty_only: bool,
):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logger.info("aDeleting shifts")
    rota = await abuild_rota_data(None, start_date, end_date)
    # print(rota)
    auth = aiohttp.BasicAuth(
        login=login_info["username"], password=login_info["password"], encoding="utf-8"
    )
    shifts_to_delete = []
    for shift in rota:
        shift.vols = [vol for vol in shift.vols if vol != "[sign up]"]
        if shift.type in types:
            if not empty_only or (empty_only and not shift.vols):
                shifts_to_delete.append(shift)

    if (
        sg.PopupOKCancel(
            f"Delete {len(shifts_to_delete)} shifts?\n\n{'ALL' if not empty_only else 'Empty'}, {types} shifts from:\n{start_date.format('dddd DD MMM YY')} to {end_date.format('dddd DD MMM YY')}"
        )
        != "OK"
    ):
        return
    async with aiohttp.ClientSession(
        auth=auth, connector=aiohttp.TCPConnector(limit=5)
    ) as session:
        tasks = []
        res = []
        i = 0
        for sh in shifts_to_delete:
            tasks.append(asyncio.create_task(adelete_shift(session, sh.shift_id)))
        for coro in asyncio.as_completed(tasks):
            res.append(await coro)
            sg.one_line_progress_meter("Deleting Shifts", i + 1, len(tasks))
            i += 1
        # r = await asyncio.gather(*tasks)
    # print(f"{len(r)} shifts deleted")
    if sys.platform == "win32":
        sg.Popup(f"{len(res)} shifts deleted")
    return


async def adelete_shift(session: aiohttp.ClientSession, shift_id: str) -> str:
    async with session.post(f"{ROTA_HOSTNAME}/rota/delete/{shift_id}") as response:
        assert response
        await response.read()
    return f"{shift_id} deleted"


async def close_empty_shifts(
    start_date: pendulum.DateTime, end_date: pendulum.DateTime
):
    logger.info("Closing shifts...")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    rota = await abuild_rota_data(None, start_date, end_date)

    shifts_to_close = []
    # Select completely empty shifts
    for i, shift in enumerate(rota):
        shift.vols = [vol for vol in shift.vols if vol != "[sign up]"]
        if (
            shift.type in ["(Duty Room)", "(Hours of Need)", "(Leader)"]
            and not shift.vols
        ):
            # If shifts_to_close is empty and we're checking a Leader shift, do not close it as the main shift is not empty
            if shift.type == "(Leader)" and not shifts_to_close:
                continue
            if shift.type != "(Leader)":
                shifts_to_close.append(shift)
            # only close the leader shift if the main (duty/need) is also empty
            # The rota is ordered such that the leader shift appears after the main shift
            elif (
                shift.type == "(Leader)" and shifts_to_close[-1].dt_obj == shift.dt_obj
            ):
                shifts_to_close.append(shift)

    logger.info(f"Found {len(shifts_to_close)} shifts to close")

    # Note: the popup box causes error in linux only:
    # XIO:  fatal IO error 2 (No such file or directory) on X server ":0" ... Aborted (core dumped)
    if sys.platform == "win32":
        if (
            sg.PopupOKCancel(
                f"Close {len(shifts_to_close)} shifts?\n\n Empty shifts from:\n{start_date.format('dddd DD MMM YY')} to {end_date.format('dddd DD MMM YY')}"
            )
            != "OK"
        ):
            return
    async with aiohttp.ClientSession(
        headers={"Authorization": f"APIKEY {APIKEY}"},
        connector=aiohttp.TCPConnector(limit=5),
    ) as session:
        tasks = []
        res = []
        i = 0
        for sh in shifts_to_close:
            tasks.append(asyncio.create_task(close_shift(session, sh.shift_id)))
        for coro in asyncio.as_completed(tasks):
            res.append(await coro)
            # Note: the one_line_progress_meter causes error in linux only:
            # XIO:  fatal IO error 2 (No such file or directory) on X server ":0" ... Aborted (core dumped)
            if sys.platform == "win32":
                sg.one_line_progress_meter("Closing Shifts", i + 1, len(tasks))
            i += 1
    logger.info(f"Closed {len(shifts_to_close)} shifts")
    if sys.platform == "win32":
        sg.Popup(f"{len(shifts_to_close)} shifts closed")


async def close_shift(session: aiohttp.ClientSession, shift_id: str) -> str:
    async with session.post(f"{ROTA_HOSTNAME}/rota/close/{shift_id}") as response:
        await response.read()
    return shift_id


def delete_all_shifts(
    session,
    start_date: pendulum.datetime,
    end_date: pendulum.DateTime,
    types: List[str],
    empty_only: bool,
):
    # rota = build_rota_data(session, start_date, end_date)
    rota = asyncio.run(abuild_rota_data(session, start_date, end_date))
    shifts_to_delete = []
    for shift in rota:
        shift.vols = [vol for vol in shift.vols if shift.vols == "[sign up]"]
        if shift.type in types:
            logger.info(f"type: {shift.type}, vols: {shift.vols}")
            if not empty_only or (empty_only and not shift.vols):
                shifts_to_delete.append(shift.shift_id)
    logger.info("Deleting shifts..")
    for i, id in enumerate(shifts_to_delete):
        if not sg.one_line_progress_meter(
            "Deleting Shifts", i + 1, len(shifts_to_delete), orientation="h"
        ):
            break
        delete_shift(session, id)
    logger.info(f"{len(shifts_to_delete)} shifts deleted")


def delete_shift(session, shift_id):
    # session.requests.Request("POST", f"{ROTA_HOSTNAME}/rota/delete/{shift_id}")
    r = session.post(f"{ROTA_HOSTNAME}/rota/delete/{shift_id}")
    return
    ...  # post to {ROTA_HOSTNAME}/rota/delete/57940346  <div id="shift_57940346" class="rota_item ..." data-shift-id="57940346"


# vol id directory scrape, return list of [volname, Shift1, Shift2...], sorted by date
async def adv_get_vol_shifts(s: requests.Session, vol_id: str, vol_name: str):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    async with s.get(
        f"{ROTA_HOSTNAME}/directory/{vol_id}",
    ) as res:
        assert res
        html = await res.read()
        soup = BeautifulSoup(html, "html.parser")

        results = soup.find_all(
            class_="directory_stats_rota"
        )  # Contains the star section, can be multiple sections if vol has done multiple shift types
        if not results:
            logger.info(f"No shifts found for {vol_name}")
            return [vol_name if vol_name else vol_id]
        shifts = []

        # check each shift, each star "img" is one shift, contains the date/time data in "title"
        for res in results:
            shifts.extend(res.find_all("img"))
        if not shifts:
            logger.info(f"No shifts found for {vol_name}")
            return [vol_name if vol_name else vol_id]

        shift_titles = []
        for shift in shifts:
            shift_type = shift.parent.parent.p.string.strip()
            shift_data = shift["title"].split(" to")[0]
            if " - " in shift_data:
                shift_data = shift_data.split(" - ")[1]
            try:
                dt_shift_data = pendulum.from_format(
                    shift_data, "dddd DD MMMM YYYY [(from] HH:mm"
                )
            except ValueError:
                logger.error(f"Exiting; Pendulum could not parse: {shift_data}")
                quit()

            shift_titles.append(Shift(type=shift_type, dt_obj=dt_shift_data))
        # for some reason the shifts aren't always grabbed in order, so order them
        sorted_shifts = sorted(shift_titles, key=lambda x: x.dt_obj)
        final_list = [vol_name if vol_name else vol_id] + sorted_shifts
        return final_list


# shift_list looks like ["Vol 123", Shift1, Shift2,...], turn it into dict: {name: "Vol 123", duty: [DT1, DT2...], need: [DT1, DT2...], embedded: [DT1...]}
def shifts_list_to_dict(shift_list) -> dict:
    out_dict = {"name": shift_list[0]}
    for shift in shift_list[1:]:
        if shift.type not in out_dict:
            out_dict[shift.type] = [shift.dt_obj]
        else:
            out_dict[shift.type].append(shift.dt_obj)
    return out_dict


def make_new_vol_report(vols: List[Volunteer], no_gui=False):
    """Creates text file new_vol_report.txt with list of all Tutored and Probationers, detailing if they need to book more tutored shifts, or be passed to next stage"""

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Filter for only [Prb] and [T]
    vols = [vol for vol in vols if "[Prb]" in vol.name or "[T]" in vol.name]

    # This isn't ordered?
    vol_all_shifts = asyncio.run(
        aget_all_vol_shifts_by_id(vols, new_output=True, no_gui=no_gui)
    )  # List of lists [[Vol1: str, shift1: dt, shift2: dt...], [Vol2: str, shift1:dt, shift2:dt...]]

    vol_all_shifts.sort(key=lambda x: x[0])

    # unused
    vol_dict_list = []
    for vol in vol_all_shifts:
        vol_dict_list.append(shifts_list_to_dict(vol))

    out_prb = []
    out_tutored = []
    no_shifts_count = 0  # count how many entries have no shift data, if this is high then possibly Live's isn't loading properly - don't send empty report!

    # Iterate through each volunteer
    for get_shifts in vol_all_shifts:
        shift_complete_counter = 0
        shift_upcoming_counter = 0
        embedded_counter = 0
        latest_shift = None
        long_shift_delay = False
        msg = ""
        if not get_shifts:
            continue

        # For Tutored vols
        if "[T]" in get_shifts[0]:
            if len(get_shifts) < 2:
                logger.info(f"{get_shifts[0]} has no shifts")
                out_tutored.append(f"{get_shifts[0]} - has no shifts *ACTION REQUIRED*")
                no_shifts_count += 1
                continue
            for sh in get_shifts[1:]:
                if sh.type != "Tutored":
                    continue
                if sh.dt_obj <= pendulum.today():
                    shift_complete_counter += 1
                    latest_shift = sh.dt_obj
                else:
                    shift_upcoming_counter += 1
            if latest_shift:
                if latest_shift < pendulum.today().subtract(days=15):
                    long_shift_delay = True
            if shift_complete_counter + shift_upcoming_counter < 7:
                msg = f"{get_shifts[0]} - Shifts complete: {shift_complete_counter}, Upcoming shifts: {shift_upcoming_counter} * ACTION REQUIRED: Book more tutored shifts *"
            elif shift_upcoming_counter == 0:
                msg = f"{get_shifts[0]} - Shifts complete: {shift_complete_counter}, Upcoming shifts: {shift_upcoming_counter} * ACTION REQUIRED: Pass tutored / Book more shifts *"
            else:
                msg = f"{get_shifts[0]} - Shifts complete: {shift_complete_counter}, Upcoming shifts: {shift_upcoming_counter}"
            if long_shift_delay:
                msg += f" * {latest_shift.diff(pendulum.today()).in_days()} days since last shift on {latest_shift.format('DD.MM.YY')} *"
            out_tutored.append(msg)

        # For Probationers
        elif "[Prb]" in get_shifts[0]:
            if len(get_shifts) < 2:
                logger.info(f"{get_shifts[0]} has no shifts")
                out_prb.append(f"{get_shifts[0]} - has no shifts *ACTION REQUIRED*")
                no_shifts_count += 1
                continue
            for sh in get_shifts[1:]:
                if (
                    sh.type.lower() == "embedded development"
                    and sh.dt_obj <= pendulum.today()
                ):
                    embedded_counter += 1
                    continue
                if sh.type.lower() not in [
                    "duty room",
                    "hours of need",
                    "peer to peer",
                ]:
                    continue
                if sh.dt_obj <= pendulum.today():
                    shift_complete_counter += 1
                    latest_shift = sh.dt_obj
                else:
                    shift_upcoming_counter += 1
            if latest_shift:
                if latest_shift < pendulum.today().subtract(days=15):
                    long_shift_delay = True

            if shift_complete_counter >= 20 and embedded_counter >= 4:
                msg = f"{get_shifts[0]} - Solo shifts complete: {shift_complete_counter}, Upcoming shifts: {shift_upcoming_counter}, Embedding: {embedded_counter} * ACTION REQUIRED: Pass probation! *"
            elif shift_upcoming_counter == 0:
                msg = f"{get_shifts[0]} - Solo shifts complete: {shift_complete_counter}, Upcoming shifts: {shift_upcoming_counter}, Embedding: {embedded_counter} * ACTION REQUIRED: Book more shifts *"
            else:
                msg = f"{get_shifts[0]} - Solo shifts complete: {shift_complete_counter}, Upcoming shifts: {shift_upcoming_counter}, Embedding: {embedded_counter}"
            if long_shift_delay:
                msg += f" * {latest_shift.diff(pendulum.today()).in_days()} days since last shift on {latest_shift.format('DD.MM.YY')} *"
            out_prb.append(msg)

    # Write the text file
    with open(
        f"new_vol_reports/new_vol_report_{pendulum.today().format('DD_MM_YY')}.txt",
        "w+",
    ) as f:
        if no_shifts_count >= len(vol_all_shifts) / 2:
            f.write(
                f"Error collecting data for New Volunteer Report {pendulum.today().format('DD.MM.YY')}"
            )
            logger.warning("New volunteer report error - not enough shift data found")
        else:
            f.write(f"New Volunteer Report {pendulum.today().format('DD.MM.YY')}\n\n")
            if out_tutored:
                f.write(f"TUTORED ({len(out_tutored)}):\n\n")
                for line in out_tutored:
                    f.write(f"{line}\n")
                f.write("\n")
            else:
                f.write("No [T] currently on Directory\n\n")
            f.write(f"PROBATIONERS ({len(out_prb)}):\n\n")
            for line in out_prb:
                f.write(f"{line}\n")
            f.write(
                "\nNote: Passing probation requires 20 solo shifts + 4 Embedding sessions"
            )
            logger.info("New volunteer report created")
    if no_gui:
        return
    if sys.platform == "linux":
        subprocess.run(
            [
                "xed",
                f"new_vol_reports/new_vol_report_{pendulum.today().format('DD_MM_YY')}.txt",
            ]
        )
    else:
        subprocess.run(
            [
                "notepad",
                f"new_vol_reports/new_vol_report_{pendulum.today().format('DD_MM_YY')}.txt",
            ]
        )


if __name__ == "__main__":
    pass
