from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from main import (
    build_schedule,
    get_calendar_service,
    get_raw_events,
    load_bar_selection_data,
    load_json,
    load_manual_data,
    save_bar_selection_data,
    save_manual_data,
    using_sheets_storage,
)


BASE_DIR = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Tokyo")

LOCATION_OPTIONS = {
    "オンライン": ("online", 0),
    "自宅": ("home", 0),
    "自宅周辺": ("near_home", 30),
    "1時間圏": ("outside_home_1h", 60),
    "1.5時間圏": ("outside_home_1_5h", 90),
}
TYPE_OPTIONS = ["飲み会", "遊び", "デート", "インターン", "バー", "大学", "その他"]
OPTIONAL_BAR_TYPES = ["ミーティング", "飲み会", "遊び", "大学", "その他"]
DURATION_OPTIONS = {
    "30分": 30,
    "1時間": 60,
    "1.5時間": 90,
    "2時間": 120,
    "3時間": 180,
    "4時間": 240,
    "6時間": 360,
    "8時間": 480,
}


def is_required_bar_event(title: str, config: dict) -> bool:
    filters = config.get("bar_lemonade_filters", {})
    return any(name in title for name in filters.get("shift_names", [])) or any(
        required in title for required in filters.get("required_titles", [])
    )


def load_blocks() -> list[dict]:
    config = load_json(BASE_DIR / "config.json", {})
    return load_manual_data(config)


def save_blocks(blocks: list[dict]) -> None:
    config = load_json(BASE_DIR / "config.json", {})
    save_manual_data(config, blocks)


def load_selections() -> dict:
    config = load_json(BASE_DIR / "config.json", {})
    return load_bar_selection_data(config)


def save_selections(selections: dict) -> None:
    config = load_json(BASE_DIR / "config.json", {})
    save_bar_selection_data(config, selections)


def dt(day: date, value: time) -> datetime:
    return datetime.combine(day, value, tzinfo=TZ)


st.set_page_config(page_title="Routine Scheduler", page_icon="Calendar", layout="wide")
st.title("個人用スケジュール自動最適化")
app_config = load_json(BASE_DIR / "config.json", {})
storage_label = "Google Sheets" if using_sheets_storage(app_config) else "ローカルJSON"
st.caption(f"保存先: {storage_label}")

manual_tab, bar_tab, run_tab = st.tabs(["手動予定", "Bar予定選択", "スケジュール生成"])

with manual_tab:
    blocks = load_blocks()

    with st.form("manual_block"):
        st.subheader("手動予定を追加")
        col1, col2, col3 = st.columns(3)
        with col1:
            input_date = st.date_input("日付", value=date.today())
            start_time = st.time_input("開始時間", value=time(20, 0), step=timedelta(minutes=15))
        with col2:
            duration_label = st.radio("時間", list(DURATION_OPTIONS.keys()), horizontal=True)
            location_label = st.radio("場所", list(LOCATION_OPTIONS.keys()), horizontal=True)
        with col3:
            type_label = st.radio("内容", TYPE_OPTIONS, horizontal=True)
            title = st.text_input("タイトル", value=type_label)
            requires_preparation = st.checkbox("外出準備1時間を入れる", value=location_label not in {"自宅"})

        submitted = st.form_submit_button("保存")

    if submitted:
        location_type, travel_min = LOCATION_OPTIONS[location_label]
        start = dt(input_date, start_time)
        end = start + timedelta(minutes=DURATION_OPTIONS[duration_label])
        block = {
            "title": title,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "type": type_label,
            "location_type": location_type,
            "travel_min": travel_min,
            "requires_preparation": bool(requires_preparation),
        }
        blocks.append(block)
        save_blocks(blocks)
        st.success("保存しました")
        st.rerun()

    st.subheader("登録済み手動予定")
    if not blocks:
        st.info("まだ手動予定はありません。")
    else:
        for index, block in enumerate(sorted(blocks, key=lambda x: x["start"])):
            cols = st.columns([3, 3, 2, 2, 1])
            cols[0].write(block["title"])
            cols[1].write(f'{block["start"]} - {block["end"]}')
            cols[2].write(block.get("type", ""))
            cols[3].write(block.get("location_type", ""))
            if cols[4].button("削除", key=f"delete-{index}"):
                original_index = blocks.index(block)
                blocks.pop(original_index)
                save_blocks(blocks)
                st.rerun()

    st.caption("保存後、main.py を実行すると準備・移動・睡眠・ルーティンと統合されます。")

