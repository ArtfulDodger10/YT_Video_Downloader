import subprocess
import os
import argparse

parser = argparse.ArgumentParser(description="Multi-Platform Video/Audio Downloader", usage="python downloader.py url [options]")  
parser.add_argument("url", help="Video URL To Download")
parser.add_argument('-o', '--output', help="Output File Name or Path (MyVideo.mp4)")
parser.add_argument('-v', '--verbose', action="store_true", help="Show Detailed Logs")
parser.add_argument("-q", "--quality", help="Maximum video quality (e.g. 360, 720, 1080)")
parser.add_argument("--audio", action="store_true", help="Download Audio Only (MP3)")
args = parser.parse_args()
cmd = ["yt-dlp", args.url]


default_path = r"C:\Users\Options\Videos\%(title)s.%(ext)s"
if not args.output:
    args.output = default_path
output_dir = os.path.dirname(args.output)


if output_dir:
    os.makedirs(output_dir, exist_ok=True)

if args.audio and args.quality:
    print("⚠️ Quality option ignored in Audio mode")	

if args.output:
    cmd.extend(["-o", args.output])

if args.audio:
	cmd.append("-x")
	cmd.extend(["--audio-format", "mp3"])
elif args.quality:
	cmd.extend(["-f", f"bv*[height<={args.quality}]+ba"])

if args.verbose:
    cmd.append("-v")
else:
    cmd.extend(["--newline", "--no-warnings", "--no-playlist", "--progress"])


cmd.extend(["--merge-output-format", "mp4"])
cmd.extend(["-N", "4"])

try:
    res = subprocess.run(cmd, check=True)
    print("\nDownload Completed ✔")
    
except subprocess.CalledProcessError as e:
    print("\nDownload Failed ❌")

