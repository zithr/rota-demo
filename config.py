from dotenv import load_dotenv
import os

load_dotenv()


def parse_list(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# Credentials
login_info = {
    "username": os.getenv("APP_USERNAME"),
    "password": os.getenv("APP_PASSWORD"),
}

APIKEY = os.getenv("API_KEY")
ROTA_HOSTNAME = os.getenv("ROTA_HOSTNAME")

email_login = {
    "username": os.getenv("EMAIL_USERNAME"),
    "password": os.getenv("EMAIL_PASSWORD"),
}

# App configuration
VERSION = os.getenv("VERSION", "DEMO")

recipient_list = {
    "anniversary_report": parse_list(os.getenv("ANNIVERSARY_REPORT_EMAILS")),
    "dbs_report": parse_list(os.getenv("DBS_REPORT_EMAILS")),
    "new_vol_report": parse_list(os.getenv("NEW_VOL_REPORT_EMAILS")),
    "full_vol_report": parse_list(os.getenv("FULL_VOL_REPORT_EMAILS")),
    "two_week_report": parse_list(os.getenv("TWO_WEEK_REPORT_EMAILS")),
    "two_monthly_report": parse_list(os.getenv("TWO_MONTHLY_REPORT_EMAILS")),
    "expiring_rota_report": parse_list(os.getenv("EXPIRING_ROTA_REPORT_EMAILS")),
    "error_report": parse_list(os.getenv("ERROR_REPORT_EMAILS")),
}

exempt_list = parse_list(os.getenv("EXEMPT_LIST"))
blt_list = parse_list(os.getenv("BLT_LIST"))
nonlistening_vols = parse_list(os.getenv("NONLISTENING_VOLS"))
