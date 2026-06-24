import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: requests. Install it with: python -m pip install requests"
    ) from exc


SUBMIT_URL = "https://api.17zhiling.com/api/asr/parse-video-url"
QUERY_URL = "https://api.17zhiling.com/api/asr/task-status"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36"


def first_url(text: str) -> str:
    match = re.search(r"https?://\S+", text)
    if not match:
        return text.strip()
    return match.group(0).rstrip("，。,.!！?？）)]}'\"")


def video_id_from_url(url: str) -> str:
    match = re.search(r"/(?:video|share/video)/(\d+)", url)
    return match.group(1) if match else ""


def resolve_url(url: str) -> str:
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        return response.url or url
    except requests.RequestException:
        return url


def candidate_contents(text: str) -> tuple[list[tuple[str, str]], str]:
    url = first_url(text)
    resolved = resolve_url(url) if url.startswith("http") else url
    video_id = video_id_from_url(resolved) or video_id_from_url(url)

    candidates: list[tuple[str, str]] = []
    if video_id:
        candidates.append(
            ("douyin_web", f"https://www.douyin.com/video/{video_id}?previous_page=web_code_link")
        )
        candidates.append(("ies_share", f"https://www.iesdouyin.com/share/video/{video_id}/"))
    if url.startswith("http"):
        candidates.append(("short_or_input_url", url))
    if resolved != url and resolved.startswith("http"):
        candidates.append(("resolved_url", resolved))
    if text.strip() and text.strip() != url:
        candidates.append(("full_share_text", text.strip()))

    deduped = []
    seen = set()
    for name, content in candidates:
        if content not in seen:
            deduped.append((name, content))
            seen.add(content)
    return deduped or [("input", text.strip())], video_id


def parse_json_response(response: requests.Response) -> dict:
    response.encoding = "utf-8"
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        # Some API failures may concatenate JSON objects. Keep the first valid one.
        data, _ = json.JSONDecoder().raw_decode(response.text.strip())
        return data


def submit(api_key: str, content: str) -> dict:
    response = requests.post(
        SUBMIT_URL,
        data={"key": api_key, "videoUrl": content},
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8;"},
        timeout=90,
    )
    return parse_json_response(response)


def query(api_key: str, task_id: str) -> dict:
    response = requests.get(
        QUERY_URL,
        params={"key": api_key, "taskId": task_id},
        timeout=60,
    )
    return parse_json_response(response)


def poll(api_key: str, task_id: str, interval: int, max_wait: int) -> dict:
    deadline = time.time() + max_wait
    last = {}
    while time.time() <= deadline:
        last = query(api_key, task_id)
        data = last.get("data")
        if isinstance(data, dict) and data.get("schedule") in {"SUCCESS", "FAIL"}:
            return last
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for taskId={task_id}. Last response: {last}")


def safe_name(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_-]+", "_", value).strip("_")
    return value or str(int(time.time()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Douyin spoken copy via 17zhiling ASR API.")
    parser.add_argument("input", help="Douyin URL or full copied share text.")
    parser.add_argument(
        "--key",
        default=os.getenv("ZHILING_KEY", os.getenv("KUHUYUN_KEY", "")),
        help="17zhiling API key. Defaults to ZHILING_KEY when set.",
    )
    parser.add_argument("--out-dir", default="output", help="Directory for the final JSON.")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds.")
    parser.add_argument("--max-wait", type=int, default=240, help="Maximum polling wait in seconds.")
    parser.add_argument("--json", action="store_true", help="Print final JSON instead of a human-readable summary.")
    args = parser.parse_args()

    if not args.key:
        raise SystemExit("Missing API key. Set ZHILING_KEY or pass --key.")

    candidates, video_id = candidate_contents(args.input)
    errors = []
    final = None
    used_name = ""
    used_content = ""

    for name, content in candidates:
        try:
            submitted = submit(args.key, content)
        except Exception as exc:
            errors.append(f"{name}: request failed: {exc}")
            continue

        if submitted.get("code") != 200:
            errors.append(f"{name}: {submitted.get('msg', submitted)}")
            continue

        data = submitted.get("data")
        task_id = data if isinstance(data, str) else data.get("taskId", "") if isinstance(data, dict) else ""
        if not task_id:
            errors.append(f"{name}: missing taskId in response: {submitted}")
            continue

        try:
            final = poll(args.key, task_id, args.interval, args.max_wait)
            used_name = name
            used_content = content
            break
        except Exception as exc:
            errors.append(f"{name}: polling failed: {exc}")

    if not final:
        print("Failed to extract Douyin copy.", file=sys.stderr)
        if video_id:
            print(f"video_id: {video_id}", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    data = final.get("data", {})
    result_text = data.get("content", "") if isinstance(data, dict) else ""
    schedule = data.get("schedule", "") if isinstance(data, dict) else ""
    if schedule == "FAIL":
        print("Failed to extract Douyin copy: task schedule=FAIL.", file=sys.stderr)
        print(json.dumps(final, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    resolved_video_id = video_id
    out_id = safe_name(resolved_video_id or data.get("id", "douyin_copy"))
    out_path = Path(args.out_dir) / f"douyin_copy_{out_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(final, ensure_ascii=True, indent=2))
    else:
        print(f"schedule: {schedule}")
        print(f"source: {used_name}")
        print(f"content_used: {used_content}")
        if resolved_video_id:
            print(f"video_id: {resolved_video_id}")
        if data.get("id"):
            print(f"taskId: {data.get('id')}")
        print(f"saved_json: {out_path.resolve()}")
        print("")
        print("Transcript:")
        print(result_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