with bar_tab:
    st.subheader("Bar Lemonade予定を選択")
    config = load_json(BASE_DIR / "config.json", {})
    selections = load_selections()
    days = st.number_input("表示日数", min_value=1, max_value=60, value=14, step=1)

    if st.button("Bar予定を読み込む"):
        service = get_calendar_service(config)
        start = datetime.combine(date.today(), time(0, 0), tzinfo=TZ)
        end = start + timedelta(days=int(days))
        events = get_raw_events(service, config["calendars"]["bar_lemonade"], start, end)
        st.session_state["bar_events"] = events

    events = st.session_state.get("bar_events", [])
    optional_events = [
        event
        for event in events
        if event.get("start", {}).get("dateTime")
        and event.get("end", {}).get("dateTime")
        and not is_required_bar_event(event.get("summary", ""), config)
    ]

    if not optional_events:
        st.info("選択可能なBar予定はまだ読み込まれていません。")
    else:
        with st.form("bar_event_selection"):
            updated = {}
            for event in optional_events:
                event_id = event["id"]
                title = event.get("summary", "(no title)")
                start = datetime.fromisoformat(event["start"]["dateTime"]).astimezone(TZ)
                end = datetime.fromisoformat(event["end"]["dateTime"]).astimezone(TZ)
                existing = selections.get(event_id, {})

                st.divider()
                cols = st.columns([4, 2, 2, 2])
                include = cols[0].checkbox(
                    f"{start:%m/%d %H:%M}-{end:%H:%M} {title}",
                    value=bool(existing.get("include", False)),
                    key=f"include-{event_id}",
                )
                selected_type = cols[1].selectbox(
                    "内容",
                    OPTIONAL_BAR_TYPES,
                    index=OPTIONAL_BAR_TYPES.index(existing.get("type", "ミーティング"))
                    if existing.get("type", "ミーティング") in OPTIONAL_BAR_TYPES
                    else 0,
                    key=f"type-{event_id}",
                )
                location_keys = list(LOCATION_OPTIONS.keys())
                existing_location = existing.get("location_type", "online")
                location_index = next(
                    (i for i, label in enumerate(location_keys) if LOCATION_OPTIONS[label][0] == existing_location),
                    0,
                )
                location_label = cols[2].selectbox(
                    "場所",
                    location_keys,
                    index=location_index,
                    key=f"location-{event_id}",
                )
                prep = cols[3].checkbox(
                    "準備",
                    value=bool(existing.get("requires_preparation", False)),
                    key=f"prep-{event_id}",
                )
                location_type, travel_min = LOCATION_OPTIONS[location_label]
                if include:
                    updated[event_id] = {
                        "include": True,
                        "title": title,
                        "type": selected_type,
                        "location_type": location_type,
                        "travel_min": travel_min,
                        "requires_preparation": prep,
                    }

            saved = st.form_submit_button("選択を保存")
        if saved:
            save_selections(updated)
            st.success("保存しました")
            st.rerun()

with run_tab:
    st.subheader("スケジュール生成")
    config = load_json(BASE_DIR / "config.json", {})
    col1, col2 = st.columns([1, 2])
    with col1:
        start_day = st.date_input("開始日", value=date.today(), key="run-start-day")
        days = st.number_input("対象日数", min_value=1, max_value=60, value=14, step=1, key="run-days")
    with col2:
        st.write("dry-runはGoogleカレンダーに書き込まず、追加・スキップ・警告だけ確認します。")
        st.write("本番反映はAUTO系予定を削除してから、生成結果をGoogleカレンダーへ追加します。")

    dry_run_clicked = st.button("dry-runで確認", type="secondary")
    apply_clicked = st.button("Googleカレンダーへ反映", type="primary")

    if dry_run_clicked or apply_clicked:
        dry_run = dry_run_clicked
        start = datetime.combine(start_day, time(0, 0), tzinfo=TZ)
        with st.spinner("Googleカレンダーを読み込み、スケジュールを生成しています..."):
            try:
                service = get_calendar_service(config)
                _, logs, sleep_total = build_schedule(config, service, start, int(days), dry_run=dry_run)
            except Exception as exc:
                st.error(f"実行に失敗しました: {exc}")
            else:
                if dry_run:
                    st.success("dry-runが完了しました。Googleカレンダーには書き込んでいません。")
                else:
                    st.success("Googleカレンダーへ反映しました。")

                added = [line for line in logs if line.startswith("追加:")]
                skipped = [line for line in logs if line.startswith("スキップ:")]
                warnings = [line for line in logs if line.startswith("警告:")]
                other = [line for line in logs if not line.startswith(("追加:", "スキップ:", "警告:"))]

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("追加", len(added))
                m2.metric("スキップ", len(skipped))
                m3.metric("警告", len(warnings))
                m4.metric("睡眠合計", f"{sleep_total // 60}時間{sleep_total % 60}分")

                if warnings:
                    st.warning("\n".join(warnings))

                with st.expander("追加", expanded=True):
                    st.code("\n".join(added) if added else "追加はありません。", language="text")
                with st.expander("スキップ"):
                    st.code("\n".join(skipped) if skipped else "スキップはありません。", language="text")
                with st.expander("その他"):
                    st.code("\n".join(other) if other else "その他ログはありません。", language="text")
