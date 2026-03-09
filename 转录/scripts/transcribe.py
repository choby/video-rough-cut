import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import ssl


VOLCENGINE_SUBMIT_ENDPOINT = "https://openspeech.bytedance.com/api/v1/vc/submit"
VOLCENGINE_QUERY_ENDPOINT = "https://openspeech.bytedance.com/api/v1/vc/query"
VOLCENGINE_SUBMIT_PARAMS = {
    "language": "zh-CN",
    "use_itn": "True",
    "use_capitalize": "True",
    "max_lines": "1",
    "words_per_line": "15",
}
VOLCENGINE_SUCCESS_CODE = 0
VOLCENGINE_PROCESSING_CODE = 1000


def parse_dotenv_value(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]
    return value


def load_dotenv_file(dotenv_path: Path) -> None:
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = parse_dotenv_value(value)


def find_project_dotenv() -> Path | None:
    candidates = []
    cwd = Path.cwd().resolve()
    candidates.extend([cwd, *cwd.parents])

    script_dir = Path(__file__).resolve().parent
    candidates.extend([script_dir, *script_dir.parents])

    seen = set()
    for root in candidates:
        if root in seen:
            continue
        seen.add(root)
        dotenv_path = root / ".env"
        if dotenv_path.is_file():
            return dotenv_path
    return None


def load_project_dotenv() -> Path | None:
    dotenv_path = find_project_dotenv()
    if dotenv_path is not None:
        load_dotenv_file(dotenv_path)
    return dotenv_path


def env_default(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def normalize_region(region: str) -> str:
    value = region.strip()
    value = value.removeprefix("https://").removeprefix("http://")
    value = value.split("/", 1)[0]
    value = value.removesuffix(".aliyuncs.com")
    value = value.removeprefix("oss-")
    return value


def normalize_endpoint_host(endpoint: str | None, bucket: str | None = None) -> str | None:
    if not endpoint:
        return None

    value = endpoint.strip()
    value = value.removeprefix("https://").removeprefix("http://")
    value = value.split("/", 1)[0].rstrip("/")

    if bucket and value.startswith(f"{bucket}."):
        value = value[len(bucket) + 1 :]

    return value or None


def build_public_url(bucket: str, region: str, key: str, endpoint: str | None) -> str:
    quoted_key = quote(key, safe="/-_.~")
    endpoint_host = normalize_endpoint_host(endpoint, bucket=bucket)
    if endpoint_host:
        return f"https://{bucket}.{endpoint_host}/{quoted_key}"
    return f"https://{bucket}.oss-{region}.aliyuncs.com/{quoted_key}"


def timestamped_name(local_path: Path) -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"{local_path.stem}-{stamp}{local_path.suffix.lower()}"


def build_object_key(local_path: Path, explicit_key: str | None, prefix: str) -> str:
    base_name = timestamped_name(local_path)
    if explicit_key:
        explicit = explicit_key.strip().lstrip("/")
        explicit_path = Path(explicit)
        filename = explicit_path.name
        suffix = Path(filename).suffix or local_path.suffix.lower()
        filename_stem = Path(filename).stem
        stamped_filename = f"{filename_stem}-{dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}{suffix}"
        parent = explicit_path.parent.as_posix()
        return f"{parent}/{stamped_filename}" if parent and parent != "." else stamped_filename

    cleaned_prefix = prefix.strip("/")
    if cleaned_prefix:
        return f"{cleaned_prefix}/{base_name}"
    return base_name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload audio.wav to Alibaba Cloud OSS and run Volcengine async transcription."
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="audio.wav",
        help="Local file path to upload. Defaults to audio.wav.",
    )
    parser.add_argument(
        "--bucket",
        default=env_default("OSS_BUCKET"),
        help="OSS bucket name. Defaults to OSS_BUCKET from .env or environment.",
    )
    parser.add_argument(
        "--region",
        default=env_default("OSS_REGION"),
        help="OSS region, such as cn-hangzhou. Defaults to OSS_REGION from .env or environment.",
    )
    parser.add_argument(
        "--endpoint",
        default=env_default("OSS_ENDPOINT"),
        help="Optional OSS endpoint host, such as oss-cn-hangzhou.aliyuncs.com.",
    )
    parser.add_argument(
        "--key",
        default=env_default("OSS_OBJECT_KEY"),
        help="Optional object key template. A timestamp suffix is always added before upload.",
    )
    parser.add_argument(
        "--prefix",
        default=env_default("OSS_OBJECT_PREFIX", ""),
        help="Optional object key prefix, for example uploads/audio/.",
    )
    parser.add_argument(
        "--sign-seconds",
        type=int,
        default=int(env_default("OSS_SIGN_SECONDS", "3600")),
        help="Presigned GET URL validity in seconds.",
    )
    parser.add_argument(
        "--skip-transcribe",
        action="store_true",
        help="Upload only and skip Volcengine transcription.",
    )
    parser.add_argument(
        "--result-json",
        default=env_default("VOLCENGINE_RESULT_JSON", "volcengine_result.json"),
        help="Output JSON file for Volcengine query result.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=int(env_default("VOLCENGINE_MAX_ATTEMPTS", "120")),
        help="Maximum query attempts while waiting for completion.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(env_default("VOLCENGINE_POLL_INTERVAL", "5")),
        help="Seconds between Volcengine query attempts.",
    )
    parser.add_argument(
        "--hot-words-file",
        default=env_default(
            "VOLCENGINE_HOT_WORDS_FILE",
            str(Path(__file__).resolve().parent.parent / "字幕" / "词典.txt"),
        ),
        help="Optional hot-words dictionary file, one word per line.",
    )
    return parser


