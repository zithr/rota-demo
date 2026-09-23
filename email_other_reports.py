import requests
import pendulum
from config import (
    APIKEY,
    ROTA_HOSTNAME,
    VERSION,
    login_info,
    email_login,
    recipient_list,
    nonlistening_vols,
    exempt_list,
)
from bs4 import BeautifulSoup
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List
from loguru import logger
from main import get_active_volunteers, make_new_vol_report
from email_report_funcs import (
    VolChecks,
    PreppedEmail,
    ReportsToSend,
    build_report_list,
    load_logs,
    save_logs,
    create_eight_week_email_message,
    create_expiring_rota_email_message,
)
from pathlib import Path

REPORT_LOG_PATH = Path(__file__).parent / "logs.json"


# return json of Live directory
def get_dir():
    url = f"{ROTA_HOSTNAME}/directory.json"
    r = requests.get(url, headers={"Authorization": f"APIKEY {APIKEY}"})
    # r.json()['volunteers'][0]['name'] # Live name including suffixes
    # r.json()['volunteers'][0]['volunteer_properties'][2]['friendly_name']['value'] # Sam Name no suffix
    return r.json()


# returns List[VolStats(name, days_inactive, day_shifts, night_shifts, pvc_shifts, total_shifts)]
def get_stats(
    vol_check_list: List[VolChecks],
    from_date: pendulum.DateTime,
    to_date: pendulum.DateTime,
) -> List[VolChecks]:
    start = from_date.format("YYYY-MM-DD")
    end = to_date.format("YYYY-MM-DD")

    # Current url example Sept 10 to Oct 10: {ROTA_HOSTNAME}/stats/number_of_shifts?utf8=%E2%9C%93&filter_volunteer_status=awake&filter_volunteer_role=all_roles&vol_inactivities=all_inactivities&filter_rotas=multiple&filter_rota_list%5B204%5D=1&filter_rota_list%5B11017%5D=1&filter_rota_list%5B725%5D=1&filter_rota_list%5B13089%5D=1&filter_rota_ungroup=1&start_date=2023-09-10&end_date=2023-10-10&filter_output_data=num_shifts&format=html&commit=Generate+Report
    url = f"{ROTA_HOSTNAME}/stats/number_of_shifts?utf8=%E2%9C%93&filter_volunteer_status=awake&filter_volunteer_role=all_roles&vol_inactivities=all_inactivities&filter_rotas=multiple&filter_rota_list[204]=1&filter_rota_list[11017]=1&filter_rota_list[725]=1&filter_rota_list[13089]=1&filter_rota_ungroup=1&start_date={start}&end_date={end}&filter_output_data=num_shifts&format=html&commit=Generate+Report"
    r = requests.get(url, headers={"Authorization": f"APIKEY {APIKEY}"})
    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    results = soup.find_all("tr")
    for i, res in enumerate(results):
        cell_text = res.get_text().strip()
        if not cell_text:
            continue
        split_row = cell_text.split("\n")
        if i == 0:
            assert split_row == [
                "Volunteer",
                "Days Inactive",
                "Number of Shifts",
            ], (
                f"Scraped table header {split_row} - does not match expected Table header - Volunteer, Days Inactive, Number of Shifts"
            )
        if i == 1:
            assert split_row == [
                "Duty Room",
                "Hours of Need",
                "PVC",
                "Foodbank",
                "Total",
            ], (
                f"Scraped table header {split_row} - does not match VolStats fields (not including name, days_inactive)"
            )
        if i > 1:
            if len(split_row) != 7:
                logger.warning(
                    f"Not enough rows found to split correctly in stats page, found: {split_row}"
                )
                continue
            for j, vol in enumerate(vol_check_list):
                if split_row[0].strip() != vol.name:
                    continue
                vol_check_list[j].days_inactive = split_row[1]
                vol_check_list[j].day_shifts = split_row[2]
                vol_check_list[j].night_shifts = split_row[3]
                vol_check_list[j].pvc_shifts = split_row[4]
                vol_check_list[j].foodbank_shifts = split_row[5]
                vol_check_list[j].total_shifts = split_row[6]
                break
    return vol_check_list


