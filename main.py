import re

import pandas as pd
import yaml
from playwright.sync_api import sync_playwright

ORGANISERS_FILE = "organisers.yml"


def load_organisers(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as file:
        data = yaml.safe_load(file)

    return data["organisers"]


def reject_cookies(page) -> None:
    button = page.get_by_role("button", name="Odrzuć opcjonalne pliki cookie")

    if button.is_visible():
        button.click()
        page.wait_for_timeout(500)


def close_login_popup(page) -> None:
    close_button = page.get_by_role("button", name="Zamknij")

    if close_button.is_visible():
        close_button.click()
        page.wait_for_timeout(500)


def get_event_details(page, url: str) -> dict:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(200)
    close_login_popup(page)

    print("Event title:", page.title())
    print("Event URL:", page.url)

    event_header = page.get_by_role(
        "button",
        name=re.compile(r"^\w+, \d+ .* o \d+:\d+"),
    )

    if event_header.count():
        sections = event_header.locator(":scope > div > div")
        title_clean = " ".join(
            line.strip() for line in sections.nth(1).inner_text().split("\n")
        )

        return {
            "date_time": sections.nth(0).inner_text(),
            "title": title_clean,
            "location": sections.nth(2).inner_text(),
            "url": url,
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
                "date_time": None,
                "title": None,
                "location": None,
                "url": page.url,
            }

        date_time = lines[date_index]
        title = lines[date_index + 1]
        location = lines[date_index + 3]

        return {
            "date_time": date_time,
            "title": title,
            "location": location,
            "url": page.url,
        }


def get_events_from_fb(organiser: dict) -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        page.goto(organiser["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(500)

        reject_cookies(page)
        close_login_popup(page)

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
                details["organiser"] = organiser["name"]
                event_details.append(details)

        browser.close()

    return event_details


if __name__ == "__main__":
    organisers = load_organisers(ORGANISERS_FILE)
    all_events = []

    for organiser in organisers:
        print(f"\n{'='*64}")
        print(f"Organiser: {organiser['name']}")
        print(f"\n{'='*64}")

        if organiser["type"] == "FB":
            events = get_events_from_fb(organiser)
            all_events.extend(events)

    df = pd.DataFrame(all_events)
    df.to_csv("test.csv")