def load_oss_sdk():
    try:
        import alibabacloud_oss_v2 as oss
    except ImportError as exc:
        raise RuntimeError(
            "Package alibabacloud-oss-v2 is not installed. Run: pip install alibabacloud-oss-v2"
        ) from exc
    return oss


def create_client(oss, region: str, endpoint_host: str | None):
    credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()
    cfg = oss.config.load_default()
    cfg.credentials_provider = credentials_provider
    cfg.region = region
    if endpoint_host:
        cfg.endpoint = endpoint_host
    return oss.Client(cfg)


def upload_file(client, oss, bucket: str, key: str, local_path: Path):
    return client.put_object_from_file(
        oss.PutObjectRequest(
            bucket=bucket,
            key=key,
        ),
        str(local_path),
    )


def build_signed_url(client, oss, bucket: str, key: str, sign_seconds: int) -> str:
    result = client.presign(
        oss.GetObjectRequest(bucket=bucket, key=key),
        expires=dt.timedelta(seconds=sign_seconds),
    )
    return result.url


def load_hot_words(hot_words_path: Path) -> list[str]:
    if not hot_words_path.is_file():
        return []

    words: list[str] = []
    for raw_line in hot_words_path.read_text(encoding="utf-8").splitlines():
        word = raw_line.strip()
        if word:
            words.append(word)
    return words


def extract_first_key(payload: object, key: str) -> object | None:
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = extract_first_key(value, key)
            if found is not None:
                return found
        return None
    if isinstance(payload, list):
        for item in payload:
            found = extract_first_key(item, key)
            if found is not None:
                return found
    return None


def request_json(
    method: str,
    url: str,
    api_key: str,
    payload: dict | None = None,
    timeout_seconds: int = 30,
) -> tuple[object | None, str]:
    request_body = None
    headers = {
        "Accept": "*/*",
        "x-api-key": api_key,
        "Connection": "keep-alive",
    }
    if payload is not None:
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["content-type"] = "application/json"

    request = Request(url=url, data=request_body, headers=headers, method=method.upper())
    try:
        # Create SSL context that doesn't verify certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        with urlopen(request, timeout=timeout_seconds, context=ssl_context) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = body or str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"request failed: {reason}") from exc

    try:
        parsed_response = json.loads(raw_response)
    except json.JSONDecodeError:
        parsed_response = None

    return parsed_response, raw_response


def extract_task_id(parsed_response: object | None, raw_response: str) -> str | None:
    task_id = extract_first_key(parsed_response, "id")
    if task_id is not None:
        value = str(task_id).strip()
        if value:
            return value

    match = re.search(r'"id"\s*:\s*"([^"]+)"', raw_response)
    if match:
        return match.group(1)
    return None


def extract_status_code(parsed_response: object | None, raw_response: str) -> int | None:
    code = extract_first_key(parsed_response, "code")
    if code is not None:
        try:
            return int(code)
        except (TypeError, ValueError):
            pass

    match = re.search(r'"code"\s*:\s*([0-9]+)', raw_response)
    if match:
        return int(match.group(1))
    return None


def count_utterances(parsed_response: object | None, raw_response: str) -> int:
    if isinstance(parsed_response, dict):
        utterances = parsed_response.get("utterances")
        if isinstance(utterances, list):
            return len(utterances)
    return raw_response.count('"text"')


def submit_volcengine_task(audio_url: str, api_key: str, hot_words: list[str]) -> str:
    request_body = {"url": audio_url}
    if hot_words:
        request_body["hot_words"] = hot_words

    submit_url = f"{VOLCENGINE_SUBMIT_ENDPOINT}?{urlencode(VOLCENGINE_SUBMIT_PARAMS)}"
    parsed_response, raw_response = request_json(
        method="POST",
        url=submit_url,
        api_key=api_key,
        payload=request_body,
    )

    task_id = extract_task_id(parsed_response, raw_response)
    if not task_id:
        raise RuntimeError(f"submit failed, response:\n{raw_response}")
    return task_id


