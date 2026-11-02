# Dubbly: notes for Claude Code

Dubbly is a Windows desktop program (Python 3.10–3.13, PySide6) that translates and dubs videos locally:
ffmpeg → faster-whisper (speech recognition) → translator (NLLB-200 / Opus-MT / MADLAD-400 through
CTranslate2) → Piper (speech synthesis) → ffmpeg (new audio track, picture copied without re-encoding).
Videos of any size work because everything is streamed. Version shown in the UI: "Build v. 1.0"
(`vt/__init__.py`). The project was written by Claude together with its owner; the owner tests every
build on Windows and reports problems. **The owner writes in Russian and has little Python experience:
answer in Russian, explain simply, make small steps.**

## Run, build, check

- Run from source: `start.bat` (creates `.venv`, installs `requirements.txt`) or `python main.py`.
  `start_debug.bat` runs with a console so errors stay visible.
- Build: GitHub Actions workflow **Build Windows exe** (`.github/workflows/build.yml`): PyInstaller →
  `installer/dubbly.iss` (Inno Setup) → artifact `Dubbly-Setup`; if the installer step fails the plain
  folder is uploaded as `Dubbly-windows`. Local build: `build.bat` → `dist\Dubbly\Dubbly.exe`.
- `python tools/check_locales.py` verifies `assets/locales/*.json` against the strings in the code
  (missing/obsolete strings, placeholders, numbers, technical words). Run it after touching any `_()` text.
- `python tools/make_ui_assets.py` (needs Pillow) redraws `assets/ui/*.png` (switches, arrows, reset icon)
  after theme colors change.
- There is **no automated test suite in the repo**. During development the logic was checked with throwaway
  scripts (a fake Qt layer plus stubbed models, since Windows, a GPU and Hugging Face were not available).
  If you can run the real program, prefer that, and consider adding real tests.

## Layout (`vt/`)

- `gui.py` window (cards; settings left, progress right on wide screens), `theme.py` dark/light QSS,
  `splash.py` + `startup.py` startup screen, `i18n.py` localization, `fonts.py`, `voices.py` (own Piper voices),
  `preview.py` (voice samples, `winsound`).
- `runner.py` runs the job in a **child process** (spawn; `multiprocessing.freeze_support()` in `main.py`);
  cancel kills the whole process tree (`taskkill /T`). `pipeline.py` is the job itself, `asr.py` recognition,
  `translate.py` translators, `tts.py` Piper, `ffmpeg_utils.py`, `cuda_libs.py` (GPU), `common.py`
  (settings, app dirs, downloads), `languages.py`.
- Data lives in `app_dir()`: `%LOCALAPPDATA%\Dubbly`, or `C:\Users\Public\Dubbly` when the profile path is not
  ASCII. Models, voices, settings, CUDA libs, temp work files (`work/<hash>`; resume after cancel).

## Conventions that matter

- **i18n:** Russian source strings in the code are the keys: `_("…")`, `N_("…")` for module-level constants,
  placeholders like `{name}`. Translations: `assets/locales/<code>.json` (en, uk, es, de, fr, pt, it, pl, tr, zh;
  machine-prepared, not reviewed by native speakers). Never use `_` as a throwaway variable in a module that
  imports `_`. The worker process gets the UI language through `Options.ui_lang`. Download progress is marked
  with `pipeline.DL_MARK`, not by matching text.
- **Non-ASCII paths break sentencepiece and Piper on Windows.** Keep models, voices and temp files under the
  ASCII `app_dir()`; load sentencepiece from bytes.
- **The windowed build has no stdout/stderr**: `vt/__init__.py` installs stubs (tqdm and huggingface_hub crash
  otherwise).
- Batch files must be **ASCII with CRLF** (`.gitattributes` has `*.bat -text`); Cyrillic or LF breaks cmd.exe.
- Qt cannot draw soft shadows; the look is gradients, borders and drawn PNG icons.
- Windows-only on purpose: Piper download URL, `winsound`, `explorer /select`, taskkill.

## Pitfalls already hit (don't reintroduce)

- faster-whisper's own audio decoding (PyAV `metadata_errors`) failed in the build: audio is extracted by ffmpeg to
  raw float32 and passed as a numpy `memmap`.
- The ffmpeg from imageio-ffmpeg is old: no `amix=normalize`; mix with `volume=2` and `alimiter`.
- urllib on frozen Windows lacked a CA chain: `common.open_url` tries certifi first, then the system store.
- huggingface_hub progress via tqdm was unreliable: progress is the download folder size; Xet is disabled.
- CUDA libs are not bundled: `cuda_libs.py` downloads the newest `win_amd64` wheels of `nvidia-cublas-cu12`
  (12.x) and `nvidia-cudnn-cu12` (9.x) from PyPI (simple API) into `app_dir()/cuda`.
- Old pip with an `https://` system proxy crashes: `start.bat` detects a proxy and downloads directly first.
- TTS files are cached by index + hash(text, voice); never reuse them by index alone.
- Dubbing timing: sentence-level segments from word timestamps; `pipeline.fit_tempo` speeds up (up to the
  user's limit) or slightly slows lines; the offset slider shifts everything.

## Do not commit

- Any font from the user's `fonts/` folder (the owner's CinecavD font says "Do not distribute"; `.gitignore`
  covers `fonts/*`). Models, voices, venvs, `dist/`, `.vt_work_*`, secrets.
- Do not edit the owner's local settings or data outside the project folder without asking.

## Open items and ideas

1. **Translation quality** (the owner reported odd dubbing in a 20-minute video: slang, terms, idioms). Ideas,
   roughly in order: a "what the video is about" field + term glossary (Whisper `initial_prompt`, protected terms);
   translating with neighbouring sentences as context; an editor step that shows original → translation so the
   owner can fix lines before dubbing; an optional local LLM translator (e.g. Qwen) with a style prompt and
   glossary; text normalization before TTS (numbers, abbreviations, Latin words). First look at real
   `.srt` files next to the video to see whether recognition, translation or TTS is at fault.
2. Dubbly's own license is not chosen yet (see `LICENSES.md`); distributing the installer redistributes a
   GPL ffmpeg binary (imageio-ffmpeg wheel). Decide before publishing releases.
3. System requirement numbers in the README are estimates; compare them with real measurements.
4. A separate AMD/Intel-GPU variant (e.g. whisper.cpp with Vulkan) was discussed but not started.
5. The owner recreated the GitHub repository on 2026-11-02 and uploaded the files through the web UI, so `main`
   has a fresh two-commit history ("Add files via upload", "build.yml"). The earlier development history (about
   20 commits) is kept only in the owner's backup archive and in a local `old-history` branch; do not force-push
   over `main`. Add new work as ordinary commits on top.
