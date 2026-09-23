# TODO Add all functions here that are used in email_other_reports.pyw

import pendulum
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List
from config import exempt_list


@dataclass
class VolChecks:
    name: str
    join_date: pendulum.DateTime
    expiry_date: pendulum.DateTime
    upcoming_anni: int = None
    email: str = None
    days_inactive: str = None
    day_shifts: str = None
    night_shifts: str = None
    pvc_shifts: str = None
    foodbank_shifts: str = None
    total_shifts: str = None
    eight_week_msg: str = None


@dataclass
class PreppedEmail:
    subject: str
    message: str
    recipient_list: List[str]


# unused currently
@dataclass
class ReportsToSend:
    latest_annual_anniversary_report: bool = False
    latest_monthly_anniversary_report: bool = False
    latest_dbs_report: bool = False
    latest_tutored_report: bool = False
    latest_probationer_report: bool = False
    latest_full_vol_report: bool = False
    latest_two_monthly_report: bool = False


def load_logs(log_path: Path) -> dict:
    with open(log_path) as f:
        return json.load(f)


def save_logs(logs: dict):
    with open("logs.json", "w") as f:
        json.dump(logs, f, indent=4)


def load_rota() -> dict:
    with open("vol_rotas.json") as f:
        return json.load(f)


# Creates email body for 8 week individual email to all members
def create_eight_week_email_message(vol: VolChecks) -> str:
    msg = f"Dear {vol.name},\n\nThis is an automatically generated email. In the last 8 week period you have completed the following number of shifts:\n\n"
    msg += f"{vol.name} - {vol.total_shifts} total (Day: {vol.day_shifts}"
    if int(vol.pvc_shifts):
        msg += f", PVC: {vol.pvc_shifts}"
    if int(vol.foodbank_shifts):
        msg += f", F.Bank: {vol.foodbank_shifts}"
    if vol.name not in exempt_list or int(vol.night_shifts):
        msg += f", Hours of Need: {vol.night_shifts}"
    msg += f")"

    if int(vol.days_inactive):
        msg += f" Days inactive: {vol.days_inactive}"
    if int(vol.days_inactive) >= 10:
        msg += f"\n\nPlease do not worry about this message if you're on a break from shifts!"
    elif int(vol.total_shifts) <= 3 and vol.name not in exempt_list:
        msg += "\n\nCurrent expectation message."
    elif int(vol.night_shifts) == 0 and vol.name not in exempt_list:
        msg += "\n\nCurrent expectation message + alternative"
    if "[Prb]" in vol.name and vol.join_date.add(months=5) > pendulum.today():
        msg += "\n\nRecent Probationer message."
    msg += "\n\nIf you have any questions about this email, please reach out to ADMIN_EMAIL."

    return msg


def create_expiring_rota_email_message():
    vol_rota = load_rota()
    today = pendulum.today()
    expired_rotas = []
    expiring_rotas = []
    for vol in vol_rota:
        if not vol_rota[vol]["last_shift_scheduled"]:
            continue
        rota_end_date = pendulum.from_format(
            vol_rota[vol]["last_shift_scheduled"], "D MMM YYYY"
        )
        if (rota_end_date - today).days < 35:
            if (rota_end_date - today).days <= 0:
                expired_rotas.append(
                    f"{vol}'s rota has expired ({(today - rota_end_date).days} days ago)"
                )
            else:
                expiring_rotas.append(
                    f"{vol}'s rota expires in {(rota_end_date - today).days} days"
                )
    if not expiring_rotas and not expired_rotas:
        return ""

    if expiring_rotas:
        msg = f"Expiring rotas ({len(expiring_rotas)}):\n\n"
        for line in expiring_rotas:
            msg += f"{line}\n"
        msg += "\n"

    if expired_rotas:
        msg += f"Expired rotas ({len(expired_rotas)}):\n\n"
        for line in expired_rotas:
            msg += f"{line}\n"
    return msg


# unused currently?
def build_report_list(log_path: Path):
    make_report = ReportsToSend()
    logs = load_logs(log_path)
    latest_log_date = {k: pendulum.parse(v) for k, v in logs.items()}

    # Send whole yearly report for anniversaries once a year
    if (
        latest_log_date["latest_annual_anniversary_report"].year
        != pendulum.today().year
    ):
        make_report.latest_annual_anniversary_report = True
    # Send a monthly anniversary report once a month
    if (
        latest_log_date["latest_monthly_anniversary_report"].month
        != pendulum.today().month
        or latest_log_date["latest_monthly_anniversary_report"].year
        != pendulum.today().year
    ):
        make_report.latest_monthly_anniversary_report = True
    # Send DBS report once a month
    if (
        latest_log_date["latest_dbs_report"].month != pendulum.today().month
        or latest_log_date["latest_dbs_report"].year != pendulum.today().year
    ):
        make_report.latest_dbs_report = True
    # Send quarterly full vol report once a quarter
    if latest_log_date["latest_full_vol_report"] < pendulum.today().subtract(days=90):
        make_report.latest_full_vol_report = True
    # Send 8 week report every 8 weeks
    if latest_log_date["latest_two_monthly_report"].add(weeks=8) <= pendulum.today():
        make_report.latest_two_monthly_report = True
    # Send tutored/probationer report every week
    if latest_log_date["latest_tutored_report"].add(days=7) <= pendulum.today():
        make_report.latest_tutored_report = True

    return make_report


if __name__ == "__main__":
    print(create_expiring_rota_email_message())
