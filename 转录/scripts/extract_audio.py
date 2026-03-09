import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract audio from an MP4 file with ffmpeg.")
    parser.add_argument("input", help="Input MP4 file path")
    parser.add_argument(
        "-o",
        "--output",
        help="Output audio file path. Defaults to the input basename with .mp3 extension.",
    )
    parser.add_argument(
        "--codec",
        default="libmp3lame",
        help="Audio codec for ffmpeg. Use 'copy' to keep the original audio stream.",
    )
    parser.add_argument(
        "--bitrate",
        default="192k",
        help="Audio bitrate used when re-encoding. Ignored when --codec=copy.",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        help="Optional audio sample rate, such as 16000 or 44100.",
    )
    parser.add_argument(
        "--channels",
        type=int,
        choices=[1, 2],
        help="Optional audio channel count: 1 for mono, 2 for stereo.",
    )
    return parser


def resolve_output_path(input_path: Path, output: str | None) -> Path:
    if output:
        return Path(output)
    return input_path.with_suffix(".mp3")


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise FileNotFoundError("ffmpeg is not installed or not found in PATH.")


def extract_audio(
    input_path: Path,
    output_path: Path,
    codec: str,
    bitrate: str,
    sample_rate: int | None,
    channels: int | None,
) -> None:
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-vn"]

    if codec == "copy":
        cmd.extend(["-acodec", "copy"])
    else:
        cmd.extend(["-acodec", codec, "-b:a", bitrate])
        if sample_rate is not None:
            cmd.extend(["-ar", str(sample_rate)])
        if channels is not None:
            cmd.extend(["-ac", str(channels)])

    cmd.append(str(output_path))

    subprocess.run(cmd, check=True)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        return 1

    if input_path.suffix.lower() != ".mp4":
        print(f"Error: Expected an MP4 file, got: {input_path.name}", file=sys.stderr)
        return 1

    output_path = resolve_output_path(input_path, args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        ensure_ffmpeg()
        extract_audio(
            input_path=input_path,
            output_path=output_path,
            codec=args.codec,
            bitrate=args.bitrate,
            sample_rate=args.sample_rate,
            channels=args.channels,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode

    print(f"Audio extracted to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