# returns filtered List[VolChecks] for vols that have x5 year anniversary this month
def monthly_anniversary_check(vols: List[VolChecks]) -> List[VolChecks]:
    out = []
    test_today = pendulum.date(2023, 12, 3)
    for vol in vols:
        months_service = (
            1
            + pendulum.today()
            .start_of("month")
            .diff(vol.join_date.start_of("month"))
            .in_months()
        )

        # Check if months of service is divisible by 12x5 exactly
        if (months_service / 12) % 5 == 0 and months_service:
            vol.upcoming_anni = int(months_service / 12)
            out.append(vol)
            # print(f"{vol.name} at {months_service/12} years!")
            # print(f"{vol.name} : {months_service/12} *** {vol.join_date.start_of('month')} TO {pendulum.today().start_of('month')} *** REAL: {vol.join_date.format('DD MMM YY')}")

    return out


# returns list of vols with x5 year anniversay in current calendar year
def annual_anniversary_check(vols: List[VolChecks]) -> List[VolChecks]:
    out = []
    for vol in vols:
        # if their year count is 4, 9, 14, 19... then they'll have a 5 year anniversay within 12 months
        months_service = (
            pendulum.today()
            .start_of("month")
            .diff(vol.join_date.start_of("month"))
            .in_months()
        )
        years_service = months_service / 12

        # if current month is their anniversary month
        if years_service and (years_service / 5).is_integer():
            vol.upcoming_anni = int(years_service)
            out.append(vol)
            continue

        # otherwise
        if ((months_service // 12) + 1) % 5 == 0:
            # don't inclue vols whose anniversaries are next calendar year
            if vol.join_date.month < pendulum.today().month:
                continue
            vol.upcoming_anni = int((months_service // 12) + 1)
            out.append(vol)
    return sorted(out, key=lambda x: x.join_date.month)


# helper function to make email body easier to write
def annual_anniversary_msg(vols: List[VolChecks]) -> List[str]:
    msg = []
    for vol in vols:
        if not vol.upcoming_anni:
            continue
        msg.append(
            f"{vol.name} - {vol.upcoming_anni} year anniversary in {vol.join_date.format('MMMM')} (Joined {vol.join_date.format('DD.MM.YYYY')})"
        )
    return msg


# returns list of vols with DBS expiring in next 70 days
def upcoming_dbs_expiry(vols: List[VolChecks]) -> List[VolChecks]:
    out = []
    for vol in vols:
        if not vol.expiry_date:
            out.append(vol)
            continue
        if vol.expiry_date < pendulum.today().add(days=70):
            out.append(vol)
    return out


# use API to build directory of vols, with their Sam Name, Join Date, DBS Expiry Date.
def build_vol_checks() -> List[VolChecks]:
    directory = get_dir()
    out = []
    for vol in directory["volunteers"]:
        # NEW skip any names that don't have a number in them, as they're not listening vols (maybe regional visitors etc.)
        if not any(chr.isdigit() for chr in vol["name"]):
            continue
        vol_name = vol["name"]
        for vol_property in vol["volunteer_properties"]:
            # if "friendly_name" in vol_property:
            #     val_name = vol_property["friendly_name"]["value"]
            #     if val_name:
            #         vol_name = val_name
            #     else:
            #         vol_name = vol["account"]["username"]
            if "join_date" in vol_property:
                val_join = vol_property["join_date"]["value"]
                if not val_join:
                    join_date = None
                else:
                    join_date = pendulum.parse(val_join)
            if "dbs_expiry_date" in vol_property:
                val_date = vol_property["dbs_expiry_date"]["value"]
                if not val_date:
                    expiry_date = pendulum.today().subtract(years=10)
                else:
                    expiry_date = pendulum.parse(val_date)
            if "email" in vol_property:
                email = vol_property["email"]["value"]

        out.append(VolChecks(vol_name, join_date, expiry_date, None, email))
    return out


# writes full_vol_report to text file, ordered by total_shifts
def make_full_member_report(vols: List[VolChecks]) -> None:
    vols.sort(key=lambda y: int(y.total_shifts))
    text = []
    for vol in vols:
        # New final condition
        if (
            "[T]" in vol.name
            or "[Prb]" in vol.name
            or vol.name in nonlistening_vols
            or not any(chr.isdigit() for chr in vol.name)
        ):
            continue
        if vol.pvc_shifts == "0":
            msg = f"{vol.name} - {vol.total_shifts} total (Day: {vol.day_shifts}, Night: {vol.night_shifts})"
        else:
            msg = f"{vol.name} - {vol.total_shifts} total (Day: {vol.day_shifts}, PVC: {vol.pvc_shifts}, Night: {vol.night_shifts})"
        if vol.days_inactive != "0":
            msg += f" Days Inactive: {vol.days_inactive}"
        # if int(vol.total_shifts) < 15:
        #     msg += " * Total *"
        if int(vol.night_shifts) < 2:
            if vol.name not in exempt_list:
                msg += " * Nights *"
        text.append(msg)

    TODAY_STRING = pendulum.today().format("DD_MM_YY")
    with open(f"full_vol_reports/full_vol_report_{TODAY_STRING}.txt", "w") as f:
        f.write(
            f"Full Volunteer Report {pendulum.today().format('DD.MM.YY')} (6 months period)\n\n"
        )
        for line in text:
            f.write(f"{line}\n")
        f.write(
            "\nNote: Current expectation is 20 shifts in 6 months, with 2 nights. PVC shifts are counted as a normal shift."
        )


# writes two_month_report to text file, ordered by total_shifts
def make_two_month_report(vols: List[VolChecks]) -> None:
    vols.sort(key=lambda y: int(y.total_shifts))
    text = []
    for vol in vols:
        if (
            vol.name in nonlistening_vols
            or not any(chr.isdigit() for chr in vol.name)
            or "[T]" in vol.name
        ):
            # Skip non-listening vols (hardcoded list in env), skip vols who have no volunteer number (these are likely guests), skip tutored vols as we don't count tutored shifts anyway
            continue

        msg = f"{vol.name} - {vol.total_shifts} total (Day: {vol.day_shifts}"
        if int(vol.pvc_shifts):
            msg += f", PVC: {vol.pvc_shifts}"
        if int(vol.foodbank_shifts):
            msg += f", F.Bank: {vol.foodbank_shifts}"
        msg += f", Night: {vol.night_shifts})"
        if int(vol.days_inactive):
            msg += f" Days Inactive: {vol.days_inactive}"
        if vol.name in nonlistening_vols:
            msg += f" (not receiving 8-week email)"
        # if int(vol.total_shifts) < 15:
        #     msg += " * Total *"
        text.append(msg)

    TODAY_STRING = pendulum.today().format("DD_MM_YY")
    with open(f"two_month_reports/two_month_report_{TODAY_STRING}.txt", "w") as f:
        f.write(
            f"8 week report {pendulum.today().subtract(weeks=8).format('DD.MM.YY')} - {pendulum.today().format('DD.MM.YY')} (8 week period)\n\n"
        )
        f.write(
            "Note: Current expectation is 6 shifts in 8 weeks. PVC shifts are counted as a normal shift.\n\n"
        )
        for line in text:
            f.write(f"{line}\n")


# helper function to write DBS expiry email
def make_dbs_expiry_msg(vols: List[VolChecks]) -> List[str]:
    msg = []
    for vol in vols:
        if vol.expiry_date <= pendulum.today().subtract(years=9):
            msg.append(f"{vol.name} DBS expiry date not set on Live ***")
        elif vol.expiry_date <= pendulum.today():
            msg.append(
                f"{vol.name} DBS expired: {vol.expiry_date.format('DD MMMM YYYY')} ***"
            )
        else:
            msg.append(
                f"{vol.name} DBS expiring soon: {vol.expiry_date.format('DD MMMM YYYY')}"
            )
    return msg


# helper function to write monthly anniversary email
def make_monthly_anni_msg(vols: List[VolChecks]) -> List[str]:
    msg = []
    for vol in vols:
        msg.append(
            f"{vol.name} - {vol.upcoming_anni} year anniversary this month (Joined {vol.join_date.format('DD.MM.YYYY')})"
        )
    return msg


def make_new_vol_report_msg():
    s = requests.Session()
    s.auth = (f"{login_info['username']}", f"{login_info['password']}")
    vols = get_active_volunteers()
    make_new_vol_report(vols, no_gui=True)

    TODAY_STRING = pendulum.today().format("DD_MM_YY")
    with open(f"new_vol_reports/new_vol_report_{TODAY_STRING}.txt") as f:
        text = f.read()

    if not text or len(text) < 200:
        logger.warning("Log not found, or not enough text in log to be valid")
        return

    return text


# Main emailer function, uses Outlook SMTP server, pass in object with subject, message, [recipients]
def send_emails_cl(emails: List[PreppedEmail]) -> None:
    context = ssl.create_default_context()
    # outlook smtp
    with smtplib.SMTP("smtp.office365.com", 587) as server:
        server.ehlo()  # Can be omitted
        server.starttls(context=context)
        server.ehlo()  # Can be omitted
        logger.info(f"Logging in {email_login['username']}")
        server.login(email_login["username"], email_login["password"])
        logger.info("Log in successful. Begin emailing...")
        for email in emails:
            for recipient in email.recipient_list:
                msgRoot = MIMEMultipart("related")
                msgRoot["Subject"] = email.subject
                msgRoot["From"] = email_login["username"]
                msgRoot["To"] = recipient

                msgRoot.preamble = (
                    "====================================================="
                )
                msgAlternative = MIMEMultipart("alternative")
                msgRoot.attach(msgAlternative)
                msgAlternative.attach(MIMEText(email.message))

                logger.info(f"{email.subject} to {recipient}")
                server.sendmail(msgRoot["From"], msgRoot["To"], msgRoot.as_string())


# def load_logs(log_path: Path) -> dict:
#     with open(log_path) as f:
#         return json.load(f)

# def save_logs(logs: dict):
#     with open("logs.json", "w") as f:
#         json.dump(logs, f, indent=4)


if __name__ == "__main__":
    logger.info("Starting report building")
    if VERSION == "DEMO":
        logger.warning("Cannot generate reports in demo version (no live data)")
        quit()

    TODAY_STRING = pendulum.today().format("DD_MM_YY")
    TODAY_DOTSTRING = pendulum.today().format("DD.MM.YY")
    prepped_emails = []
    report_errors = []
    logs = load_logs(REPORT_LOG_PATH)
    vols_check_list: List[VolChecks] = build_vol_checks()

    latest_log_date = {k: pendulum.parse(v) for k, v in logs.items()}

    # Send Annual anniversary email
    if (
        latest_log_date["latest_annual_anniversary_report"].year
        != pendulum.today().year
    ):
        logger.info("Creating Annual Anniversary report...")
        annual_vols: List[VolChecks] = annual_anniversary_check(vols_check_list)
        if not annual_vols:
            msg = f"{TODAY_DOTSTRING} - No volunteer x5 anniversaries this year"
        else:
            msg = f"Upcoming volunteer x5 anniversaries this year ({len(annual_vols)}):\n\n"
            msg += "\n".join(annual_anniversary_msg(annual_vols))
        prepped_emails.append(
            PreppedEmail(
                f"[AUTO] Annual x5 anniversaries for {pendulum.today().year}",
                msg,
                recipient_list["anniversary_report"],
            )
        )
        logs["latest_annual_anniversary_report"] = pendulum.today().format("YYYY-MM-DD")
        save_logs(logs)
        logger.info("Annual Anniversary report successful")

    # Send Monthly anniversary email
    if (
        latest_log_date["latest_monthly_anniversary_report"].month
        != pendulum.today().month
        or latest_log_date["latest_monthly_anniversary_report"].year
        != pendulum.today().year
    ):
        logger.info("Creating Monthly Anniversary report...")
        monthly_vols: List[VolChecks] = monthly_anniversary_check(vols_check_list)
        if not monthly_vols:
            msg = f"{TODAY_DOTSTRING} - No volunteer x5 anniversaries this month"
        else:
            msg = f"Volunteer x5 anniversaries this month ({len(monthly_vols)}):\n\n"
            msg += "\n".join(make_monthly_anni_msg(monthly_vols))
        prepped_emails.append(
            PreppedEmail(
                f"[AUTO] Monthly x5 anniversaries {TODAY_DOTSTRING}",
                msg,
                recipient_list["anniversary_report"],
            )
        )
        logs["latest_monthly_anniversary_report"] = pendulum.today().format(
            "YYYY-MM-DD"
        )
        save_logs(logs)
        logger.info("Monthly Anniversary report successful")

    # Send Monthly DBS report
    if (
        latest_log_date["latest_dbs_report"].month != pendulum.today().month
        or latest_log_date["latest_dbs_report"].year != pendulum.today().year
    ):
        logger.info("Creating Monthly DBS report...")
        expiring_vols = upcoming_dbs_expiry(vols_check_list)
        expiring_msg_list = make_dbs_expiry_msg(expiring_vols)
        if not expiring_msg_list:
            msg = f"{TODAY_DOTSTRING} - No DBS expiring within next 2 months"
        else:
            msg = f"Upcoming DBS expiry report {TODAY_DOTSTRING}\n\n"
            msg += "\n".join(make_dbs_expiry_msg(expiring_vols))
        prepped_emails.append(
            PreppedEmail(
                f"[AUTO] Upcoming DBS expiry report {TODAY_DOTSTRING}",
                msg,
                recipient_list["dbs_report"],
            )
        )
        logs["latest_dbs_report"] = pendulum.today().format("YYYY-MM-DD")
        save_logs(logs)
        logger.info("Monthly DBS report successful")

    # Send Quarterly Full Vol report
    if latest_log_date["latest_full_vol_report"] < pendulum.today().subtract(days=90):
        logger.info("Creating quarterly Full Member report...")
        vol_quarterly_list = get_stats(
            vols_check_list, pendulum.today().subtract(months=6), pendulum.today()
        )
        make_full_member_report(vol_quarterly_list)

        with open(f"full_vol_reports/full_vol_report_{TODAY_STRING}.txt") as f:
            msg = f.read()
        prepped_emails.append(
            PreppedEmail(
                f"[AUTO] Quarterly Full Member report {TODAY_DOTSTRING}",
                msg,
                recipient_list["full_vol_report"],
            )
        )
        logs["latest_full_vol_report"] = pendulum.today().format("YYYY-MM-DD")
        save_logs(logs)
        logger.info("Full Member report successful")

    # Send two monthly all vol report + Individual reports
    if latest_log_date["latest_two_monthly_report"].add(weeks=8) <= pendulum.today():
        logger.info("Creating master two monthly report")
        vol_eight_week_list: List[VolChecks] = get_stats(
            vols_check_list, pendulum.today().subtract(weeks=8), pendulum.today()
        )
        make_two_month_report(vol_eight_week_list)

        with open(f"two_month_reports/two_month_report_{TODAY_STRING}.txt") as f:
            msg = f.read()

        prepped_emails.append(
            PreppedEmail(
                f"[AUTO] 8 week report {TODAY_DOTSTRING}",
                msg,
                recipient_list["two_monthly_report"],
            )
        )
        logger.info("Master two monthly report successful")

        # Individual reports will also be sent on same day
        logger.info("Creating individual two monthly report")
        for vol in vols_check_list:
            if "[T]" in vol.name:  # or vol.name not in blt_list:
                continue
            # skip any names that don't have a number in them, as they're not listening vols (maybe regional visitors etc.)
            if not any(chr.isdigit() for chr in vol.name):
                continue
            if vol.name in nonlistening_vols:
                continue
            if not vol.join_date or not vol.email:
                logger.warning(
                    f"Skipping individual report, no email/join_date found for: {vol}"
                )
                continue
            # Create body of email
            msg = create_eight_week_email_message(vol=vol)
            prepped_emails.append(
                PreppedEmail(
                    f"[AUTO] Your Sams shifts in the last 8 weeks", msg, [vol.email]
                )
            )
        logger.info("Individual two monthly report successful")
        logs["latest_two_monthly_report"] = pendulum.today().format("YYYY-MM-DD")
        save_logs(logs)

    # Send new vol report weekly (program is only run weekly via window scheduler, but just in case: use 7 days as condition)
    if latest_log_date["latest_tutored_report"].add(days=6) <= pendulum.today():
        logger.info("Creating New Volunteer report...")
        msg = make_new_vol_report_msg()
        if msg:
            prepped_emails.append(
                PreppedEmail(
                    f"[AUTO] New vol report {pendulum.today().format('DD MMMM YYYY')}",
                    msg,
                    recipient_list["new_vol_report"],
                )
            )
            logs["latest_probationer_report"] = pendulum.today().format("YYYY-MM-DD")
            logs["latest_tutored_report"] = pendulum.today().format("YYYY-MM-DD")
            save_logs(logs)
            logger.info("New Volunteer report successful")
        else:
            logger.warning("New Volunteer report failed - check report text file")
            report_errors.append("New Volunteer report failed - check report text file")

    # Send expiring rota report weekly
    if latest_log_date["latest_expiring_rota_report"].add(days=6) <= pendulum.today():
        msg = create_expiring_rota_email_message()
        if msg:
            logger.info("Creating expiring rota report...")
            prepped_emails.append(
                PreppedEmail(
                    f"[AUTO] Expiring rotas {pendulum.today().format('DD MMMM YYYY')}",
                    msg,
                    recipient_list["expiring_rota_report"],
                )
            )
            logs["latest_expiring_rota_report"] = pendulum.today().format("YYYY-MM-DD")
            save_logs(logs)
            logger.info("Expiring report successful")
        else:
            logger.info("No expiring rota report - no rotas expiring soon.")
    # Send error report email if any errors happened

    if report_errors:
        logger.info("Creating error email report...")
        msg = "Errors in reports:\n"
        msg += "\n".join(report_errors)
        prepped_emails.append(
            PreppedEmail(
                f"[AUTO] Email report errors", msg, recipient_list["error_report"]
            )
        )

    if prepped_emails:
        logger.info(f"Emailing {len(prepped_emails)} reports")
        send_emails_cl(prepped_emails)
        logger.info("All reports built & emailed")
    else:
        logger.info("No reports to email")
