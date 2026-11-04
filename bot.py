import os
import json
import time
import html
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL = "@speedvacancy"
SITEMAP_INDEX = "https://www.ethiopianreporterjobs.com/sitemap_index.xml"
STATE_FILE = "posted_jobs.json"

HEADERS = {
    "User-Agent": "SpeedVacancyBot/1.0 (job sitemap monitor)"
}


def load_seen():
    if not os.path.exists(STATE_FILE):
        return None

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(json.load(f))


def save_seen(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def get_job_urls():
    response = requests.get(SITEMAP_INDEX, headers=HEADERS, timeout=30)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    sitemap_urls = []

    for item in root:
        loc = item.find("{*}loc")
        if loc is not None and "job-sitemap" in loc.text:
            sitemap_urls.append(loc.text.strip())

    job_urls = set()

    for sitemap in sitemap_urls:
        try:
            r = requests.get(sitemap, headers=HEADERS, timeout=30)
            r.raise_for_status()
            sitemap_root = ET.fromstring(r.content)

            for item in sitemap_root:
                loc = item.find("{*}loc")
                if loc is not None and "/jobs/" in loc.text:
                    job_urls.add(loc.text.strip())

        except Exception as e:
            print("Sitemap error:", sitemap, e)

    return job_urls


def find_jobposting(data):
    if isinstance(data, list):
        for item in data:
            result = find_jobposting(item)
            if result:
                return result

    elif isinstance(data, dict):
        job_type = data.get("@type", "")
        if isinstance(job_type, list):
            job_type = " ".join(job_type)

        if "JobPosting" in str(job_type):
            return data

        if "@graph" in data:
            return find_jobposting(data["@graph"])

    return None


def get_job_details(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    job = None

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
            job = find_jobposting(data)
            if job:
                break
        except Exception:
            continue

    if not job:
        title = soup.title.get_text(strip=True) if soup.title else "Vacancy"
        description = soup.get_text(" ", strip=True)
        employer = "Not specified"
        location = "Not specified"
        deadline = "Not specified"
    else:
        title = job.get("title", "Vacancy")

        org = job.get("hiringOrganization", {})
        employer = org.get("name", "Not specified") if isinstance(org, dict) else "Not specified"

        loc = job.get("jobLocation", {})
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        address = loc.get("address", {}) if isinstance(loc, dict) else {}

        if isinstance(address, dict):
            location = ", ".join(
                str(address.get(k, "")).strip()
                for k in ("addressLocality", "addressRegion", "addressCountry")
                if address.get(k)
            ) or "Not specified"
        else:
            location = "Not specified"

        deadline = job.get("validThrough", "Not specified")
        description = job.get("description", "")

    description = html.unescape(str(description))
    description = BeautifulSoup(description, "html.parser").get_text(" ", strip=True)
    description = " ".join(description.split())

    return title, employer, location, deadline, description


def send_message(text):
    api_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    response = requests.post(
        api_url,
        data={
            "chat_id": CHANNEL,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result)


def main():
    seen = load_seen()
    current_urls = get_job_urls()

    if seen is None:
        save_seen(current_urls)
        print(f"Initial setup: recorded {len(current_urls)} existing vacancies.")
        print("No old jobs were posted.")
        return

    new_urls = sorted(current_urls - seen)

    if not new_urls:
        print("No new vacancies.")
        return

    print(f"Found {len(new_urls)} new vacancy URL(s).")

    for url in new_urls:
        try:
            title, employer, location, deadline, description = get_job_details(url)

            title = html.escape(title)
            employer = html.escape(employer)
            location = html.escape(location)
            deadline = html.escape(str(deadline))
            description = html.escape(description[:1800])

            message = (
                "📢 <b>NEW VACANCY</b>\n\n"
                f"💼 <b>Position:</b> {title}\n"
                f"🏢 <b>Employer:</b> {employer}\n"
                f"📍 <b>Location:</b> {location}\n"
                f"📅 <b>Deadline:</b> {deadline}\n\n"
                f"📝 <b>Details:</b>\n{description}\n\n"
                f"🔗 <a href=\"{html.escape(url, quote=True)}\">View and apply</a>"
            )

            send_message(message[:4000])
            seen.add(url)
            save_seen(seen)
            print("Posted:", url)
            time.sleep(2)

        except Exception as e:
            print("Failed to process:", url, e)


if __name__ == "__main__":
    main()
