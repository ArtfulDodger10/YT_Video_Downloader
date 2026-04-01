# Simple Video/Audio Downloader

A simple CLI tool built with Python using yt-dlp.

## Features

* Download videos from YouTube and other platforms
* Choose video quality (360p, 720p, 1080p)
* Extract audio as MP3
* Custom output filename/path
* Clean progress output

## Usage

Download video:
python downloader.py <url>

Download with quality:
python downloader.py <url> -q 720

Download as MP3:
python downloader.py <url> --audio

Custom filename:
python downloader.py <url> -o myvideo.mp4

Verbose mode:
python downloader.py <url> -v

## Requirements

* Python 3
* yt-dlp installed
* ffmpeg installed
