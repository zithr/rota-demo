import requests
import pendulum
import json
from main import get_active_volunteers, make_new_vol_report
from config import login_info, email_login, recipient_list
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List
from loguru import logger

def send_email(email_subject: str, email_text: str, recipient_list: List[str]):
    context = ssl.create_default_context()
    # outlook smtp
    with smtplib.SMTP("smtp.office365.com", 587) as server:
        server.ehlo()  # Can be omitted
        server.starttls(context=context)
        server.ehlo()  # Can be omitted
        logger.info(f"Logging in {email_login['username']}")
        server.login(email_login["username"], email_login["password"])
        logger.info("Sending...")
        for recipient in recipient_list:
            msgRoot = MIMEMultipart("related")
            msgRoot["Subject"] = email_subject
            msgRoot["From"] = email_login["username"]
            msgRoot["To"] = recipient

            msgAlternative = MIMEMultipart("alternative")
            msgRoot.attach(msgAlternative)
            msgAlternative.attach(MIMEText(email_text))

            logger.info(f"Sending to {recipient}")
            server.sendmail(msgRoot["From"], msgRoot["To"], msgRoot.as_string())

def load_logs() -> dict:
    with open("logs.json") as f:
        return json.load(f)

def save_logs(logs: dict):
    with open("logs.json", "w") as f:
        json.dump(logs, f, indent=4)


if __name__ == "__main__":
    s = requests.Session()
    s.auth = (f'{login_info["username"]}', f'{login_info["password"]}')
    vols = get_active_volunteers(s)
    make_new_vol_report(vols, no_gui=True)

    TODAY_STRING = pendulum.today().format('DD_MM_YY')
    with open(f"new_vol_reports/new_vol_report_{TODAY_STRING}.txt") as f:
        text = f.read()
    
    if not text or len(text) < 200:
        logger.warning("Log not found, or not enough text in log to be valid")
        quit()
    quit()
    logs = load_logs()

    send_email(f"New vol report {pendulum.today().format('DD MMMM YYYY')}", text, recipient_list["new_vol_report"])

    # Update and save logs
    logs["latest_tutored_report"] = pendulum.today().format('YYYY-MM-DD')
    logs["latest_probationer_report"] = pendulum.today().format('YYYY-MM-DD')
    save_logs(logs)



