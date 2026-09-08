import re

import pandas as pd
import yaml
from playwright.sync_api import sync_playwright

ORGANISERS_FILE = "organisers.yml"
MONTHS_PL = {
    "stycznia": "January",
    "lutego": "February",
    "marca": "March",
    "kwietnia": "April",
    "maja": "May",
    "czerwca": "June",
    "lipca": "July",
    "sierpnia": "August",
    "września": "September",
    "października": "October",
    "listopada": "November",
    "grudnia": "December",
}


def load_organisers(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return data["organisers"]


def reject_cookies(page) -> None:
    button = page.get_by_role("button", name="Odrzuć opcjonalne pliki cookie")

    if button.is_visible():
        button.click()
        page.wait_for_timeout(200)


def close_login_popup(page) -> None:
    close_button = page.get_by_role("button", name="Zamknij")

    if close_button.is_visible():
        close_button.click()
        page.wait_for_timeout(200)


def load_all_events(page) -> None:
    previous_count = 0
    stable_rounds = 0

    while stable_rounds < 5:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)

        current_count = page.locator("a[href*='/events/']").count()

        if current_count == previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0

        previous_count = current_count


def get_event_details(page, url: str) -> dict:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    close_login_popup(page)

    print("Event title:", page.title())
    print("Event URL:", page.url)

    event_header = page.get_by_role(
        "button",
        name=re.compile(
            r"^(Poniedziałek|Wtorek|Środa|Czwartek|Piątek|Sobota|Niedziela), "
            r"\d{1,2} .* o \d{1,2}:\d{2}"
        ),
    )

    if event_header.count():
        sections = event_header.locator(":scope > div > div")
        weekday, date_time = sections.nth(0).inner_text().split(",")
        title_clean = " ".join(
            line.strip() for line in sections.nth(1).inner_text().split("\n")
        )
        location = sections.nth(2).inner_text()

        return {
            "Data": date_time,
            "Dzień tygodnia": weekday,
            "Tytuł": title_clean,
            "Lokalizacja": location,
            "URL": url,
        }

    else:
        lines = [
            line.strip()
            for line in page.locator("body").inner_text().splitlines()
            if line.strip()
        ]

        date_pattern = re.compile(
            r"^(Poniedziałek|Wtorek|Środa|Czwartek|Piątek|Sobota|Niedziela), "
            r"\d{1,2} .* o \d{1,2}:\d{2}"
        )

        date_index = next(
            (i for i, line in enumerate(lines) if date_pattern.match(line)),
            None,
        )

        if date_index is None:
            return {
                "Data": None,
                "Dzień tygodnia": None,
                "Tytuł": None,
                "Lokalizacja": None,
                "URL": page.url,
            }

        weekday, date_time = lines[date_index].split(",")
        title = lines[date_index + 1]
        location = lines[date_index + 2]

        return {
            "Data": date_time,
            "Dzień tygodnia": weekday,
            "Tytuł": title,
            "Lokalizacja": location,
            "URL": page.url,
        }


def get_events_from_fb(organiser: dict) -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        page.goto(organiser["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(200)

        reject_cookies(page)
        close_login_popup(page)

        load_all_events(page)

        links = page.locator("a")

        events = []

        for i in range(links.count()):
            link = links.nth(i)
            text = link.inner_text().strip()
            href = link.get_attribute("href")

            if "quiz" in text.lower() and href and "/events/" in href:
                events.append(
                    {
                        "organiser": organiser["name"],
                        "title": text,
                        "url": href,
                    }
                )

        event_details = []

        for event in events:
            details = get_event_details(page, event["url"])

            if details:
                details["Organizator"] = organiser["name"]
                event_details.append(details)

        browser.close()

    return event_details


def parse_date(date_str: str) -> pd.Timestamp:
    if pd.isna(date_str):
        return pd.NaT

    match = re.search(r"(\d{1,2}) (\w+) (\d{4}) o (\d{1,2}:\d{2})", date_str)

    if not match:
        return pd.NaT

    day, month, year, time = match.groups()
    month = MONTHS_PL[month]

    return pd.to_datetime(f"{day} {month} {year} {time}")


if __name__ == "__main__":
    organisers = load_organisers(ORGANISERS_FILE)
    all_events = []

    for organiser in organisers:
        print(f"\n{'='*64}")
        print(f"Organiser: {organiser['name']}")

        if organiser["type"] == "FB":
            events = get_events_from_fb(organiser)
            all_events.extend(events)

    column_order = [
        "Data",
        "Dzień tygodnia",
        "Organizator",
        "Tytuł",
        "Lokalizacja",
        "URL",
    ]
    df = pd.DataFrame(all_events, columns=column_order)

    df["Data"] = df["Data"].apply(parse_date)

    df = df.sort_values("URL", key=lambda x: x.str.len())
    df = df.drop_duplicates(subset=["Data", "Tytuł", "Lokalizacja"], keep="first")

    df.sort_values(["Data", "Organizator", "Tytuł"]).to_csv("events.csv", index=False)