def query_volcengine_task(task_id: str, api_key: str) -> tuple[object | None, str]:
    query_url = f"{VOLCENGINE_QUERY_ENDPOINT}?{urlencode({'id': task_id})}"
    return request_json(
        method="GET",
        url=query_url,
        api_key=api_key,
    )


def wait_for_volcengine_result(
    task_id: str,
    api_key: str,
    max_attempts: int,
    poll_interval: float,
) -> tuple[object | None, str]:
    printed_dots = False
    for _ in range(max_attempts):
        time.sleep(poll_interval)
        parsed_response, raw_response = query_volcengine_task(task_id, api_key)
        status = extract_status_code(parsed_response, raw_response)

        if status == VOLCENGINE_SUCCESS_CODE:
            if printed_dots:
                print()
            return parsed_response, raw_response

        if status == VOLCENGINE_PROCESSING_CODE:
            print(".", end="", flush=True)
            printed_dots = True
            continue

        if printed_dots:
            print()
        raise RuntimeError(f"transcribe failed, response:\n{raw_response}")

    if printed_dots:
        print()
    raise TimeoutError("timeout, task not completed")


def write_json_result(output_path: Path, raw_response: str) -> None:
    output_text = raw_response if raw_response.endswith("\n") else f"{raw_response}\n"
    output_path.write_text(output_text, encoding="utf-8")


def main() -> int:
    dotenv_path = load_project_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    local_path = Path(args.file).expanduser().resolve()
    if not local_path.is_file():
        print(f"Error: file not found: {local_path}", file=sys.stderr)
        return 1

    if not args.bucket:
        print("Error: missing OSS bucket. Set --bucket or OSS_BUCKET.", file=sys.stderr)
        return 1

    if not args.region:
        print("Error: missing OSS region. Set --region or OSS_REGION.", file=sys.stderr)
        return 1

    normalized_region = normalize_region(args.region)
    endpoint_host = normalize_endpoint_host(args.endpoint, bucket=args.bucket)
    object_key = build_object_key(local_path, args.key, args.prefix)

    try:
        oss = load_oss_sdk()
        client = create_client(oss, normalized_region, endpoint_host)
        result = upload_file(client, oss, args.bucket, object_key, local_path)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: upload failed: {exc}", file=sys.stderr)
        return 1

    object_url = build_public_url(args.bucket, normalized_region, object_key, endpoint_host)
    print(f"Uploaded: {local_path}")
    if dotenv_path is not None:
        print(f"Loaded .env: {dotenv_path}")
    print(f"Bucket: {args.bucket}")
    print(f"Region: {normalized_region}")
    if endpoint_host:
        print(f"Endpoint: {endpoint_host}")
    print(f"Object Key: {object_key}")
    print(f"ETag: {getattr(result, 'etag', '')}")
    print(f"Object URL: {object_url}")

    try:
        signed_url = build_signed_url(client, oss, args.bucket, object_key, args.sign_seconds)
        print(f"Signed URL ({args.sign_seconds}s): {signed_url}")
    except Exception as exc:
        print(f"Warning: failed to generate signed URL: {exc}", file=sys.stderr)

    if args.skip_transcribe:
        print(object_url)
        return 0

    if args.max_attempts <= 0:
        print("Error: --max-attempts must be > 0", file=sys.stderr)
        return 1

    if args.poll_interval <= 0:
        print("Error: --poll-interval must be > 0", file=sys.stderr)
        return 1

    api_key = env_default("VOLCENGINE_API_KEY")
    if not api_key:
        print("Error: missing VOLCENGINE_API_KEY in .env or environment.", file=sys.stderr)
        return 1

    hot_words_file = Path(args.hot_words_file).expanduser()
    hot_words = load_hot_words(hot_words_file)

    print("Submitting Volcengine transcription task...")
    print(f"Audio URL: {object_url}")
    if hot_words:
        print(f"Loaded hot words: {len(hot_words)} from {hot_words_file.resolve()}")

    try:
        task_id = submit_volcengine_task(object_url, api_key, hot_words)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Task submitted: {task_id}")
    print("Waiting for transcription result...")

    try:
        parsed_response, raw_response = wait_for_volcengine_result(
            task_id=task_id,
            api_key=api_key,
            max_attempts=args.max_attempts,
            poll_interval=args.poll_interval,
        )
    except (RuntimeError, TimeoutError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    result_output_path = Path(args.result_json).expanduser().resolve()
    write_json_result(result_output_path, raw_response)
    utterance_count = count_utterances(parsed_response, raw_response)
    print(f"Transcription completed, result saved to {result_output_path}")
    print(f"Recognized utterances: {utterance_count}")

    print(object_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
