from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


BASE_DIR = Path(__file__).resolve().parent
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]
TZ = ZoneInfo("Asia/Tokyo")
AUTO_TAGS = [
    "[AUTO_INTERN]",
    "[AUTO_TRAVEL]",
    "[AUTO_PREP]",
    "[AUTO_SLEEP]",
    "[AUTO_SLEEP_EXTRA]",
    "[AUTO_ROUTINE]",
    "[AUTO_REST]",
    "[SYNC_BAR_LEMONADE]",
]
OUTING_LOCATION_TYPES = {"near_home", "outside_home_1h", "outside_home_1_5h", "bar", "intern"}


@dataclass(frozen=True)
class Block:
    title: str
    start: datetime
    end: datetime
    type: str
    location_type: str
    source: str
    travel_min: int = 0
    requires_preparation: bool = False

    @property
    def duration_min(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class PlannedEvent:
    title: str
    start: datetime
    end: datetime
    tag: str
    location_type: str
    description: str = ""

    @property
    def duration_min(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_dt(value: str) -> datetime:
    value = value.strip()
    if "T" in value:
        dt = datetime.fromisoformat(value)
    else:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def combine_dt(day: date, hhmm: str) -> datetime:
    hour, minute = [int(part) for part in hhmm.split(":")]
    extra_days, hour = divmod(hour, 24)
    return datetime.combine(day + timedelta(days=extra_days), time(hour, minute), tzinfo=TZ)


def iso(dt: datetime) -> str:
    return dt.astimezone(TZ).isoformat()


def get_calendar_service(config: dict[str, Any]):
    return get_google_service(config, "calendar", "v3")


def get_sheets_service(config: dict[str, Any]):
    return get_google_service(config, "sheets", "v4")


def get_secret_json(name: str) -> dict[str, Any] | None:
    env_value = os.environ.get(name.upper())
    if env_value:
        return json.loads(env_value)
    try:
        import streamlit as st

        if name in st.secrets:
            value = st.secrets[name]
            if isinstance(value, str):
                return json.loads(value)
            return dict(value)
    except Exception:
        return None
    return None


def get_google_service(config: dict[str, Any], service_name: str, version: str):
    token_path = BASE_DIR / config.get("token_file", "token.json")
    credentials_path = BASE_DIR / config.get("credentials_file", "credentials.json")
    token_info = get_secret_json("google_token_json")
    credentials_info = get_secret_json("google_credentials_json")
    creds = None

    if token_info:
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    elif token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if credentials_info:
                flow = InstalledAppFlow.from_client_config(credentials_info, SCOPES)
            elif credentials_path.exists():
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            else:
                raise FileNotFoundError(
                    f"{credentials_path} が見つかりません。Google CloudからOAuthクライアントJSONを配置してください。"
                )
            creds = flow.run_local_server(port=0)
        if not token_info:
            token_path.write_text(creds.to_json(), encoding="utf-8")

    return build(service_name, version, credentials=creds)


def using_sheets_storage(config: dict[str, Any]) -> bool:
    storage = config.get("storage", {})
    return storage.get("backend") == "google_sheets" and bool(storage.get("spreadsheet_id"))


def sheet_read_json(config: dict[str, Any], sheet_name: str, default: Any) -> Any:
    service = get_sheets_service(config)
    spreadsheet_id = config["storage"]["spreadsheet_id"]
    response = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A1").execute()
    values = response.get("values", [])
    if not values or not values[0] or not values[0][0]:
        return default
    return json.loads(values[0][0])


def sheet_write_json(config: dict[str, Any], sheet_name: str, data: Any) -> None:
    service = get_sheets_service(config)
    spreadsheet_id = config["storage"]["spreadsheet_id"]
    body = {"values": [[json.dumps(data, ensure_ascii=False)]]}
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="RAW",
        body=body,
    ).execute()


def load_manual_data(config: dict[str, Any]) -> list[dict[str, Any]]:
    if using_sheets_storage(config):
        return sheet_read_json(config, config["storage"].get("manual_sheet", "manual_blocks"), [])
    return load_json(BASE_DIR / "manual_blocks.json", [])


def save_manual_data(config: dict[str, Any], blocks: list[dict[str, Any]]) -> None:
    if using_sheets_storage(config):
        sheet_write_json(config, config["storage"].get("manual_sheet", "manual_blocks"), blocks)
    else:
        save_json(BASE_DIR / "manual_blocks.json", blocks)


def load_bar_selection_data(config: dict[str, Any]) -> dict[str, Any]:
    if using_sheets_storage(config):
        return sheet_read_json(config, config["storage"].get("selection_sheet", "bar_event_selections"), {})
    return load_json(BASE_DIR / "bar_event_selections.json", {})


def save_bar_selection_data(config: dict[str, Any], selections: dict[str, Any]) -> None:
    if using_sheets_storage(config):
        sheet_write_json(config, config["storage"].get("selection_sheet", "bar_event_selections"), selections)
    else:
        save_json(BASE_DIR / "bar_event_selections.json", selections)


def to_block(event: dict[str, Any], source: str) -> Block | None:
    start_raw = event.get("start", {}).get("dateTime")
    end_raw = event.get("end", {}).get("dateTime")
    if not start_raw or not end_raw:
        return None
    location_type = event.get("extendedProperties", {}).get("private", {}).get("location_type", "outside_home_1h")
    return Block(
        title=event.get("summary", "(no title)"),
        start=parse_dt(start_raw),
        end=parse_dt(end_raw),
        type="calendar",
        location_type=location_type,
        source=source,
    )


def to_bar_block(event: dict[str, Any]) -> Block | None:
    start_raw = event.get("start", {}).get("dateTime")
    end_raw = event.get("end", {}).get("dateTime")
    if not start_raw or not end_raw:
        return None
    return Block(
        title=event.get("summary", "(no title)"),
        start=parse_dt(start_raw),
        end=parse_dt(end_raw),
        type="bar_calendar",
        location_type="online",
        source=event.get("id", ""),
    )


def classify_bar_block(block: Block, config: dict[str, Any], selected_events: dict[str, Any]) -> Block | None:
    filters = config.get("bar_lemonade_filters", {})
    title = block.title or ""
    if any(name in title for name in filters.get("shift_names", [])):
        return Block(
            title=block.title,
            start=block.start,
            end=block.end,
            type="バー",
            location_type="bar",
            source=block.source,
        )
    if any(required in title for required in filters.get("required_titles", [])):
        return Block(
            title=block.title,
            start=block.start,
            end=block.end,
            type="ミーティング",
            location_type="online",
            source=block.source,
        )
    selected = selected_events.get(block.source)
    if selected and selected.get("include", False):
        return Block(
            title=block.title,
            start=block.start,
            end=block.end,
            type=selected.get("type", "選択予定"),
            location_type=selected.get("location_type", "online"),
            source=block.source,
            travel_min=int(selected.get("travel_min", 0) or 0),
            requires_preparation=bool(selected.get("requires_preparation", False)),
        )
    return None


def get_events(service, calendar_id: str, start: datetime, end: datetime, source: str) -> list[Block]:
    response = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=iso(start),
            timeMax=iso(end),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    blocks: list[Block] = []
    for event in response.get("items", []):
        block = to_block(event, source)
        if block:
            blocks.append(block)
    return blocks


def get_raw_events(service, calendar_id: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    return (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=iso(start),
            timeMax=iso(end),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )


def is_auto_event(event: dict[str, Any]) -> bool:
    text = f"{event.get('summary', '')}\n{event.get('description', '')}"
    return any(tag in text for tag in AUTO_TAGS)


def get_non_auto_calendar_blocks(service, calendar_id: str, start: datetime, end: datetime, source: str) -> list[Block]:
    blocks = []
    for event in get_raw_events(service, calendar_id, start, end):
        if is_auto_event(event):
            continue
        block = to_block(event, source)
        if block:
            blocks.append(block)
    return blocks


def get_freebusy(service, calendar_ids: list[str], start: datetime, end: datetime) -> dict[str, list[Block]]:
    if not calendar_ids:
        return {}
    response = (
        service.freebusy()
        .query(
            body={
                "timeMin": iso(start),
                "timeMax": iso(end),
                "timeZone": "Asia/Tokyo",
                "items": [{"id": calendar_id} for calendar_id in calendar_ids],
            }
        )
        .execute()
    )
    result: dict[str, list[Block]] = {}
    for calendar_id, data in response.get("calendars", {}).items():
        result[calendar_id] = [
            Block(
                title=f"Busy: {calendar_id}",
                start=parse_dt(item["start"]),
                end=parse_dt(item["end"]),
                type="busy",
                location_type="outside_home_1h",
                source=f"freebusy:{calendar_id}",
            )
            for item in data.get("busy", [])
        ]
    return result


def load_manual_blocks(config: dict[str, Any]) -> list[Block]:
    data = load_manual_data(config)
    blocks = []
    for item in data:
        blocks.append(
            Block(
                title=item.get("title", "manual"),
                start=parse_dt(item["start"]),
                end=parse_dt(item["end"]),
                type=item.get("type", "その他"),
                location_type=item.get("location_type", "outside_home_1h"),
                source="manual",
                travel_min=int(item.get("travel_min", 0) or 0),
                requires_preparation=bool(item.get("requires_preparation", False)),
            )
        )
    return blocks


def load_holidays(config: dict[str, Any], start: datetime, days: int) -> set[date]:
    configured = {date.fromisoformat(x) for x in config.get("holidays", [])}
    holiday_file = BASE_DIR / config.get("holidays_file", "holidays.json")
    if holiday_file.exists():
        configured |= {date.fromisoformat(x) for x in load_json(holiday_file, [])}
    return {start.date() + timedelta(days=i) for i in range(days)} & configured


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def is_free(start: datetime, end: datetime, busy: list[Block | PlannedEvent]) -> bool:
    return start < end and all(not overlaps(start, end, item.start, item.end) for item in busy)


def prep_can_overlap(item: Block | PlannedEvent) -> bool:
    return item.location_type == "online" or getattr(item, "type", "") in {"ミーティング", "online"}


def is_free_for_event(event: PlannedEvent, busy: list[Block | PlannedEvent]) -> bool:
    if event.tag == "[AUTO_PREP]":
        return event.start < event.end and all(
            prep_can_overlap(item) or not overlaps(event.start, event.end, item.start, item.end) for item in busy
        )
    return is_free(event.start, event.end, busy)


def add_if_free(
    planned: list[PlannedEvent],
    busy: list[Block | PlannedEvent],
    event: PlannedEvent,
    logs: list[str],
) -> bool:
    if is_free_for_event(event, busy + planned):
        planned.append(event)
        logs.append(f"追加: {event.tag} {event.start:%m/%d %H:%M}-{event.end:%H:%M} {event.title}")
        return True
    logs.append(f"スキップ: {event.tag} {event.start:%m/%d %H:%M}-{event.end:%H:%M} {event.title}")
    return False


def is_outing(item: Block | PlannedEvent) -> bool:
    return item.location_type in OUTING_LOCATION_TYPES


def has_earlier_outing(day: date, before: datetime, items: list[Block | PlannedEvent]) -> bool:
    return any(is_outing(item) and item.start.date() == day and item.start < before for item in items)


def is_after_last_train(dt: datetime) -> bool:
    return dt.hour < 5


def return_travel_window(block: Block | PlannedEvent, travel_min: int) -> tuple[datetime, datetime]:
    if block.location_type not in {"home", "online"} and is_after_last_train(block.end):
        return_start = datetime.combine(block.end.date(), time(5, 0), tzinfo=TZ)
    else:
        return_start = block.end
    return return_start, return_start + timedelta(minutes=travel_min)


def default_travel_min(location_type: str) -> int:
    return {
        "near_home": 30,
        "outside_home_1h": 60,
        "outside_home_1_5h": 90,
        "bar": 90,
        "intern": 80,
    }.get(location_type, 60)


def travel_minutes_between(prev_location: str, next_location: str, default_min: int) -> int:
    if {prev_location, next_location} == {"bar", "intern"}:
        return 40
    if prev_location.startswith("outside_home") and next_location == "bar":
        return 60
    if {prev_location, next_location} == {"home", "intern"}:
        return 90
    if {prev_location, next_location} == {"near_home", "intern"}:
        return 90
    if next_location == "online" or next_location == "home":
        return 0
    return default_min


def add_prep_and_travel(
    blocks: list[Block],
    busy_blocks: list[Block],
    planned: list[PlannedEvent],
    logs: list[str],
) -> None:
    busy: list[Block | PlannedEvent] = busy_blocks + planned
    for block in sorted(blocks, key=lambda x: x.start):
        if block.location_type not in OUTING_LOCATION_TYPES:
            continue
        travel_min = block.travel_min or default_travel_min(block.location_type)
        travel_start = block.start - timedelta(minutes=travel_min)
        travel_end = block.start
        needs_prep = block.requires_preparation or not has_earlier_outing(block.start.date(), block.start, busy_blocks + planned)
        if needs_prep and block.location_type not in {"home", "online"}:
            prep_end = travel_start
            prep_start = prep_end - timedelta(hours=1)
            add_if_free(
                planned,
                busy,
                PlannedEvent("準備", prep_start, prep_end, "[AUTO_PREP]", "home", f"{block.title} の準備"),
                logs,
            )
        add_if_free(
            planned,
            busy,
            PlannedEvent("移動", travel_start, travel_end, "[AUTO_TRAVEL]", "travel", f"{block.title} への移動"),
            logs,
        )


def add_return_travels(
    blocks: list[Block],
    busy_blocks: list[Block],
    planned: list[PlannedEvent],
    logs: list[str],
) -> None:
    for block in sorted(blocks, key=lambda x: x.end):
        if block.location_type not in OUTING_LOCATION_TYPES:
            continue
        travel_min = block.travel_min or default_travel_min(block.location_type)
        return_start, return_end = return_travel_window(block, travel_min)
        title = "終電後の帰宅" if return_start.hour == 5 and block.end.hour < 5 else "帰宅移動"
        add_if_free(
            planned,
            busy_blocks + planned,
            PlannedEvent(title, return_start, return_end, "[AUTO_TRAVEL]", "travel", f"{block.title} から帰宅"),
            logs,
        )


def intern_prerequisites(
    event: PlannedEvent,
    config: dict[str, Any],
    busy_blocks: list[Block],
    planned: list[PlannedEvent],
) -> list[PlannedEvent]:
    travel_min = int(config.get("intern", {}).get("travel_min", 80))
    travel = PlannedEvent(
        "インターン移動",
        event.start - timedelta(minutes=travel_min),
        event.start,
        "[AUTO_TRAVEL]",
        "travel",
        "インターン前の移動",
    )
    prerequisites = [travel]
    if not has_earlier_outing(event.start.date(), event.start, busy_blocks + planned):
        prerequisites.insert(
            0,
            PlannedEvent(
                "準備",
                travel.start - timedelta(hours=1),
                travel.start,
                "[AUTO_PREP]",
                "home",
                "その日初回外出前の準備",
            ),
        )
    return prerequisites


def intern_return(event: PlannedEvent, config: dict[str, Any]) -> PlannedEvent:
    travel_min = int(config.get("intern", {}).get("travel_min", 80))
    return_start, return_end = return_travel_window(event, travel_min)
    return PlannedEvent(
        "インターン帰宅",
        return_start,
        return_end,
        "[AUTO_TRAVEL]",
        "travel",
        "インターン後の帰宅",
    )


def add_intern_if_possible(
    planned: list[PlannedEvent],
    busy_blocks: list[Block],
    event: PlannedEvent,
    config: dict[str, Any],
    logs: list[str],
) -> bool:
    prerequisites = intern_prerequisites(event, config, busy_blocks, planned)
    candidates = prerequisites + [event, intern_return(event, config)]
    base: list[Block | PlannedEvent] = busy_blocks + planned
    for candidate in candidates:
        if not is_free_for_event(candidate, base + [x for x in candidates if x is not candidate]):
            logs.append(
                f"スキップ: {event.tag} {event.start:%m/%d %H:%M}-{event.end:%H:%M} {event.title} "
                f"({candidate.title}を確保できません)"
            )
            return False
    for candidate in candidates:
        planned.append(candidate)
        logs.append(f"追加: {candidate.tag} {candidate.start:%m/%d %H:%M}-{candidate.end:%H:%M} {candidate.title}")
    return True


def add_interns(
    config: dict[str, Any],
    busy_blocks: list[Block],
    planned: list[PlannedEvent],
    start: datetime,
    days: int,
    holidays: set[date],
    logs: list[str],
) -> None:
    rules = config["intern"]
    priority = rules["priority"]
    times = rules["times"]
    by_week: dict[tuple[int, int], list[date]] = {}
    for offset in range(days):
        d = start.date() + timedelta(days=offset)
        by_week.setdefault(d.isocalendar()[:2], []).append(d)

    for _, week_days in by_week.items():
        count = 0
        for weekday_key in priority:
            d = next((x for x in week_days if str(x.weekday()) == weekday_key), None)
            if not d or d in holidays:
                if d in holidays:
                    logs.append(f"スキップ: [AUTO_INTERN] {d:%m/%d} は祝日")
                continue
            start_s, end_s = times[weekday_key]
            ev = PlannedEvent(
                "インターン",
                combine_dt(d, start_s),
                combine_dt(d, end_s),
                "[AUTO_INTERN]",
                "intern",
                "週3回マストの自動配置",
            )
            if add_intern_if_possible(planned, busy_blocks, ev, config, logs):
                count += 1
            if count >= rules.get("weekly_required", 3):
                break
        if count < rules.get("weekly_required", 3):
            logs.append(f"警告: {week_days[0].isocalendar().week}週目のインターンが{count}回だけです")


def has_drinking_previous_night(blocks: list[Block], day: date) -> bool:
    prev_start = datetime.combine(day - timedelta(days=1), time(18, 0), tzinfo=TZ)
    noon = datetime.combine(day, time(12, 0), tzinfo=TZ)
    return any(block.type == "飲み会" and overlaps(prev_start, noon, block.start, block.end) for block in blocks)


def add_sleep(
    config: dict[str, Any],
    blocks: list[Block],
    planned: list[PlannedEvent],
    start: datetime,
    days: int,
    logs: list[str],
) -> int:
    sleep_cfg = config["sleep"]
    total = 0
    for offset in range(days):
        d = start.date() + timedelta(days=offset)
        base_start = combine_dt(d, sleep_cfg.get("default_start", "25:00"))
        base_end = base_start + timedelta(hours=sleep_cfg.get("base_hours", 6))
        same_night = [
            block
            for block in blocks
            if block.location_type not in {"home", "online"}
            and overlaps(combine_dt(d, "20:00"), combine_dt(d, "29:00"), block.start, block.end)
        ]
        if same_night:
            latest = max(same_night, key=lambda x: x.end)
            if latest.end.hour < 5 or latest.end.date() > d:
                base_start = latest.end + timedelta(hours=1)
                base_end = base_start + timedelta(hours=sleep_cfg.get("base_hours", 6))

        if has_drinking_previous_night(blocks, d):
            morning = Block("飲み会翌日午前NG", combine_dt(d, "06:00"), combine_dt(d, "12:00"), "guard", "home", "rule")
            blocks.append(morning)
            logs.append(f"警告: {d:%m/%d} 飲み会翌日のため午前NG")

        ev = PlannedEvent("睡眠", base_start, base_end, "[AUTO_SLEEP]", "home", "基本睡眠")
        if add_if_free(planned, blocks + planned, ev, logs):
            total += ev.duration_min
        else:
            min_end = base_start + timedelta(hours=sleep_cfg.get("min_hours", 3))
            min_ev = PlannedEvent("睡眠", base_start, min_end, "[AUTO_SLEEP]", "home", "最低睡眠")
            if add_if_free(planned, blocks + planned, min_ev, logs):
                total += min_ev.duration_min

    target_min = int(sleep_cfg.get("weekly_target_hours", 42) * 60 * days / 7)
    if total < target_min:
        missing = target_min - total
        for offset in range(days):
            if missing <= 0:
                break
            d = start.date() + timedelta(days=offset)
            nap_start = combine_dt(d, "14:00")
            nap_end = nap_start + timedelta(minutes=min(120, missing))
            ev = PlannedEvent("追加睡眠", nap_start, nap_end, "[AUTO_SLEEP_EXTRA]", "home", "週睡眠目標の補填")
            if add_if_free(planned, blocks + planned, ev, logs):
                total += ev.duration_min
                missing -= ev.duration_min
    return total


def add_routines(
    routines: list[dict[str, Any]],
    blocks: list[Block],
    planned: list[PlannedEvent],
    start: datetime,
    days: int,
    logs: list[str],
) -> None:
    for offset in range(days):
        d = start.date() + timedelta(days=offset)
        for routine in routines:
            weekdays = routine.get("weekdays")
            if weekdays is not None and d.weekday() not in weekdays:
                continue
            duration = int(routine.get("duration_min", 30))
            candidates = routine.get("candidate_starts", ["07:30", "21:00"])
            for candidate in candidates:
                ev_start = combine_dt(d, candidate)
                ev_end = ev_start + timedelta(minutes=duration)
                ev = PlannedEvent(
                    routine.get("title", "ルーティン"),
                    ev_start,
                    ev_end,
                    "[AUTO_ROUTINE]",
                    routine.get("location_type", "home"),
                    "routine_scheduler generated",
                )
                if add_if_free(planned, blocks + planned, ev, logs):
                    break


def add_rests(blocks: list[Block], planned: list[PlannedEvent], logs: list[str]) -> None:
    for item in sorted(blocks + planned, key=lambda x: x.start):
        if item.duration_min >= 240:
            rest_start = item.start + timedelta(hours=4)
            rest_end = rest_start + timedelta(minutes=30)
            add_if_free(
                planned,
                blocks + planned,
                PlannedEvent("休憩", rest_start, rest_end, "[AUTO_REST]", item.location_type, "4時間連続後の休憩"),
                logs,
            )


def delete_auto_events(service, calendar_id: str, start: datetime, end: datetime) -> int:
    events = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=iso(start),
            timeMax=iso(end),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )
    deleted = 0
    for event in events:
        if is_auto_event(event):
            service.events().delete(calendarId=calendar_id, eventId=event["id"]).execute()
            deleted += 1
    return deleted


def insert_event(service, calendar_id: str, event: PlannedEvent) -> None:
    service.events().insert(
        calendarId=calendar_id,
        body={
            "summary": f"{event.tag} {event.title}",
            "description": event.description,
            "start": {"dateTime": iso(event.start), "timeZone": "Asia/Tokyo"},
            "end": {"dateTime": iso(event.end), "timeZone": "Asia/Tokyo"},
            "extendedProperties": {"private": {"location_type": event.location_type, "generated_by": "routine_scheduler"}},
        },
    ).execute()


def sync_bar_events(
    bar_blocks: list[Block],
    busy_blocks: list[Block],
    planned: list[PlannedEvent],
    logs: list[str],
) -> list[Block]:
    synced_blocks = []
    for block in bar_blocks:
        ev = PlannedEvent(
            block.title,
            block.start,
            block.end,
            "[SYNC_BAR_LEMONADE]",
            block.location_type,
            "Bar Lemonadeカレンダーから同期",
        )
        if add_if_free(planned, busy_blocks, ev, logs):
            synced_blocks.append(block)
    return synced_blocks


def build_schedule(config: dict[str, Any], service, start: datetime, days: int, dry_run: bool) -> tuple[list[PlannedEvent], list[str], int]:
    logs: list[str] = []
    end = start + timedelta(days=days)
    output_id = config["calendars"]["output"]
    reference_ids = config["calendars"].get("references", [])
    bar_id = config["calendars"].get("bar_lemonade")
    calendar_ids = reference_ids

    if not dry_run:
        deleted = delete_auto_events(service, output_id, start, end)
        logs.append(f"削除: AUTO系 {deleted}件")
    else:
        logs.append("DRY RUN: Googleカレンダーには書き込みません")

    freebusy = get_freebusy(service, calendar_ids, start, end)
    output_busy = get_non_auto_calendar_blocks(service, output_id, start, end, "output")
    calendar_busy = output_busy + [block for blocks in freebusy.values() for block in blocks]
    manual_blocks = load_manual_blocks(config)
    raw_bar_events = get_raw_events(service, bar_id, start, end) if bar_id else []
    raw_bar_blocks = [block for block in (to_bar_block(event) for event in raw_bar_events) if block]
    selected_events = load_bar_selection_data(config)
    bar_blocks = [block for block in (classify_bar_block(block, config, selected_events) for block in raw_bar_blocks) if block]
    ignored_bar_count = len(raw_bar_blocks) - len(bar_blocks)
    if raw_bar_blocks:
        logs.append(f"参照のみ: Bar Lemonade {ignored_bar_count}件 / 関係予定 {len(bar_blocks)}件")
    base_busy_blocks = calendar_busy + manual_blocks
    holidays = load_holidays(config, start, days)
    routines = load_json(BASE_DIR / "routines.json", []) if config.get("routines_enabled", True) else []

    planned: list[PlannedEvent] = []
    synced_bar_blocks = sync_bar_events(bar_blocks, base_busy_blocks, planned, logs)
    busy_blocks = base_busy_blocks + synced_bar_blocks
    add_prep_and_travel(manual_blocks + synced_bar_blocks, busy_blocks, planned, logs)
    add_return_travels(manual_blocks + synced_bar_blocks, busy_blocks, planned, logs)
    add_interns(config, busy_blocks, planned, start, days, holidays, logs)
    sleep_total = add_sleep(config, busy_blocks, planned, start, days, logs)
    add_routines(routines, busy_blocks, planned, start, days, logs)
    add_rests(busy_blocks, planned, logs)

    planned.sort(key=lambda x: x.start)
    if not dry_run:
        for event in planned:
            insert_event(service, output_id, event)
    return planned, logs, sleep_total


def main() -> None:
    parser = argparse.ArgumentParser(description="Googleカレンダー個人用スケジュール自動最適化")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--start", default=None, help="YYYY-MM-DD。省略時は今日")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_json(BASE_DIR / "config.json", {})
    if not config:
        raise RuntimeError("config.json が空です。READMEに従って設定してください。")

    start_day = date.fromisoformat(args.start) if args.start else datetime.now(TZ).date()
    start = datetime.combine(start_day, time(0, 0), tzinfo=TZ)
    service = get_calendar_service(config)
    _, logs, sleep_total = build_schedule(config, service, start, args.days, args.dry_run)

    for line in logs:
        print(line)
    print(f"睡眠合計: {sleep_total // 60}時間{sleep_total % 60}分 / {args.days}日")


if __name__ == "__main__":
    main()
