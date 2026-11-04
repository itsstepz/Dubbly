"""Отделение голоса от музыки и шумов (модель MDX-Net Kim_Vocal_2 через onnxruntime).

Зачем: раньше весь оригинальный звук приглушался под озвучкой, и вместе с голосом
пропадали музыка и эффекты. Теперь из оригинала вырезается только голос, а фон
(музыка, эффекты) остаётся в полную громкость — как в профессиональном дубляже.

Модель выдаёт голос; фон = исходный звук − голос. Звук обрабатывается кусками по ~6 с
и пишется на диск сразу: память не зависит от длины видео.
Алгоритм повторяет MDX-Net из Ultimate Vocal Remover (MIT), без PyTorch — на numpy.
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .common import CancelToken, download_file, hf_url, models_dir
from .i18n import _

SR = 44100
MODEL_REPO = "nomadkaraoke/public_uvr_models"   # зеркало моделей UVR на Hugging Face
MODEL_FILE = "Kim_Vocal_2.onnx"
MODEL_SIZE = 66759214
# параметры модели Kim_Vocal_2 (как в UVR): размер окна, полоса частот, длина куска, поправка громкости
N_FFT, DIM_F, DIM_T, HOP, COMPENSATE = 7680, 3072, 256, 1024, 1.009

Log = Callable[[str], None]


def ensure_model(endpoint: str, cancel: CancelToken, log: Log,
                 hook: Optional[Callable[[int, int], None]] = None) -> Path:
    path = models_dir() / "separation" / MODEL_FILE
    if path.exists() and path.stat().st_size == MODEL_SIZE:
        return path
    log(_("Скачиваю модель отделения голоса от музыки (один раз)…"))
    url = hf_url(f"https://huggingface.co/{MODEL_REPO}/resolve/main/{MODEL_FILE}", endpoint)
    download_file(url, path, cancel, hook)
    return path


def providers(gpu: bool) -> list:
    """DirectML — видеокарта любой фирмы (NVIDIA, AMD, Intel) под Windows; иначе процессор."""
    import onnxruntime as ort

    have = ort.get_available_providers()
    return (["DmlExecutionProvider"] if gpu and "DmlExecutionProvider" in have else []) + ["CPUExecutionProvider"]


class _MDX:
    def __init__(self, model_path: Path, gpu: bool = False):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        if gpu:  # DirectML требует так (документация onnxruntime)
            opts.enable_mem_pattern = False
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.sess = ort.InferenceSession(str(model_path), opts, providers=providers(gpu))
        self.on_gpu = self.sess.get_providers()[0] == "DmlExecutionProvider"
        self.inp = self.sess.get_inputs()[0].name
        self.chunk = HOP * (DIM_T - 1)                  # отсчётов в одном куске (~5,9 с)
        self.trim = N_FFT // 2
        self.gen = self.chunk - 2 * self.trim           # полезная часть куска без краёв
        self.bins = N_FFT // 2 + 1
        n = np.arange(N_FFT)
        self.window = (0.5 - 0.5 * np.cos(2 * np.pi * n / N_FFT)).astype(np.float32)  # Hann, как torch

    def _stft(self, x: np.ndarray) -> np.ndarray:
        """[2, chunk] → [1, 4, DIM_F, DIM_T] (re/im обоих каналов), как torch.stft(center=True)."""
        pad = N_FFT // 2
        x = np.pad(x, ((0, 0), (pad, pad)), mode="reflect")
        idx = np.arange(DIM_T)[:, None] * HOP + np.arange(N_FFT)[None, :]
        frames = x[:, idx] * self.window                # [2, T, n_fft]
        spec = np.fft.rfft(frames, axis=-1)             # [2, T, bins]
        spec = spec.transpose(0, 2, 1)[:, :DIM_F, :]    # [2, F, T]
        out = np.stack([spec.real, spec.imag], axis=1)  # [2, 2, F, T]
        return out.reshape(1, 4, DIM_F, DIM_T).astype(np.float32)

    def _istft(self, s: np.ndarray) -> np.ndarray:
        """[1, 4, DIM_F, DIM_T] → [2, chunk] (обратное к _stft, с перекрытием окон)."""
        s = s.reshape(2, 2, DIM_F, DIM_T)
        spec = np.zeros((2, self.bins, DIM_T), dtype=np.complex64)
        spec[:, :DIM_F, :] = s[:, 0] + 1j * s[:, 1]
        frames = np.fft.irfft(spec.transpose(0, 2, 1), n=N_FFT, axis=-1) * self.window  # [2, T, n_fft]
        total = N_FFT + HOP * (DIM_T - 1)
        out = np.zeros((2, total), dtype=np.float32)
        norm = np.zeros(total, dtype=np.float32)
        for t in range(DIM_T):
            out[:, t * HOP:t * HOP + N_FFT] += frames[:, t]
            norm[t * HOP:t * HOP + N_FFT] += self.window ** 2
        out /= np.maximum(norm, 1e-8)
        pad = N_FFT // 2
        return out[:, pad:pad + self.chunk]

    def vocals(self, block: np.ndarray) -> np.ndarray:
        """Голос из куска [2, chunk] (с краями trim, которые потом отбрасываются)."""
        spec = self._stft(block)
        pred = self.sess.run(None, {self.inp: spec})[0]
        return self._istft(pred) * COMPENSATE


def separate(mix_f32: Path, n_samples: int, out_bg_wav: Path, model_path: Path, cancel: CancelToken,
             progress: Callable[[float], None], gpu: bool = False) -> bool:
    """Из сырого стерео float32 44,1 кГц (mix_f32) пишет фон без голоса в 16-битный WAV.
    Возвращает True, если считалось на видеокарте."""
    m = _MDX(model_path, gpu)
    mix = np.memmap(mix_f32, dtype=np.float32, mode="r").reshape(-1, 2)  # [n, 2], не грузим целиком
    n = min(n_samples, mix.shape[0])
    with wave.open(str(out_bg_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        pos = 0
        while pos < n:
            cancel.check()
            # кусок с запасом trim с обеих сторон (за краями — тишина)
            lo, hi = pos - m.trim, pos - m.trim + m.chunk
            block = np.zeros((2, m.chunk), dtype=np.float32)
            a, b = max(lo, 0), min(hi, n)
            if b > a:
                block[:, a - lo:b - lo] = mix[a:b].T
            voc = m.vocals(block)[:, m.trim:m.trim + m.gen]
            take = min(m.gen, n - pos)
            orig = block[:, m.trim:m.trim + take]
            bg = np.clip(orig - voc[:, :take], -1.0, 1.0)
            w.writeframes((bg.T * 32767).astype(np.int16).tobytes())
            pos += take
            progress(min(1.0, pos / n))
    return m.on_gpu
