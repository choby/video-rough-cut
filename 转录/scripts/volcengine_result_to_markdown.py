import argparse
import json
import os
import sys
from pathlib import Path


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


def non_negative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc

    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return parsed


def env_non_negative_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return non_negative_float(raw_value.strip())
    except argparse.ArgumentTypeError as exc:
        raise ValueError(f"{name} must be a number >= 0, got {raw_value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert volcengine_result.json utterances to a markdown transcript."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="volcengine_result.json",
        help="Input JSON file path. Defaults to volcengine_result.json.",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default="转录.md",
        help="Output markdown file path. Defaults to 转录.md.",
    )
    return parser


def format_seconds(milliseconds: int | float) -> str:
    return f"{float(milliseconds) / 1000:.3f}"


def load_utterances(input_path: Path) -> list[dict]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    utterances = data.get("utterances")
    if not isinstance(utterances, list):
        raise ValueError("JSON does not contain a valid 'utterances' array.")
    return utterances


def normalize_utterances(utterances: list[dict]) -> list[dict[str, float | str]]:
    normalized: list[dict[str, float | str]] = []
    for utterance in utterances:
        text = str(utterance.get("text", "")).strip()
        start_time = utterance.get("start_time")
        end_time = utterance.get("end_time")

        if not text or start_time is None or end_time is None:
            continue

        try:
            start_ms = float(start_time)
            end_ms = float(end_time)
        except (TypeError, ValueError):
            continue

        if end_ms < start_ms:
            continue

        normalized.append(
            {
                "text": text,
                "start_time": start_ms,
                "end_time": end_ms,
            }
        )
    return normalized


def adjust_utterance_boundaries(
    utterances: list[dict[str, float | str]],
    silence_threshold: float,
    silence_boundary: float,
) -> list[dict[str, float | str]]:
    if silence_boundary <= 0:
        return utterances

    adjusted: list[dict[str, float | str]] = []
    total = len(utterances)
    for index, utterance in enumerate(utterances):
        start_time = float(utterance["start_time"])
        end_time = float(utterance["end_time"])

        if index > 0:
            previous_end = float(utterances[index - 1]["end_time"])
            if start_time - previous_end >= silence_threshold:
                start_time = max(0.0, start_time - silence_boundary)

        if index + 1 < total:
            next_start = float(utterances[index + 1]["start_time"])
            if next_start - end_time >= silence_threshold:
                end_time += silence_boundary

        adjusted.append(
            {
                "text": utterance["text"],
                "start_time": start_time,
                "end_time": end_time,
            }
        )

    return adjusted


def utterance_to_line(utterance: dict[str, float | str]) -> str | None:
    text = str(utterance.get("text", "")).strip()
    start_time = utterance.get("start_time")
    end_time = utterance.get("end_time")

    if not text or start_time is None or end_time is None:
        return None

    start_text = format_seconds(start_time)
    end_text = format_seconds(end_time)
    return f"- `({start_text}-{end_text})` {text}"


def write_markdown(lines: list[str], output_path: Path) -> None:
    content = "\n".join(lines).rstrip() + "\n"
    output_path.write_text(content, encoding="utf-8")


def main() -> int:
    load_project_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        utterances = load_utterances(input_path)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        silence_threshold = env_non_negative_float("SILENCE_THRESHOLD", 500.0)
        silence_boundary = env_non_negative_float("SILENCE_BOUNDARY", 0.0)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    normalized_utterances = normalize_utterances(utterances)
    adjusted_utterances = adjust_utterance_boundaries(
        normalized_utterances,
        silence_threshold=silence_threshold,
        silence_boundary=silence_boundary,
    )
    lines = [
        line for utterance in adjusted_utterances if (line := utterance_to_line(utterance))
    ]
    write_markdown(lines, output_path)

    print(f"Wrote {len(lines)} lines to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
