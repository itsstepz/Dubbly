**English** · [Русский](LICENSES.ru.md)

# Licenses of the components

Dubbly itself does not contain any speech, translation or voice models: they are downloaded to the user's computer on first use, each under its own terms. The program also relies on open-source libraries and bundles one font. This file lists them.

This is an overview, not legal advice. It was last reviewed on 2 November 2026. Some entries were checked against the projects' own pages (marked ✓); the others are from general knowledge and should be verified before you rely on them, especially for commercial use.

## Dubbly's own code

The project owner has not chosen a license for Dubbly's source code yet. Until a license file is added to the repository, normal copyright applies: others may read the code but have no automatic right to copy, modify or redistribute it.

## Components

| Component | What it does in Dubbly | License |
|---|---|---|
| faster-whisper and the Whisper models | Speech recognition | MIT |
| CTranslate2 | Runs the recognition and translation models | MIT |
| NLLB-200 (distilled 600M) | Translation ("NLLB-200" in the program) | **CC-BY-NC 4.0, non-commercial only** ✓. Its model card calls it a research model not meant for production use |
| Opus-MT (Helsinki-NLP) | Translation ("Opus-MT") | CC-BY 4.0 ✓ (attribution required; some converted copies are tagged Apache-2.0) |
| MADLAD-400 3B (Google) | Translation ("MADLAD-400") | Apache 2.0 ✓ |
| Piper (release 2023.11.14-2) | Speech synthesis engine | MIT ✓. If you move Piper to a newer release, check that release's license |
| Piper voices | The voices themselves | **Each voice has its own license**, shown on its model card. Some forbid commercial use |
| ffmpeg (inside the imageio-ffmpeg package) | Reads and writes video and audio | The Python wrapper is BSD-2; the PyPI wheels bundle an **ffmpeg binary under the GPL** ✓. See below |
| PyAV (`av`) | Used by faster-whisper | BSD-3 (it bundles its own FFmpeg libraries) |
| PySide6 (Qt) | The program window | LGPL-3.0 (alternatively GPL or a commercial license) |
| sentencepiece | Tokenizing text for translation | Apache 2.0 |
| huggingface_hub | Downloads models | Apache 2.0 |
| onnxruntime | Used for voice activity detection | MIT |
| NumPy | Audio arrays | BSD-3 |
| certifi | Certificates for secure downloads | MPL-2.0 |
| tqdm | Progress bars in a library | MPL-2.0 / MIT |
| JetBrains Mono | The interface font (bundled in `assets/fonts`) | SIL Open Font License 1.1; the text is in `assets/fonts/OFL.txt` |
| NVIDIA CUDA libraries (cuBLAS, cuDNN) | Optional graphics card support | NVIDIA's own license terms. They are **not** distributed with Dubbly: the program downloads them from PyPI at the user's request |
| PyInstaller | Builds the Windows program | GPL-2.0 with an exception that allows bundling any program |
| Inno Setup | Builds the installer | Inno Setup License (free for use and distribution) |

## What to know before sharing Dubbly

- **ffmpeg and the GPL.** If you hand out the installer or the program folder, you are redistributing the GPL-licensed ffmpeg binary. You then have to ship ffmpeg's license text and offer the corresponding source code, or switch to an LGPL-only ffmpeg build, or require the user to install ffmpeg separately. Using the program yourself is not affected.
- **Qt (LGPL).** Include the LGPL text with the program and keep the Qt libraries replaceable (the folder build does this: they stay as separate files).
- **NLLB-200 is non-commercial.** Do not use that translator in a commercial product. Opus-MT and MADLAD-400 are the alternatives built into the program.
- **Opus-MT needs attribution:** Helsinki-NLP, Language Technology Research Group, University of Helsinki.
- **Voices.** Check the license of every Piper voice you offer or recommend, and of any voice you add yourself.
- **Fonts.** JetBrains Mono may be bundled and redistributed under the OFL as long as the license text travels with it. A font you add yourself is your responsibility: many fonts forbid redistribution.

## The videos you process

Translating and dubbing someone else's video, and especially publishing the result, can infringe the author's rights. Use videos you own or have permission to adapt.
