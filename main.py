import os
import sys
import time
import logging
from datetime import datetime

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

INTERVAL = 4 * 60 * 60  # 4 hours in seconds
TIMEOUT = 15
MAX_RETRIES = 1


def load_config():
    cookie = os.environ.get("HH_COOKIE", "").strip()
    xsrf = os.environ.get("HH_XSRF", "").strip()
    resume_hash = os.environ.get("HH_RESUME_HASH", "").strip()
    domain = os.environ.get("HH_DOMAIN", "astana.hh.kz")
    user_agent = os.environ.get(
        "HH_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    )

    if not cookie or not resume_hash:
        log.error("HH_COOKIE and HH_RESUME_HASH must be set")
        sys.exit(1)

    return {
        "url": f"https://{domain}/applicant/resumes/touch",
        "headers": {
            "Cookie": cookie,
            "User-Agent": user_agent,
            "X-Xsrftoken": xsrf,
            "Referer": f"https://{domain}/applicant/resumes",
            "Origin": f"https://{domain}",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        },
        "files": {
            "resume": (None, resume_hash),
            "undirectable": (None, "true"),
        },
    }


def touch_resume(config):
    for attempt in range(1 + MAX_RETRIES):
        try:
            log.info("Sending touch request (attempt %d)...", attempt + 1)
            resp = requests.post(
                config["url"],
                headers=config["headers"],
                files=config["files"],
                timeout=TIMEOUT,
                allow_redirects=False,
            )

            body_preview = resp.text[:300]
            log.info("Status: %d | Body: %s", resp.status_code, body_preview)

            if resp.status_code == 200:
                log.info("Resume touched successfully.")
                return True

            if resp.status_code == 409:
                log.info("409 Conflict — resume already touched recently (cooldown). This is OK.")
                return True

            if resp.status_code in (301, 302):
                location = resp.headers.get("Location", "")
                if "captcha" in location or "captcha" in body_preview:
                    log.warning("Redirected to captcha — too many requests. Will try next cycle.")
                    return True
                log.warning("Redirect to: %s", location)
                return True

            if resp.status_code == 403:
                log.error(
                    "403 Forbidden — cookies/xsrf expired. "
                    "Update HH_COOKIE and HH_XSRF in Railway env vars."
                )
                return False

            if resp.status_code >= 400:
                log.error("Server returned %d — check response above.", resp.status_code)
                return False

            log.info("Status %d — unexpected but not an error.", resp.status_code)
            return True

        except requests.exceptions.RequestException as e:
            log.warning("Network error: %s", e)
            if attempt < MAX_RETRIES:
                log.info("Retrying in 5 seconds...")
                time.sleep(5)
            else:
                log.error("All retries exhausted.")
                return False

    return False


def main():
    config = load_config()
    run_mode = os.environ.get("RUN_MODE", "once").lower()

    if run_mode == "loop":
        log.info("Running in loop mode (every %d hours)", INTERVAL // 3600)
        while True:
            touch_resume(config)
            log.info("Sleeping %d hours until next touch...", INTERVAL // 3600)
            time.sleep(INTERVAL)
    else:
        log.info("Running in once mode")
        success = touch_resume(config)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
