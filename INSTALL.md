**English** · [Русский](INSTALL.ru.md)

# Installing and building Dubbly

## Quick start (Windows)

Double-click `start.bat`. On the first run it installs Python 3.12 (through winget) if needed, creates an environment, downloads the libraries and opens the program. Later runs open it immediately.

## Run from source

Python 3.11 or 3.12 is required.

```
pip install -r requirements.txt
python main.py
```

## NVIDIA graphics card

Enabled by default. On the first run with a card, Dubbly downloads the CUDA libraries
(cuBLAS and cuDNN, about 1 GB) from PyPI into its data folder. The option can be switched off
in the program window. Without a card or without the libraries, the processor is used.

## Interface language

The interface is available in Russian, English, Ukrainian, Spanish, German, French, Portuguese, Italian,
Polish, Turkish and Chinese. The language is chosen in the window header ("Same as system" by default);
switching is instant and keeps your settings. Progress messages and errors follow the same language.
Translations were prepared with machine help and have not been reviewed by native speakers: corrections are welcome.

To add a language: copy `assets/locales/en.json`, translate the values (keep placeholders such as `{name}`),
add the language to `LANGS` in `vt/i18n.py`, then run `python tools/check_locales.py` to verify it.

## Font

Dubbly ships with JetBrains Mono (SIL Open Font License, see `assets/fonts/OFL.txt`).
To use another font, put a `.ttf` or `.otf` file into a `fonts` folder: next to `start.bat`
(when running from source), or in the program's data folder, subfolder `fonts`
(`%LOCALAPPDATA%\Dubbly\fonts`, or `C:\Users\Public\Dubbly\fonts` if the user name is not Latin).
The font must contain Cyrillic. Custom fonts are not part of the repository or the installer:
many licenses forbid redistribution. To go back to JetBrains Mono, remove the file.

## Your own voices

Any Piper voice can be added: press **Add...** next to the voice list and choose the `.onnx` file
(the matching `.onnx.json` must lie in the same folder). Voices are published, for example, at
https://huggingface.co/rhasspy/piper-voices; you can also train your own. The program copies the pair
into its data folder (`voices`), picks the language from the voice settings, and lists the voice
for that language marked "(own)". **Delete** removes it from the program; the original files stay where they were.
Check the license of every voice you use: some voices forbid commercial use.

## Building the .exe

On Windows, run `build.bat`. The program appears in `dist\Dubbly\`.

Without installing anything locally, use GitHub: put the project files in a repository, open the **Actions** tab, choose **Build Windows exe** and click **Run workflow**. When it finishes, download the archive from **Artifacts** on the run page and unpack it: it contains `Dubbly-Setup.exe`. Run it to install Dubbly (Start menu and desktop shortcuts, uninstaller). Installing a newer version over an old one keeps settings and downloaded models.
