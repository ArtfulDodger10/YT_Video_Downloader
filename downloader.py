import subprocess
import os
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import re
import sys
from typing import List



def get_default_dir() -> str:
    home = Path.home()
    for candidate in ["Videos", "Downloads"]:
        p = home / candidate
        if p.exists():
            return str(p)
    return str(home)

def check_dependency(name: str) -> bool:
    return shutil.which(name) is not None

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


# main app 

class DownloaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YT Downloader")
        self.resizable(False, False)
        self.configure(bg="#111")

        self._warn_missing_deps()

        self.output_dir = tk.StringVar(value=get_default_dir())
        self.mode       = tk.StringVar(value="video")   
        self.quality    = tk.StringVar(value="best")
        self.verbose    = tk.BooleanVar(value=False)
        self._running   = False

        self._build_ui()
        self.eval('tk::PlaceWindow . center')

    # dependency warnings 

    def _warn_missing_deps(self):
        missing = []
        if not check_dependency("yt-dlp"):
            missing.append("• yt-dlp   →  pip install yt-dlp")
        if not check_dependency("ffmpeg"):
            missing.append("• ffmpeg   →  https://ffmpeg.org/download.html")
        if missing:
            messagebox.showwarning(
                "Missing Dependencies",
                "The following tools are not on your PATH:\n\n"
                + "\n".join(missing)
                + "\n\nInstall them before downloading."
            )

    # UI 

    def _build_ui(self):
        C = {
            "bg":      "#111111",
            "surface": "#1a1a1a",
            "border":  "#2a2a2a",
            "accent":  "#b5f544",
            "text":    "#f0f0f0",
            "muted":   "#666666",
            "danger":  "#ff5555",
            "success": "#55ff99",
        }
        FONT_LABEL = ("Courier New", 9, "bold")
        FONT_BODY  = ("Segoe UI", 10) if sys.platform == "win32" else ("Helvetica", 11)
        FONT_MONO  = ("Courier New", 9)
        FONT_TITLE = ("Courier New", 18, "bold")

        PAD = {"padx": 20, "pady": 6}

        # title
        title_frame = tk.Frame(self, bg=C["bg"], pady=18)
        title_frame.pack(fill="x")
        tk.Label(title_frame, text="YT.DOWN", font=FONT_TITLE,
                 bg=C["bg"], fg=C["accent"]).pack()
        tk.Label(title_frame, text="yt-dlp powered · local · multi-platform",
                 font=("Courier New", 8), bg=C["bg"], fg=C["muted"]).pack()

        sep = tk.Frame(self, height=1, bg=C["border"])
        sep.pack(fill="x")

        body = tk.Frame(self, bg=C["bg"], padx=24, pady=16)
        body.pack(fill="both")

        self._label(body, C, FONT_LABEL, "SAVE TO")
        dir_row = tk.Frame(body, bg=C["bg"])
        dir_row.pack(fill="x", pady=(2, 10))

        dir_entry = tk.Entry(dir_row, textvariable=self.output_dir,
                             bg=C["surface"], fg=C["text"], insertbackground=C["text"],
                             relief="flat", font=FONT_MONO,
                             highlightthickness=1, highlightbackground=C["border"],
                             highlightcolor=C["accent"])
        dir_entry.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)

        tk.Button(dir_row, text=" Browse ", command=self._browse,
                  bg=C["surface"], fg=C["text"], relief="flat",
                  font=FONT_MONO, cursor="hand2",
                  activebackground=C["border"], activeforeground=C["accent"]
                  ).pack(side="left", padx=(6, 0))

        # URL 
        self._label(body, C, FONT_LABEL, "VIDEO URL")
        self.url_var = tk.StringVar()
        url_entry = tk.Entry(body, textvariable=self.url_var,
                             bg=C["surface"], fg=C["text"], insertbackground=C["text"],
                             relief="flat", font=FONT_BODY,
                             highlightthickness=1, highlightbackground=C["border"],
                             highlightcolor=C["accent"])
        url_entry.pack(fill="x", ipady=6, ipadx=6, pady=(2, 10))

        # mode toggle ──
        self._label(body, C, FONT_LABEL, "MODE")
        mode_row = tk.Frame(body, bg=C["bg"])
        mode_row.pack(fill="x", pady=(2, 10))
        self._mode_btns = {}
        for val, label in [("video", "⬛  Video (MP4)"), ("audio", "◈  Audio only (MP3)")]:
            b = tk.Button(mode_row, text=label, command=lambda v=val: self._set_mode(v),
                          bg=C["surface"], fg=C["muted"], relief="flat",
                          font=("Courier New", 9), cursor="hand2", width=18,
                          activebackground=C["border"], activeforeground=C["accent"])
            b.pack(side="left", padx=(0, 6), ipady=5)
            self._mode_btns[val] = b

        self._quality_frame = tk.Frame(body, bg=C["bg"])
        self._quality_frame.pack(fill="x")
        self._label(self._quality_frame, C, FONT_LABEL, "MAX QUALITY")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TCombobox",
                        fieldbackground=C["surface"], background=C["surface"],
                        foreground=C["text"], arrowcolor=C["muted"],
                        bordercolor=C["border"], selectbackground=C["surface"],
                        selectforeground=C["text"])
        qual_combo = ttk.Combobox(self._quality_frame, textvariable=self.quality,
                                  values=["best", "1080", "720", "480", "360"],
                                  state="readonly", style="Dark.TCombobox", font=FONT_BODY)
        qual_combo.pack(fill="x", pady=(2, 10), ipady=3)

        self._set_mode("video")  # now safe — quality frame exists

        # verbose checkbox 
        chk = tk.Checkbutton(body, text="Show verbose logs in console",
                              variable=self.verbose,
                              bg=C["bg"], fg=C["muted"], selectcolor=C["surface"],
                              activebackground=C["bg"], activeforeground=C["text"],
                              font=("Courier New", 8), relief="flat", cursor="hand2")
        chk.pack(anchor="w", pady=(0, 12))

        # ── download button ──
        self.dl_btn = tk.Button(body, text="  DOWNLOAD  ",
                                command=self._start_download,
                                bg=C["accent"], fg="#111", relief="flat",
                                font=("Courier New", 11, "bold"), cursor="hand2",
                                activebackground="#9ed43a", activeforeground="#111")
        self.dl_btn.pack(fill="x", ipady=9, pady=(4, 0))

        #list formats button 
        tk.Button(body, text="List available formats",
                  command=self._list_formats,
                  bg=C["surface"], fg=C["muted"], relief="flat",
                  font=("Courier New", 8), cursor="hand2",
                  activebackground=C["border"], activeforeground=C["text"]
                  ).pack(pady=(6, 0))

        sep2 = tk.Frame(self, height=1, bg=C["border"])
        sep2.pack(fill="x", pady=(12, 0))

        log_frame = tk.Frame(self, bg=C["bg"], padx=24, pady=12)
        log_frame.pack(fill="both")

        self.status_text = tk.Text(log_frame, height=6, bg=C["surface"], fg=C["muted"],
                                   insertbackground=C["text"], relief="flat",
                                   font=FONT_MONO, wrap="word", state="disabled",
                                   highlightthickness=0)
        self.status_text.pack(fill="x")
        self.status_text.tag_config("ok",      foreground=C["success"])
        self.status_text.tag_config("err",     foreground=C["danger"])
        self.status_text.tag_config("info",    foreground=C["muted"])
        self.status_text.tag_config("heading", foreground=C["accent"])

        self._log("Ready. Enter a URL and click DOWNLOAD.", "info")
        self.C = C

    def _label(self, parent, C, font, text):
        tk.Label(parent, text=text, font=font, bg=C["bg"], fg=C["muted"],
                 anchor="w").pack(fill="x", pady=(6, 0))

    # mode ──────────────────────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        self.mode.set(mode)
        C = getattr(self, "C", {})
        accent  = C.get("accent", "#b5f544")
        surface = C.get("surface", "#1a1a1a")
        muted   = C.get("muted", "#666")
        acc_dim = "#1f2e0a"

        for val, btn in self._mode_btns.items():
            if val == mode:
                btn.config(bg=acc_dim, fg=accent)
            else:
                btn.config(bg=surface, fg=muted)

        if mode == "audio":
            self._quality_frame.pack_forget()
        else:
            self._quality_frame.pack(fill="x")

    # log 

    def _log(self, msg: str, tag: str = "info"):
        self.status_text.config(state="normal")
        self.status_text.insert("end", msg + "\n", tag)
        self.status_text.see("end")
        self.status_text.config(state="disabled")

    def _clear_log(self):
        self.status_text.config(state="normal")
        self.status_text.delete("1.0", "end")
        self.status_text.config(state="disabled")


    def _browse(self):
        chosen = filedialog.askdirectory(initialdir=self.output_dir.get(), title="Choose download folder")
        if chosen:
            self.output_dir.set(chosen)

    # build yt-dlp command 

    def _build_cmd(self, url: str) -> List[str]:
        out_dir  = self.output_dir.get().strip()
        mode     = self.mode.get()
        quality  = self.quality.get()
        verbose  = self.verbose.get()

        output_template = os.path.join(out_dir, "%(title)s.%(ext)s")
        os.makedirs(out_dir, exist_ok=True)

        cmd = [
            "yt-dlp", url,
            "-o", output_template,
            "--restrict-filenames",   
            "--no-playlist",
            "-N", "4",
        ]

        if mode == "audio":
            cmd += ["-x", "--audio-format", "mp3"]
        else:
            if quality != "best":
                cmd += ["-f", f"bv*[height<={quality}]+ba/b[height<={quality}]"]
            cmd += ["--merge-output-format", "mp4"]

        if verbose:
            cmd.append("-v")
        else:
            cmd += ["--newline", "--no-warnings", "--progress"]

        return cmd

    # download 

    def _start_download(self):
        if self._running:
            return

        url     = self.url_var.get().strip()
        out_dir = self.output_dir.get().strip()

        if not url:
            messagebox.showwarning("Missing URL", "Please enter a video URL.")
            return
        if not out_dir:
            messagebox.showwarning("Missing Folder", "Please choose a download folder.")
            return
        if not check_dependency("yt-dlp"):
            messagebox.showerror("Not Found", "yt-dlp is not installed.\nRun: pip install yt-dlp")
            return

        self._clear_log()
        self._log(f"Downloading: {url}", "heading")
        self._log(f"To: {out_dir}", "info")
        self.dl_btn.config(state="disabled", text="  DOWNLOADING…  ")
        self._running = True

        threading.Thread(target=self._run_download, args=(url,), daemon=True).start()

    def _run_download(self, url: str):
        cmd = self._build_cmd(url)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            if result.returncode == 0:
                self.after(0, lambda: self._log("\n✔  Download complete!", "ok"))
            else:
                err = (result.stderr or result.stdout or "Unknown error").strip()
                self.after(0, lambda: self._log(f"\n✗  Failed:\n{err}", "err"))
        except FileNotFoundError:
            self.after(0, lambda: self._log(
                "✗  yt-dlp not found. Install it:\n   pip install yt-dlp", "err"))
        except Exception as e:
            self.after(0, lambda: self._log(f"✗  Unexpected error: {e}", "err"))
        finally:
            self.after(0, self._reset_btn)

    def _reset_btn(self):
        self.dl_btn.config(state="normal", text="  DOWNLOAD  ")
        self._running = False

    #list formats 

    def _list_formats(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Enter a URL first.")
            return
        if not check_dependency("yt-dlp"):
            messagebox.showerror("Not Found", "yt-dlp is not installed.")
            return

        self._clear_log()
        self._log("Fetching available formats…", "info")

        def run():
            try:
                result = subprocess.run(
                    ["yt-dlp", "-F", "--no-warnings", url],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30
                )
                output = result.stdout or result.stderr or "No output."
                self.after(0, lambda: self._log(output, "info"))
            except Exception as e:
                self.after(0, lambda: self._log(f"✗ Error: {e}", "err"))

        threading.Thread(target=run, daemon=True).start()



if __name__ == "__main__":
    app = DownloaderApp()
    app.mainloop()


