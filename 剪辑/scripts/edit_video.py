import re
import subprocess
import os
import glob
import shutil
import sys

# Configuration
mp4_files = glob.glob("*.mp4")
# Ignore generated outputs from previous runs.
mp4_files = [
    f for f in mp4_files
    if not f.startswith("temp_segment_")
    and not re.match(r".*_v\d+\.mp4", f)
    and not re.match(r"片段\d+\.mp4$", f)
]
if not mp4_files:
    print("Error: No original .mp4 files found.")
    exit(1)
VIDEO_FILE = max(mp4_files, key=os.path.getsize)
VIDEO_BASENAME = os.path.splitext(VIDEO_FILE)[0]

def get_latest_task_file():
    if len(sys.argv) > 1:
        custom_file = sys.argv[1].strip()
        if custom_file.isdigit():
            custom_file = f"片段{custom_file}"
        if not custom_file.endswith(".md"):
            custom_file += ".md"
        if os.path.exists(custom_file):
            return custom_file

    # Prefer the current skill's canonical naming.
    files = glob.glob("片段*.md")
    numbered_files = []
    for path in files:
        match = re.fullmatch(r"片段(\d+)\.md", os.path.basename(path))
        if match:
            numbered_files.append((int(match.group(1)), path))
    if numbered_files:
        numbered_files.sort(key=lambda item: item[0], reverse=True)
        return numbered_files[0][1]

    # Backward compatibility with older naming conventions.
    files = glob.glob(f"{VIDEO_BASENAME}-v*_片段x.md")
    if not files:
        files = glob.glob(f"{VIDEO_BASENAME}_片段x.md")
    if not files:
        return None

    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

def get_output_video_name(task_file):
    # Extract basename from task_file (e.g. 片段1.md -> 片段1)
    base_name = os.path.basename(task_file)
    name_without_ext = os.path.splitext(base_name)[0]
    return f"{name_without_ext}.mp4"


def parse_time(time_str):
    # Format: MM:SS or S.ss or just S
    if ':' in time_str:
        parts = time_str.split(':')
        return float(parts[0]) * 60 + float(parts[1])
    return float(time_str)

def main():
    task_file = get_latest_task_file()
    if not task_file:
        print("Error: No task file found!")
        return
        
    print(f"Using task file: {task_file}")
    
    output_file = get_output_video_name(task_file)
    print(f"Output video will be: {output_file}")

    # Read task file to find keep ranges
    keep_ranges = []
    
    with open(task_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Regex to find (start-end)
    # Matches: `(start-end)`
    pattern = r'`\((.*?)-(.*?)\)`'
    matches = re.finditer(pattern, content)
    
    raw_keep_ranges = []
    for match in matches:
        start_str = match.group(1)
        end_str = match.group(2)
        start = parse_time(start_str)
        end = parse_time(end_str)
        raw_keep_ranges.append((start, end))
        print(f"Found raw segment: {start:.3f}s - {end:.3f}s")
    
    if not raw_keep_ranges:
        print("No keep segments found!")
        return

    # Merge overlapping or adjacent intervals
    raw_keep_ranges.sort(key=lambda x: x[0])
    keep_ranges = [raw_keep_ranges[0]]
    for current in raw_keep_ranges[1:]:
        previous = keep_ranges[-1]
        # Float tolerance 1e-3 to handle potential precision issues
        if current[0] <= previous[1] + 1e-3:
            keep_ranges[-1] = (previous[0], max(previous[1], current[1]))
        else:
            keep_ranges.append(current)

    print(f"\nMerged {len(raw_keep_ranges)} segments into {len(keep_ranges)} segments.")
    for start, end in keep_ranges:
        print(f"Merged keep segment: {start:.3f}s - {end:.3f}s")

    # Extract sequences individually
    temp_dir = "temp_edit_segments"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)
    
    temp_files = []
    for i, (start, end) in enumerate(keep_ranges):
        temp_file = os.path.join(temp_dir, f"seg_{i:03d}.mp4")
        temp_files.append(temp_file)
        print(f"Extracting segment {i+1}/{len(keep_ranges)}: {start:.3f}s to {end:.3f}s -> {temp_file}")
        duration = end - start
        # High precision seek before input, very fast
        cmd = [
            "ffmpeg", "-y", "-ss", str(start), #"-to", str(end),
            "-i", VIDEO_FILE,
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-crf", "18", 
            "-c:a", "aac",
            temp_file
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    # Create concat list
    list_file = os.path.join(temp_dir, "concat_list.txt")
    with open(list_file, "w", encoding='utf-8') as f:
        for temp_file in temp_files:
            # Need strict format for ffmpeg concat demuxer
            # file 'path'
            f.write(f"file '{os.path.basename(temp_file)}'\n")
            
    print(f"Generated concat demuxer list: {list_file}")
    
    # Run ffmpeg concat demuxer
    concat_cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", os.path.basename(list_file),
        "-c", "copy",
        output_file
    ]
    
    print("Running ffmpeg concat...")
    # Change working directory of ffmpeg so it can find the files specified by basename
    subprocess.run(concat_cmd, cwd=temp_dir, check=True)
    
    # Move the output video from temp_dir to the current directory
    shutil.move(os.path.join(temp_dir, output_file), output_file)
    
    # Clean up
    shutil.rmtree(temp_dir)
    print(f"Done! Output saved to {output_file}")

if __name__ == "__main__":
    main()
