"""Studio AI Narrator & Voiceover Engine for Captions Studio.

Supports three verified synthesis backends without modifying core requirements.txt:
1. ``edge``: Microsoft Edge Neural TTS over WSS (aiohttp + certifi, Sec-MS-GEC v2, 14 languages, WordBoundary timings).
2. ``kokoro``: Local offline Kokoro-82M ONNX neural TTS (on-demand install into models/kokoro/, voice blending, phoneme timings).
3. ``elevenlabs``: Optional Bring-Your-Own API key (/v1/text-to-speech/{voice_id}/with-timestamps, line continuity context).

Every caption line is mastered to its own 44.1 kHz stereo WAV slice (``narr_line_<id>.wav``) with a
locked voice profile and broadcast LUFS preset so regenerating a single line preserves vocal color.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime as dt, timezone as tz
from email.utils import parsedate_to_datetime
from functools import lru_cache
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import ssl
import struct
import sys
import time
from typing import Any, Callable
import uuid
import wave
from xml.sax.saxutils import escape, unescape

import aiohttp
import certifi
import imageio_ffmpeg
import numpy as np
import requests

import job_process as process
from storage_utils import atomic_write_json, read_json_with_backup

ENGINES = ('edge', 'kokoro', 'elevenlabs')
TIMING_MODES = ('sync_captions', 'fit_captions')
SPEAK_TRACKS = ('original', 'translation', 'script')

TONE_PRESETS: dict[str, dict[str, str]] = {
    'natural': {
        'label': 'Natural Clean (Balanced -16 LUFS)',
        'filter': 'loudnorm=I=-16:TP=-1.5:LRA=11',
    },
    'warm_podcast': {
        'label': 'Warm Podcast Mic (Rich Low-Mid + Smooth Highs)',
        'filter': (
            'highpass=f=70,'
            'equalizer=f=140:t=q:w=1.2:g=2.5,'
            'equalizer=f=3500:t=q:w=1.4:g=-1.5,'
            'acompressor=threshold=-18dB:ratio=2.5:makeup=2,'
            'loudnorm=I=-16:TP=-1.5:LRA=11'
        ),
    },
    'crisp_creator': {
        'label': 'Crisp Creator / TikTok Pop (Presence & Punch)',
        'filter': (
            'highpass=f=90,'
            'equalizer=f=4800:t=q:w=1.0:g=3.0,'
            'acompressor=threshold=-16dB:ratio=3.5:makeup=2.5,'
            'loudnorm=I=-16:TP=-1.5:LRA=11'
        ),
    },
    'deep_cinema': {
        'label': 'Deep Cinema / Documentary (Chest Resonance)',
        'filter': (
            'highpass=f=60,'
            'equalizer=f=110:t=q:w=1.1:g=4.0,'
            'equalizer=f=4200:t=q:w=1.2:g=2.0,'
            'acompressor=threshold=-17dB:ratio=3.0:makeup=2,'
            'loudnorm=I=-16:TP=-1.5:LRA=11'
        ),
    },
}

DEFAULT_SETTINGS: dict[str, Any] = {
    'engine': 'edge',
    'voice': 'en-US-AvaMultilingualNeural',
    'language': 'en',
    'tone': 'natural',
    'timing_mode': 'sync_captions',
    'track': 'original',
    'rate_pct': 0,
    'pitch_hz': 0,
    'speed': 1.0,
    'blend_voice': '',
    'blend_ratio': 0.0,
    'eleven_model': 'eleven_multilingual_v2',
    'stability': 0.50,
    'similarity_boost': 0.75,
    'style': 0.15,
    'narrator_volume': 1.0,
    'background_volume': 0.25,
    'ducking': True,
    'line_pause': 0.20,
}

# Curated Microsoft Edge Neural voices across all 14 Studio languages
EDGE_VOICES: list[dict[str, str]] = [
    # English (US & UK)
    {'id': 'en-US-AvaMultilingualNeural', 'name': 'Ava Multilingual', 'lang': 'en', 'gender': 'Female', 'accent': 'US', 'tag': 'Bright Creator · Reels/TikTok'},
    {'id': 'en-US-AndrewMultilingualNeural', 'name': 'Andrew Multilingual', 'lang': 'en', 'gender': 'Male', 'accent': 'US', 'tag': 'Warm Storyteller · Podcast'},
    {'id': 'en-US-EmmaMultilingualNeural', 'name': 'Emma Multilingual', 'lang': 'en', 'gender': 'Female', 'accent': 'US', 'tag': 'Calm Narrative · Essay'},
    {'id': 'en-US-BrianMultilingualNeural', 'name': 'Brian Multilingual', 'lang': 'en', 'gender': 'Male', 'accent': 'US', 'tag': 'Clear & Upbeat · Explainer'},
    {'id': 'en-US-ChristopherNeural', 'name': 'Christopher', 'lang': 'en', 'gender': 'Male', 'accent': 'US', 'tag': 'Deep Documentary · Cinema'},
    {'id': 'en-US-AriaNeural', 'name': 'Aria', 'lang': 'en', 'gender': 'Female', 'accent': 'US', 'tag': 'Crisp Presenter · News'},
    {'id': 'en-US-GuyNeural', 'name': 'Guy', 'lang': 'en', 'gender': 'Male', 'accent': 'US', 'tag': 'Natural Conversational'},
    {'id': 'en-GB-SoniaNeural', 'name': 'Sonia', 'lang': 'en', 'gender': 'Female', 'accent': 'UK', 'tag': 'British Polished'},
    {'id': 'en-GB-RyanNeural', 'name': 'Ryan', 'lang': 'en', 'gender': 'Male', 'accent': 'UK', 'tag': 'British Storyteller'},
    # Greek (el)
    {'id': 'el-GR-AthinaNeural', 'name': 'Athina (Αθηνά)', 'lang': 'el', 'gender': 'Female', 'accent': 'GR', 'tag': 'Natural Greek Female'},
    {'id': 'el-GR-NestorasNeural', 'name': 'Nestoras (Νέστορας)', 'lang': 'el', 'gender': 'Male', 'accent': 'GR', 'tag': 'Natural Greek Male'},
    # Korean (ko)
    {'id': 'ko-KR-SunHiNeural', 'name': 'Sun-Hi (선희)', 'lang': 'ko', 'gender': 'Female', 'accent': 'KR', 'tag': 'Natural Korean Female'},
    {'id': 'ko-KR-InJoonNeural', 'name': 'In-Joon (인준)', 'lang': 'ko', 'gender': 'Male', 'accent': 'KR', 'tag': 'Natural Korean Male'},
    # French (fr)
    {'id': 'fr-FR-VivienneMultilingualNeural', 'name': 'Vivienne Multilingual', 'lang': 'fr', 'gender': 'Female', 'accent': 'FR', 'tag': 'Natural French Female'},
    {'id': 'fr-FR-RemyMultilingualNeural', 'name': 'Rémy Multilingual', 'lang': 'fr', 'gender': 'Male', 'accent': 'FR', 'tag': 'Natural French Male'},
    # Spanish (es)
    {'id': 'es-ES-ElviraNeural', 'name': 'Elvira', 'lang': 'es', 'gender': 'Female', 'accent': 'ES', 'tag': 'Natural Spanish Female'},
    {'id': 'es-ES-AlvaroNeural', 'name': 'Álvaro', 'lang': 'es', 'gender': 'Male', 'accent': 'ES', 'tag': 'Natural Spanish Male'},
    # German (de)
    {'id': 'de-DE-SeraphinaMultilingualNeural', 'name': 'Seraphina Multilingual', 'lang': 'de', 'gender': 'Female', 'accent': 'DE', 'tag': 'Natural German Female'},
    {'id': 'de-DE-FlorianMultilingualNeural', 'name': 'Florian Multilingual', 'lang': 'de', 'gender': 'Male', 'accent': 'DE', 'tag': 'Natural German Male'},
    # Italian (it)
    {'id': 'it-IT-ElsaNeural', 'name': 'Elsa', 'lang': 'it', 'gender': 'Female', 'accent': 'IT', 'tag': 'Natural Italian Female'},
    {'id': 'it-IT-GiuseppeMultilingualNeural', 'name': 'Giuseppe Multilingual', 'lang': 'it', 'gender': 'Male', 'accent': 'IT', 'tag': 'Natural Italian Male'},
    # Portuguese (pt)
    {'id': 'pt-BR-ThalitaMultilingualNeural', 'name': 'Thalita Multilingual', 'lang': 'pt', 'gender': 'Female', 'accent': 'BR', 'tag': 'Natural Portuguese Female'},
    {'id': 'pt-BR-AntonioNeural', 'name': 'Antônio', 'lang': 'pt', 'gender': 'Male', 'accent': 'BR', 'tag': 'Natural Portuguese Male'},
    # Japanese (ja)
    {'id': 'ja-JP-NanamiNeural', 'name': 'Nanami', 'lang': 'ja', 'gender': 'Female', 'accent': 'JP', 'tag': 'Natural Japanese Female'},
    {'id': 'ja-JP-KeitaNeural', 'name': 'Keita', 'lang': 'ja', 'gender': 'Male', 'accent': 'JP', 'tag': 'Natural Japanese Male'},
    # Chinese (zh)
    {'id': 'zh-CN-XiaoxiaoNeural', 'name': 'Xiaoxiao', 'lang': 'zh', 'gender': 'Female', 'accent': 'CN', 'tag': 'Expressive Chinese Female'},
    {'id': 'zh-CN-YunxiNeural', 'name': 'Yunxi', 'lang': 'zh', 'gender': 'Male', 'accent': 'CN', 'tag': 'Narrative Chinese Male'},
    # Arabic (ar)
    {'id': 'ar-SA-ZariyahNeural', 'name': 'Zariyah', 'lang': 'ar', 'gender': 'Female', 'accent': 'SA', 'tag': 'Natural Arabic Female'},
    {'id': 'ar-SA-HamedNeural', 'name': 'Hamed', 'lang': 'ar', 'gender': 'Male', 'accent': 'SA', 'tag': 'Natural Arabic Male'},
    # Hindi (hi)
    {'id': 'hi-IN-SwaraNeural', 'name': 'Swara', 'lang': 'hi', 'gender': 'Female', 'accent': 'IN', 'tag': 'Natural Hindi Female'},
    {'id': 'hi-IN-MadhurNeural', 'name': 'Madhur', 'lang': 'hi', 'gender': 'Male', 'accent': 'IN', 'tag': 'Natural Hindi Male'},
    # Russian (ru)
    {'id': 'ru-RU-SvetlanaNeural', 'name': 'Svetlana', 'lang': 'ru', 'gender': 'Female', 'accent': 'RU', 'tag': 'Natural Russian Female'},
    {'id': 'ru-RU-DmitryNeural', 'name': 'Dmitry', 'lang': 'ru', 'gender': 'Male', 'accent': 'RU', 'tag': 'Natural Russian Male'},
    # Turkish (tr)
    {'id': 'tr-TR-EmelNeural', 'name': 'Emel', 'lang': 'tr', 'gender': 'Female', 'accent': 'TR', 'tag': 'Natural Turkish Female'},
    {'id': 'tr-TR-AhmetNeural', 'name': 'Ahmet', 'lang': 'tr', 'gender': 'Male', 'accent': 'TR', 'tag': 'Natural Turkish Male'},
]

KOKORO_VOICES: list[dict[str, str]] = [
    {'id': 'af_heart', 'name': 'Heart ⭐', 'lang': 'en', 'espeak_lang': 'en-us', 'gender': 'Female', 'accent': 'US', 'tag': '#1 Studio Warmth · Flagship'},
    {'id': 'af_bella', 'name': 'Bella', 'lang': 'en', 'espeak_lang': 'en-us', 'gender': 'Female', 'accent': 'US', 'tag': 'Expressive Storyteller'},
    {'id': 'af_nicole', 'name': 'Nicole', 'lang': 'en', 'espeak_lang': 'en-us', 'gender': 'Female', 'accent': 'US', 'tag': 'Soft & Intimate · Calm'},
    {'id': 'af_sarah', 'name': 'Sarah', 'lang': 'en', 'espeak_lang': 'en-us', 'gender': 'Female', 'accent': 'US', 'tag': 'Crisp Creator · Clear'},
    {'id': 'af_nova', 'name': 'Nova', 'lang': 'en', 'espeak_lang': 'en-us', 'gender': 'Female', 'accent': 'US', 'tag': 'Upbeat Modern · Reels'},
    {'id': 'am_adam', 'name': 'Adam', 'lang': 'en', 'espeak_lang': 'en-us', 'gender': 'Male', 'accent': 'US', 'tag': 'Deep Narrator · Documentary'},
    {'id': 'am_michael', 'name': 'Michael', 'lang': 'en', 'espeak_lang': 'en-us', 'gender': 'Male', 'accent': 'US', 'tag': 'Conversational Podcast Host'},
    {'id': 'am_fenrir', 'name': 'Fenrir', 'lang': 'en', 'espeak_lang': 'en-us', 'gender': 'Male', 'accent': 'US', 'tag': 'Cinematic Bold · Trailer'},
    {'id': 'am_puck', 'name': 'Puck', 'lang': 'en', 'espeak_lang': 'en-us', 'gender': 'Male', 'accent': 'US', 'tag': 'Energetic Creator · Shorts'},
    {'id': 'bf_emma', 'name': 'Emma (UK)', 'lang': 'en', 'espeak_lang': 'en-gb', 'gender': 'Female', 'accent': 'UK', 'tag': 'British Studio Female'},
    {'id': 'bf_isabella', 'name': 'Isabella (UK)', 'lang': 'en', 'espeak_lang': 'en-gb', 'gender': 'Female', 'accent': 'UK', 'tag': 'British Warm Female'},
    {'id': 'bm_george', 'name': 'George (UK)', 'lang': 'en', 'espeak_lang': 'en-gb', 'gender': 'Male', 'accent': 'UK', 'tag': 'British Documentary Male'},
    {'id': 'bm_lewis', 'name': 'Lewis (UK)', 'lang': 'en', 'espeak_lang': 'en-gb', 'gender': 'Male', 'accent': 'UK', 'tag': 'British Narrative Male'},
    {'id': 'ff_siwis', 'name': 'Siwis', 'lang': 'fr', 'espeak_lang': 'fr-fr', 'gender': 'Female', 'accent': 'FR', 'tag': 'French Studio Female'},
    {'id': 'ef_dora', 'name': 'Dora', 'lang': 'es', 'espeak_lang': 'es', 'gender': 'Female', 'accent': 'ES', 'tag': 'Spanish Studio Female'},
    {'id': 'em_alex', 'name': 'Alex', 'lang': 'es', 'espeak_lang': 'es', 'gender': 'Male', 'accent': 'ES', 'tag': 'Spanish Studio Male'},
    {'id': 'if_sara', 'name': 'Sara', 'lang': 'it', 'espeak_lang': 'it', 'gender': 'Female', 'accent': 'IT', 'tag': 'Italian Studio Female'},
    {'id': 'im_nicola', 'name': 'Nicola', 'lang': 'it', 'espeak_lang': 'it', 'gender': 'Male', 'accent': 'IT', 'tag': 'Italian Studio Male'},
    {'id': 'pf_dora', 'name': 'Dora (BR)', 'lang': 'pt', 'espeak_lang': 'pt-br', 'gender': 'Female', 'accent': 'BR', 'tag': 'Portuguese Studio Female'},
    {'id': 'pm_alex', 'name': 'Alex (BR)', 'lang': 'pt', 'espeak_lang': 'pt-br', 'gender': 'Male', 'accent': 'BR', 'tag': 'Portuguese Studio Male'},
    {'id': 'jf_alpha', 'name': 'Alpha', 'lang': 'ja', 'espeak_lang': 'ja', 'gender': 'Female', 'accent': 'JP', 'tag': 'Japanese Studio Female'},
    {'id': 'jm_kumo', 'name': 'Kumo', 'lang': 'ja', 'espeak_lang': 'ja', 'gender': 'Male', 'accent': 'JP', 'tag': 'Japanese Studio Male'},
    {'id': 'hf_alpha', 'name': 'Alpha (HI)', 'lang': 'hi', 'espeak_lang': 'hi', 'gender': 'Female', 'accent': 'IN', 'tag': 'Hindi Studio Female'},
    {'id': 'hm_omega', 'name': 'Omega (HI)', 'lang': 'hi', 'espeak_lang': 'hi', 'gender': 'Male', 'accent': 'IN', 'tag': 'Hindi Studio Male'},
]

PREVIEW_SAMPLES: dict[str, str] = {
    'en': 'Welcome back! Today we are testing the studio voiceover right inside Captions Studio.',
    'el': 'Γεια σας! Αυτή είναι μια δοκιμή της φωνητικής αφήγησης στο στούντιο υποτίτλων.',
    'ko': '안녕하세요! 자막 스튜디오의 인공지능 내레이션 음성을 테스트하고 있습니다.',
    'fr': 'Bonjour à tous !Voici un aperçu de la voix narrative dans le studio.',
    'es': '¡Hola a todos! Esta es una prueba de la voz de narración en el estudio.',
    'de': 'Hallo zusammen! Dies ist ein kurzer Test der neuen Studio-Sprachausgabe.',
    'it': 'Ciao a tutti! Questa è una prova della voce narrante nello studio.',
    'pt': 'Olá a todos! Este é um teste da narração de voz no estúdio.',
    'ja': 'こんにちは！これはスタジオナレーション音声のプレビューです。',
    'zh': '大家好！这是字幕工作室语音旁白功能的试听测试。',
    'ar': 'مرحباً بكم! هذا اختبار للصوت السردي داخل استوديو الترجمة.',
    'hi': 'नमस्ते! यह कैप्शन स्टूडियो में वॉयस नैरेशन का एक परीक्षण है।',
    'ru': 'Всем привет! Это проверка голосовой озвучки в студии субтитров.',
    'tr': 'Merhaba! Bu, altyazı stüdyosundaki seslendirme özelliğinin bir testidir.',
}


# ------------------------------------------------------------------
# 1. Microsoft Edge Neural TTS (Sec-MS-GEC v2 + WSS WordBoundary)
# ------------------------------------------------------------------

_EDGE_BASE_URL = 'speech.platform.bing.com/consumer/speech/synthesize/readaloud'
_TRUSTED_CLIENT_TOKEN = '6A5AA1D4EAFF4E9FB37E23D68491D6F4'
_EDGE_WSS_URL = f'wss://{_EDGE_BASE_URL}/edge/v1?TrustedClientToken={_TRUSTED_CLIENT_TOKEN}'
_CHROMIUM_FULL_VERSION = '143.0.3650.75'
_CHROMIUM_MAJOR = '143'
_SEC_MS_GEC_VERSION = f'2-{_CHROMIUM_FULL_VERSION}'
_WIN_EPOCH = 11644473600
_TICKS_PER_SECOND = 10_000_000
_MP3_BITRATE_BPS = 48_000
_U32_MASK = 0xFFFFFFFF

_SHA256_INITIAL = (
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
)
_SHA256_STATE = (
    0xFD9FBEA2, 0x91243CE7, 0xBE499094, 0xCD2E1E0A,
    0x6C006F49, 0x04BD35AB, 0xFEB0A7E4, 0x03EFFBD2,
)
_SHA256_SCHEDULE = (
    0xEB24BF9E, 0x1558691F, 0xA0C09EE2, 0x0CFA32BA,
    0xA622EE8C, 0xD1DD9491, 0xC0DD25A0, 0xF9E70AB6,
    0xF0C31573, 0x7058CE4E, 0x7188E606, 0x00E5AB33,
    0xD258B060, 0x72766564,
)
_SHA256_ROUND_CONSTANTS = (
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1, 0x923F82A4, 0xAB1C5ED5,
    0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3, 0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174,
    0xE49B69C1, 0xEFBE4786, 0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147, 0x06CA6351, 0x14292967,
    0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13, 0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85,
    0xA2BFE8A1, 0xA81A664B, 0xC24B8B70, 0xC76C51A3, 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3, 0x4ED8AA4A, 0x5B9CCA4F, 0x682E6FF3,
    0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208, 0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
)
_SHA256_ADJUSTMENT = 0xC9DC06A7
_SHA256_BLOCK_CONSTANTS = (
    _SHA256_ROUND_CONSTANTS[:14] + (_SHA256_ADJUSTMENT,) + _SHA256_ROUND_CONSTANTS[15:]
)
_SHA256_SIGMA0_ADJUSTMENT = 0x059C0B80
_SHA256_SIGMA1_ADJUSTMENT = 0x000B92C0
_CS64_COEFFICIENTS = (
    (0xE82E91B1, 0xB32700D0), (0x44DE24C6, 0x88DFF51D),
    (0x3BEB65BC, 0x29514038), (0xC89C5933, 0xB328CBDF),
    (0x8D1EC211, 0xD405B4D5), (0x314EF5D5, 0x26E55F3C),
    (0xE92491B1, 0x607801C6), (0xF0A5B9D5, 0x82B2C1FB),
    (0x06064CF3, 0xFA51A3DA), (0xDA79FA60, 0x207CC464),
    (0xBED20560, 0x3C3C74F3), (0x89F9C9F8, 0xD2D14B61),
    (0x35FA38C6, 0xBB04A2C1), (0xCB49E3C6, 0xC5626167),
)
_CS64_FACTOR = 0x82893933
_CS64_ADJUSTMENT0 = 0xF2F90B1A
_CS64_ADJUSTMENT1 = 0x0B1A0000

_EDGE_CLOCK_SKEW: float = 0.0
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _rol16(value: int) -> int:
    value &= _U32_MASK
    return ((value << 16) | (value >> 16)) & _U32_MASK


def _sigma0(value: int) -> int:
    return ((value >> 7) ^ (value << 25) ^ (value >> 18) ^ (value << 14) ^ (value >> 3)) & _U32_MASK


def _sigma1(value: int) -> int:
    return ((value >> 17) ^ (value << 15) ^ (value >> 19) ^ (value << 13) ^ (value >> 10)) & _U32_MASK


def _sha256_rounds(state: tuple[int, ...], words: list[int], first_round: int = 0) -> tuple[int, ...]:
    a, b, c, d, e, f, g, h = state
    mask = _U32_MASK
    constants = _SHA256_BLOCK_CONSTANTS if first_round == 14 else _SHA256_ROUND_CONSTANTS
    for index in range(first_round, 64):
        rot_e = e * 0x100000001
        rot_a = a * 0x100000001
        t1 = (
            h
            + ((rot_e >> 6) ^ (rot_e >> 11) ^ (rot_e >> 25))
            + (g ^ (e & (f ^ g)))
            + constants[index]
            + words[index]
        )
        t2 = ((rot_a >> 2) ^ (rot_a >> 13) ^ (rot_a >> 22)) + ((a & b) | (c & (a | b)))
        a, b, c, d, e, f, g, h = (t1 + t2) & mask, a, b, c, (d + t1) & mask, e, f, g
    return a, b, c, d, e, f, g, h


def _expand_sha256_schedule(words: list[int], first_word: int = 16) -> None:
    mask = _U32_MASK
    for index in range(first_word, 64):
        x, y = words[index - 2], words[index - 15]
        s1 = (x >> 17) ^ (x << 15) ^ (x >> 19) ^ (x << 13) ^ (x >> 10)
        s0 = (y >> 7) ^ (y << 25) ^ (y >> 18) ^ (y << 14) ^ (y >> 3)
        words.append((s1 + words[index - 7] + s0 + words[index - 16]) & mask)


@lru_cache(maxsize=4)
def _sha256_init(data: bytes) -> tuple[int, ...]:
    mask = _U32_MASK
    words = [0] * 14 + [int.from_bytes(data[:3], 'big'), int.from_bytes(data[3:7], 'big')]
    for index in range(16, 30):
        value = _SHA256_SCHEDULE[index - 16]
        if index - 2 >= 14:
            value += (_sigma1(words[index - 2]) ^ _SHA256_SIGMA1_ADJUSTMENT) if index == 16 else _sigma1(words[index - 2])
        if index - 7 >= 14:
            value += words[index - 7]
        if index - 15 >= 14:
            value += (_sigma0(words[index - 15]) ^ _SHA256_SIGMA0_ADJUSTMENT) if index == 29 else _sigma0(words[index - 15])
        words.append(value & mask)
    words.append(
        (_sigma1(words[28]) + words[23] + _sigma0(words[15]) + words[14] + _SHA256_ADJUSTMENT - _SHA256_ROUND_CONSTANTS[14]) & mask
    )
    _expand_sha256_schedule(words, 31)
    working = _sha256_rounds(_SHA256_STATE, words, 14)
    return tuple((x + y) & mask for x, y in zip(_SHA256_INITIAL, working))


def _sha256_digest(data: bytes) -> bytes:
    mask = _U32_MASK
    length = 57 + len(data)
    padded = data[7:] + b'\x80' + b'\x00' * ((55 - length) % 64) + struct.pack('>Q', length * 8)
    state = _sha256_init(data[:7])
    for offset in range(0, len(padded), 64):
        words = list(struct.unpack('>16I', padded[offset:offset + 64]))
        _expand_sha256_schedule(words)
        working = _sha256_rounds(state, words)
        state = tuple((x + y) & mask for x, y in zip(state, working))
    return struct.pack('>8I', *state)


def _cs64_digest(data: bytes, digest: bytes) -> tuple[int, int]:
    mask = _U32_MASK
    key_a, key_b = struct.unpack_from('<II', digest)
    key_a |= 1
    key_b |= 1
    factors = ((key_a * _CS64_FACTOR) & mask, (key_b * _CS64_FACTOR) & mask)
    terms = [(coeff * factors[i % 2]) & mask for i, (coeff, _) in enumerate(_CS64_COEFFICIENTS)]
    offsets = [off for _, off in _CS64_COEFFICIENTS]
    raw = b'\x00' + data
    padded = raw + b'\x00' * ((-len(raw)) % 4)
    le_words = list(struct.unpack(f'<{len(padded) // 4}I', padded)) if padded else []
    if len(le_words) % 2:
        le_words.append(0)
    for index, word in enumerate(le_words):
        term = word * (key_a if index % 2 == 0 else key_b)
        offset = _rol16(word) * (0xEF0569FB if index % 2 == 0 else 0xC31713DB)
        if index == 0:
            term += _CS64_ADJUSTMENT0 * factors[0]
            offset += _CS64_ADJUSTMENT1
        terms.append(term & mask)
        offsets.append(offset & mask)
    swap_acc = swap_last = state = acc = 0
    for index in range(0, len(terms), 2):
        x, y = terms[index], terms[index + 1]
        t = _rol16((offsets[index] + x) & mask)
        q = (t * 0x76F50F34) & mask
        swap_acc += (_rol16(q) * 0xC3EFEA97 + q) & mask
        t = _rol16((offsets[index + 1] + y) & mask)
        q = (t * 0x1881CE3C) & mask
        swap_last = (_rol16(q) * 0x35BD1EC9 + q) & mask
        swap_acc = (swap_acc + swap_last) & mask
        state = (state * key_a + x) & mask
        state = (_rol16(state) * 0xCF98B111) & mask
        state = (_rol16(state) * 0x87085B9F) & mask
        state = (_rol16(state) * 0x12CEB96D) & mask
        state = (_rol16(state) * 0x257E1D83) & mask
        acc += state
        t = (state * key_b + y) & mask
        t = (_rol16(t) * 0xA27416F5) & mask
        t = (_rol16(t) * 0xD38396FF) & mask
        state = (_rol16((_rol16(t) * 0x7C932B89) & mask) * 0xBFA49F69) & mask
        acc = (acc + state) & mask
    return swap_last ^ state, swap_acc ^ acc


def generate_sec_ms_gec_v2(unix_timestamp: float | None = None) -> str:
    """Compute Microsoft's v2 Sec-MS-GEC token (<16 hex>-<64 hex>)."""
    ticks = (dt.now(tz.utc).timestamp() + _EDGE_CLOCK_SKEW) if unix_timestamp is None else float(unix_timestamp)
    ticks += _WIN_EPOCH
    ticks -= ticks % 300
    ticks *= 1e7
    str_to_hash = f'{ticks:.0f}{_TRUSTED_CLIENT_TOKEN}'.encode('ascii')
    digest = _sha256_digest(str_to_hash)
    cs64 = struct.pack('<II', *_cs64_digest(str_to_hash, digest)).hex().upper()
    return f'{cs64}-{digest.hex().upper()}'


def format_edge_voice_name(short_voice: str) -> str:
    """Convert short names like ``el-GR-AthinaNeural`` into Microsoft's full SSML voice identifier."""
    short_voice = str(short_voice or '').strip()
    if short_voice.startswith('Microsoft Server Speech Text to Speech Voice ('):
        return short_voice
    match = re.match(r'^([a-z]{2,})-([A-Z]{2,})-(.+Neural)$', short_voice)
    if not match:
        raise ValueError(f'Invalid Microsoft Neural voice ID: {short_voice!r}')
    lang, region, name = match.group(1), match.group(2), match.group(3)
    if '-' in name:
        region = f'{region}-{name[:name.find("-")]}'
        name = name[name.find('-') + 1:]
    return f'Microsoft Server Speech Text to Speech Voice ({lang}-{region}, {name})'


def clean_tts_text(text: str) -> str:
    """Strip control characters that cause SSML or tokenizer rejections."""
    chars = list(str(text or ''))
    for idx, ch in enumerate(chars):
        code = ord(ch)
        if (0 <= code <= 8) or (11 <= code <= 12) or (14 <= code <= 31):
            chars[idx] = ' '
    return ' '.join(''.join(chars).split()).strip()


def build_edge_ssml(text: str, voice: str, *, rate_pct: int = 0, pitch_hz: int = 0) -> str:
    full_voice = format_edge_voice_name(voice)
    rate_pct = max(-50, min(60, int(round(float(rate_pct or 0)))))
    pitch_hz = max(-20, min(20, int(round(float(pitch_hz or 0)))))
    escaped = escape(clean_tts_text(text))
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
        f"<voice name='{full_voice}'>"
        f"<prosody pitch='{pitch_hz:+d}Hz' rate='{rate_pct:+d}%' volume='+0%'>"
        f"{escaped}"
        "</prosody>"
        "</voice>"
        "</speak>"
    )


async def _edge_synthesize_once(ssml: str) -> tuple[bytes, list[dict[str, Any]]]:
    headers = {
        'User-Agent': (
            f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            f'(KHTML, like Gecko) Chrome/{_CHROMIUM_MAJOR}.0.0.0 Safari/537.36 Edg/{_CHROMIUM_MAJOR}.0.0.0'
        ),
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'en-US,en;q=0.9',
        'Pragma': 'no-cache',
        'Cache-Control': 'no-cache',
        'Origin': 'chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold',
        'Sec-WebSocket-Version': '13',
        'Cookie': f'muid={secrets.token_hex(16).upper()};',
    }
    url = (
        f'{_EDGE_WSS_URL}&ConnectionId={uuid.uuid4().hex}'
        f'&Sec-MS-GEC={generate_sec_ms_gec_v2()}'
        f'&Sec-MS-GEC-Version={_SEC_MS_GEC_VERSION}'
    )
    timeout = aiohttp.ClientTimeout(total=45, sock_connect=10, sock_read=30)
    audio_chunks: list[bytes] = []
    words: list[dict[str, Any]] = []
    async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
        async with session.ws_connect(url, compress=15, headers=headers, ssl=_SSL_CTX) as ws:
            ts = time.strftime('%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)', time.gmtime())
            cfg = (
                f'X-Timestamp:{ts}\r\n'
                'Content-Type:application/json; charset=utf-8\r\n'
                'Path:speech.config\r\n\r\n'
                '{"context":{"synthesis":{"audio":{"metadataoptions":{'
                '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"true"'
                '},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n'
            )
            await ws.send_str(cfg)
            msg = (
                f'X-RequestId:{uuid.uuid4().hex}\r\n'
                'Content-Type:application/ssml+xml\r\n'
                f'X-Timestamp:{ts}Z\r\n'
                'Path:ssml\r\n\r\n'
                f'{ssml}'
            )
            await ws.send_str(msg)
            async for received in ws:
                if received.type == aiohttp.WSMsgType.BINARY:
                    if len(received.data) < 2:
                        continue
                    header_len = int.from_bytes(received.data[:2], 'big')
                    payload = received.data[header_len + 2:]
                    if payload:
                        audio_chunks.append(payload)
                elif received.type == aiohttp.WSMsgType.TEXT:
                    if 'Path:audio.metadata' in received.data and 'WordBoundary' in received.data:
                        parts = received.data.split('\r\n\r\n', 1)
                        if len(parts) == 2:
                            meta = json.loads(parts[1])
                            for item in meta.get('Metadata', []):
                                if item.get('Type') == 'WordBoundary':
                                    data = item.get('Data', {})
                                    w_text = unescape(str((data.get('text') or {}).get('Text') or '')).strip()
                                    if not w_text:
                                        continue
                                    start_s = float(data.get('Offset', 0)) / _TICKS_PER_SECOND
                                    dur_s = max(0.04, float(data.get('Duration', 0)) / _TICKS_PER_SECOND)
                                    words.append({
                                        'start': round(start_s, 3),
                                        'end': round(start_s + dur_s, 3),
                                        'text': w_text,
                                    })
                    elif 'Path:turn.end' in received.data:
                        break
                elif received.type == aiohttp.WSMsgType.ERROR:
                    raise RuntimeError(f'Edge TTS WebSocket error: {received.data}')
    audio_bytes = b''.join(audio_chunks)
    if not audio_bytes:
        raise ValueError('Microsoft Neural TTS returned empty audio for this line.')
    return audio_bytes, words


def synthesize_edge(text: str, voice: str, *, rate_pct: int = 0, pitch_hz: int = 0) -> tuple[bytes, str, list[dict[str, Any]]]:
    """Synthesize speech with Microsoft Edge Neural TTS. Returns ``(audio_bytes, '.mp3', word_timings)``."""
    global _EDGE_CLOCK_SKEW
    cleaned = clean_tts_text(text)
    if not cleaned:
        raise ValueError('Cannot synthesize an empty caption line.')
    ssml = build_edge_ssml(cleaned, voice, rate_pct=rate_pct, pitch_hz=pitch_hz)

    async def _run():
        global _EDGE_CLOCK_SKEW
        try:
            return await _edge_synthesize_once(ssml)
        except aiohttp.ClientResponseError as exc:
            if exc.status == 403 and exc.headers and exc.headers.get('Date'):
                try:
                    parsed = parsedate_to_datetime(exc.headers['Date'])
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=tz.utc)
                    _EDGE_CLOCK_SKEW += parsed.timestamp() - (dt.now(tz.utc).timestamp() + _EDGE_CLOCK_SKEW)
                except Exception:
                    pass
                return await _edge_synthesize_once(ssml)
            raise

    audio_bytes, words = asyncio.run(_run())
    return audio_bytes, '.mp3', words


# ------------------------------------------------------------------
# 2. Kokoro-82M Local ONNX Engine (100% Offline, GPU/CPU Safe)
# ------------------------------------------------------------------

KOKORO_MODEL_URLS = {
    'kokoro-v1.0.fp16.onnx': 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.fp16.onnx',
    'voices-v1.0.bin': 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin',
}
_KOKORO_LOCK = asyncio.Lock() if False else None  # Lazy threading lock below
import threading
_KOKORO_THREAD_LOCK = threading.RLock()
_KOKORO_CACHE: dict[str, Any] = {}


def kokoro_dir(app_root: Path | None = None) -> Path:
    base = Path(app_root) if app_root else Path(__file__).resolve().parent
    return base / 'models' / 'kokoro'


def kokoro_status(app_root: Path | None = None) -> dict[str, Any]:
    """Return whether the local Kokoro-82M ONNX package and model files are installed."""
    kdir = kokoro_dir(app_root)
    model_ok = (kdir / 'kokoro-v1.0.fp16.onnx').is_file() and (kdir / 'kokoro-v1.0.fp16.onnx').stat().st_size > 50_000_000
    voices_ok = (kdir / 'voices-v1.0.bin').is_file() and (kdir / 'voices-v1.0.bin').stat().st_size > 5_000_000
    pkg_ok = False
    try:
        import importlib.util
        pkg_ok = importlib.util.find_spec('kokoro_onnx') is not None and importlib.util.find_spec('espeakng_loader') is not None
    except Exception:
        pkg_ok = False
    return {
        'installed': bool(pkg_ok and model_ok and voices_ok),
        'package_installed': pkg_ok,
        'models_installed': bool(model_ok and voices_ok),
        'path': str(kdir),
    }


def install_kokoro_local(app_root: Path | None = None, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Install kokoro-onnx (--no-deps to preserve onnxruntime-gpu) and download model files into models/kokoro/."""
    report = progress or (lambda _msg: None)
    kdir = kokoro_dir(app_root)
    kdir.mkdir(parents=True, exist_ok=True)
    status = kokoro_status(app_root)
    if not status['package_installed']:
        report('Installing local phonemizer and Kokoro ONNX runtime helpers…')
        res1 = process.run(
            [sys.executable, '-m', 'pip', 'install', '--prefer-binary', 'espeakng-loader>=0.2.4', 'phonemizer>=3.4.0', 'dlinfo>=2.0.0'],
            capture_output=True,
        )
        if res1.returncode != 0:
            err = res1.stderr.decode('utf-8', errors='replace')[-400:]
            raise RuntimeError(f'Could not install Kokoro phonemizer dependencies: {err}')
        res2 = process.run(
            [sys.executable, '-m', 'pip', 'install', '--no-deps', 'kokoro-onnx==0.6.1'],
            capture_output=True,
        )
        if res2.returncode != 0:
            err = res2.stderr.decode('utf-8', errors='replace')[-400:]
            raise RuntimeError(f'Could not install kokoro-onnx package: {err}')
    for filename, url in KOKORO_MODEL_URLS.items():
        dest = kdir / filename
        if dest.is_file() and dest.stat().st_size > 5_000_000:
            continue
        part = kdir / f'.{filename}.part'
        report(f'Downloading {filename}…')
        try:
            with requests.get(url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get('Content-Length') or 0)
                downloaded = 0
                with open(part, 'wb') as handle:
                    for chunk in resp.iter_content(chunk_size=1024 * 512):
                        process.check_cancelled()
                        if chunk:
                            handle.write(chunk)
                            downloaded += len(chunk)
                            if total > 0:
                                pct = min(99, int(downloaded * 100 / total))
                                report(f'Downloading {filename} ({pct}%)…')
            os.replace(part, dest)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    report('Kokoro-82M local voice engine is ready.')
    return kokoro_status(app_root)


def map_kokoro_phoneme_timings_to_words(text: str, spoken_timings: list[Any], total_duration: float) -> list[dict[str, Any]]:
    """Map Kokoro phoneme timings (space-delimited groups) or proportional character lengths to word timestamps."""
    raw_words = [w for w in str(text or '').split() if w.strip()]
    if not raw_words or total_duration <= 0.02:
        return []
    groups: list[tuple[float, float]] = []
    cur_start: float | None = None
    cur_end: float = 0.0
    for item in spoken_timings or []:
        phoneme = getattr(item, 'phoneme', '') if not isinstance(item, dict) else item.get('phoneme', '')
        start = float(getattr(item, 'start', 0.0) if not isinstance(item, dict) else item.get('start', 0.0))
        end = float(getattr(item, 'end', 0.0) if not isinstance(item, dict) else item.get('end', 0.0))
        if phoneme == ' ':
            if cur_start is not None and cur_end > cur_start:
                groups.append((cur_start, cur_end))
            cur_start = None
        else:
            if cur_start is None:
                cur_start = start
            cur_end = max(cur_end, end)
    if cur_start is not None and cur_end > cur_start:
        groups.append((cur_start, cur_end))

    if len(groups) == len(raw_words):
        result = []
        prev = 0.0
        for word_str, (g_start, g_end) in zip(raw_words, groups):
            a = max(prev, round(g_start, 3))
            b = min(round(total_duration, 3), max(round(a + 0.04, 3), round(g_end, 3)))
            if b > a:
                result.append({'start': a, 'end': b, 'text': word_str})
                prev = b
        if len(result) == len(raw_words):
            return result

    # Proportional character-length fallback when numbers/abbreviations expand into multiple phoneme groups
    weights = [max(1, len(re.sub(r'\W+', '', w)) or 1) for w in raw_words]
    total_weight = sum(weights)
    cursor = 0.0
    fallback = []
    for idx, (word_str, weight) in enumerate(zip(raw_words, weights)):
        span = total_duration * (weight / total_weight)
        start = round(cursor, 3)
        end = round(total_duration if idx == len(raw_words) - 1 else min(total_duration, cursor + span), 3)
        if end > start:
            fallback.append({'start': start, 'end': end, 'text': word_str})
        cursor += span
    return fallback


def _samples_to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    clipped = np.clip(np.asarray(samples, dtype=np.float32).ravel(), -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype('<i2')
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def synthesize_kokoro(
    text: str,
    voice: str = 'af_heart',
    *,
    speed: float = 1.0,
    blend_voice: str = '',
    blend_ratio: float = 0.0,
    app_root: Path | None = None,
) -> tuple[bytes, str, list[dict[str, Any]]]:
    """Synthesize speech locally using Kokoro-82M ONNX. Returns ``(wav_bytes, '.wav', word_timings)``."""
    cleaned = clean_tts_text(text)
    if not cleaned:
        raise ValueError('Cannot synthesize an empty caption line.')
    status = kokoro_status(app_root)
    if not status['installed']:
        raise ValueError('Local Kokoro-82M voice pack is not installed yet. Click "Install Local Kokoro AI" first.')
    kdir = kokoro_dir(app_root)
    model_path = str(kdir / 'kokoro-v1.0.fp16.onnx')
    voices_path = str(kdir / 'voices-v1.0.bin')
    with _KOKORO_THREAD_LOCK:
        kokoro = _KOKORO_CACHE.get(model_path)
        if kokoro is None:
            from kokoro_onnx import Kokoro
            kokoro = Kokoro(model_path, voices_path)
            _KOKORO_CACHE[model_path] = kokoro
        voice_meta = next((v for v in KOKORO_VOICES if v['id'] == voice), KOKORO_VOICES[0])
        espeak_lang = voice_meta.get('espeak_lang', 'en-us')
        style_vec = kokoro.get_voice_style(voice_meta['id'])
        blend_ratio = max(0.0, min(1.0, float(blend_ratio or 0.0)))
        if blend_voice and blend_voice != voice_meta['id'] and blend_ratio > 0.01:
            if any(v['id'] == blend_voice for v in KOKORO_VOICES):
                secondary = kokoro.get_voice_style(blend_voice)
                style_vec = ((1.0 - blend_ratio) * style_vec + blend_ratio * secondary).astype(np.float32)
        spd = max(0.5, min(2.0, float(speed or 1.0)))
        samples, sample_rate, spoken = kokoro.create_timed(cleaned, style_vec, speed=spd, lang=espeak_lang)
    total_dur = len(samples) / float(sample_rate) if sample_rate else 0.0
    words = map_kokoro_phoneme_timings_to_words(cleaned, spoken, total_dur)
    return _samples_to_wav_bytes(samples, sample_rate), '.wav', words


# ------------------------------------------------------------------
# 3. ElevenLabs Studio API (with-timestamps + line context continuity)
# ------------------------------------------------------------------

def read_narrator_keys(captions_root: Path) -> dict[str, str]:
    key_file = Path(captions_root) / 'narrator_keys.json'
    stored = read_json_with_backup(key_file, {}, validate=lambda d: isinstance(d, dict))
    eleven = str(stored.get('elevenlabs') or os.environ.get('ELEVENLABS_API_KEY') or '').strip()
    return {'elevenlabs': eleven} if eleven else {}


def save_narrator_key(captions_root: Path, elevenlabs_key: str) -> dict[str, bool]:
    key_file = Path(captions_root) / 'narrator_keys.json'
    data = read_json_with_backup(key_file, {}, validate=lambda d: isinstance(d, dict))
    cleaned = str(elevenlabs_key or '').strip()
    if cleaned:
        if len(cleaned) > 240 or any(c in cleaned for c in '\r\n\t '):
            raise ValueError('Enter a valid ElevenLabs API key.')
        data['elevenlabs'] = cleaned
    else:
        data.pop('elevenlabs', None)
    atomic_write_json(key_file, data, backup=True)
    return {'elevenlabs': bool(data.get('elevenlabs') or os.environ.get('ELEVENLABS_API_KEY'))}


def list_elevenlabs_voices(api_key: str) -> list[dict[str, str]]:
    if not api_key:
        return []
    resp = requests.get(
        'https://api.elevenlabs.io/v1/voices',
        headers={'xi-api-key': api_key, 'Accept': 'application/json'},
        timeout=12,
    )
    if resp.status_code in (401, 403):
        raise ValueError('ElevenLabs API key was rejected (HTTP 401). Check your API key.')
    resp.raise_for_status()
    payload = resp.json()
    voices = []
    for item in payload.get('voices') or []:
        vid = str(item.get('voice_id') or '').strip()
        name = str(item.get('name') or '').strip()
        if not vid or not name:
            continue
        labels = item.get('labels') or {}
        gender = str(labels.get('gender') or '').capitalize()
        accent = str(labels.get('accent') or '').upper()[:12]
        use_case = str(labels.get('use_case') or labels.get('description') or item.get('category') or 'ElevenLabs Voice')
        voices.append({
            'id': vid,
            'name': name,
            'lang': 'multi',
            'gender': gender or 'Voice',
            'accent': accent or 'Studio',
            'tag': use_case[:60],
        })
    return voices


def map_elevenlabs_alignment_to_words(alignment: dict[str, Any] | None, fallback_text: str) -> list[dict[str, Any]]:
    """Group ElevenLabs character timestamps into word-level ``{start, end, text}`` timings."""
    if not isinstance(alignment, dict):
        return []
    chars = alignment.get('characters') or []
    starts = alignment.get('character_start_times_seconds') or []
    ends = alignment.get('character_end_times_seconds') or []
    if not chars or len(chars) != len(starts) or len(chars) != len(ends):
        return []
    words: list[dict[str, Any]] = []
    cur_chars: list[str] = []
    w_start: float | None = None
    w_end: float = 0.0
    for ch, st, en in zip(chars, starts, ends):
        ch_str = str(ch)
        if ch_str.isspace():
            if cur_chars and w_start is not None and w_end > w_start:
                words.append({'start': round(w_start, 3), 'end': round(w_end, 3), 'text': ''.join(cur_chars)})
            cur_chars = []
            w_start = None
        else:
            if w_start is None:
                w_start = float(st)
            w_end = max(w_end, float(en))
            cur_chars.append(ch_str)
    if cur_chars and w_start is not None and w_end > w_start:
        words.append({'start': round(w_start, 3), 'end': round(w_end, 3), 'text': ''.join(cur_chars)})
    return words


def synthesize_elevenlabs(
    text: str,
    voice_id: str,
    api_key: str,
    *,
    model_id: str = 'eleven_multilingual_v2',
    stability: float = 0.50,
    similarity_boost: float = 0.75,
    style: float = 0.15,
    previous_text: str = '',
    next_text: str = '',
) -> tuple[bytes, str, list[dict[str, Any]]]:
    """Synthesize speech with ElevenLabs `/with-timestamps`. Returns ``(mp3_bytes, '.mp3', word_timings)``."""
    cleaned = clean_tts_text(text)
    if not cleaned:
        raise ValueError('Cannot synthesize an empty caption line.')
    if not api_key:
        raise ValueError('Add your ElevenLabs API key in the Narrator panel first.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{6,64}', str(voice_id or '').strip()):
        raise ValueError('Choose a valid ElevenLabs voice.')
    body: dict[str, Any] = {
        'text': cleaned,
        'model_id': model_id if model_id in ('eleven_multilingual_v2', 'eleven_flash_v2_5', 'eleven_turbo_v2_5') else 'eleven_multilingual_v2',
        'voice_settings': {
            'stability': max(0.0, min(1.0, float(stability))),
            'similarity_boost': max(0.0, min(1.0, float(similarity_boost))),
            'style': max(0.0, min(1.0, float(style))),
            'use_speaker_boost': True,
        },
    }
    if previous_text.strip():
        body['previous_text'] = clean_tts_text(previous_text)[:500]
    if next_text.strip():
        body['next_text'] = clean_tts_text(next_text)[:500]
    resp = requests.post(
        f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id.strip()}/with-timestamps',
        headers={'xi-api-key': api_key, 'Content-Type': 'application/json', 'Accept': 'application/json'},
        json=body,
        timeout=45,
    )
    if resp.status_code in (401, 403):
        raise ValueError('ElevenLabs API key rejected or quota exceeded. Check your ElevenLabs account.')
    if resp.status_code >= 400:
        detail = ''
        try:
            detail = str((resp.json().get('detail') or {}).get('message') or resp.text)[:200]
        except Exception:
            detail = resp.text[:200]
        raise ValueError(f'ElevenLabs synthesis failed: {detail}')
    payload = resp.json()
    audio_b64 = payload.get('audio_base64') or ''
    if not audio_b64:
        raise ValueError('ElevenLabs returned no audio data.')
    audio_bytes = base64.b64decode(audio_b64)
    alignment = payload.get('normalized_alignment') or payload.get('alignment')
    words = map_elevenlabs_alignment_to_words(alignment, cleaned)
    return audio_bytes, '.mp3', words


# ------------------------------------------------------------------
# 4. Unified Synthesis Dispatch, FFmpeg Mastering & Track Assembly
# ------------------------------------------------------------------

def validate_narrator_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = {**DEFAULT_SETTINGS, **(raw if isinstance(raw, dict) else {})}
    if cfg['engine'] not in ENGINES:
        raise ValueError('Choose Microsoft Neural, Kokoro-82M Local, or ElevenLabs.')
    if cfg['tone'] not in TONE_PRESETS:
        raise ValueError('Choose a supported vocal tone preset.')
    if cfg['timing_mode'] not in TIMING_MODES:
        raise ValueError('Choose a supported narration timing mode.')
    if cfg['track'] not in SPEAK_TRACKS:
        raise ValueError('Choose whether to speak original captions, translations, or a new script.')
    cfg['rate_pct'] = max(-40, min(50, int(round(float(cfg.get('rate_pct') or 0)))))
    cfg['pitch_hz'] = max(-15, min(15, int(round(float(cfg.get('pitch_hz') or 0)))))
    cfg['speed'] = round(max(0.5, min(2.0, float(cfg.get('speed') or 1.0))), 2)
    cfg['blend_ratio'] = round(max(0.0, min(0.9, float(cfg.get('blend_ratio') or 0.0))), 2)
    cfg['stability'] = round(max(0.0, min(1.0, float(cfg.get('stability') if cfg.get('stability') is not None else 0.50))), 2)
    cfg['similarity_boost'] = round(max(0.0, min(1.0, float(cfg.get('similarity_boost') if cfg.get('similarity_boost') is not None else 0.75))), 2)
    cfg['style'] = round(max(0.0, min(1.0, float(cfg.get('style') if cfg.get('style') is not None else 0.15))), 2)
    cfg['narrator_volume'] = round(max(0.1, min(2.0, float(cfg.get('narrator_volume') if cfg.get('narrator_volume') is not None else 1.0))), 2)
    cfg['background_volume'] = round(max(0.0, min(2.0, float(cfg.get('background_volume') if cfg.get('background_volume') is not None else 0.25))), 2)
    cfg['ducking'] = bool(cfg.get('ducking', True))
    cfg['line_pause'] = round(max(0.05, min(2.0, float(cfg.get('line_pause') if cfg.get('line_pause') is not None else 0.20))), 2)
    cfg['voice'] = str(cfg.get('voice') or DEFAULT_SETTINGS['voice']).strip()[:120]
    cfg['blend_voice'] = str(cfg.get('blend_voice') or '').strip()[:80]
    return cfg


def synthesize_line_raw(
    text: str,
    settings: dict[str, Any],
    *,
    previous_text: str = '',
    next_text: str = '',
    api_key: str = '',
    app_root: Path | None = None,
) -> tuple[bytes, str, list[dict[str, Any]]]:
    """Dispatch a single line to the selected TTS engine and return ``(raw_bytes, ext, word_timings)``."""
    cfg = validate_narrator_settings(settings)
    engine = cfg['engine']
    if engine == 'edge':
        return synthesize_edge(text, cfg['voice'], rate_pct=cfg['rate_pct'], pitch_hz=cfg['pitch_hz'])
    if engine == 'kokoro':
        return synthesize_kokoro(
            text,
            cfg['voice'],
            speed=cfg['speed'],
            blend_voice=cfg['blend_voice'],
            blend_ratio=cfg['blend_ratio'],
            app_root=app_root,
        )
    return synthesize_elevenlabs(
        text,
        cfg['voice'],
        api_key,
        model_id=cfg.get('eleven_model', 'eleven_multilingual_v2'),
        stability=cfg['stability'],
        similarity_boost=cfg['similarity_boost'],
        style=cfg['style'],
        previous_text=previous_text,
        next_text=next_text,
    )


def master_line_audio(
    raw_bytes: bytes,
    raw_ext: str,
    out_wav: Path,
    *,
    tone: str = 'natural',
    atempo: float = 1.0,
    cwd: Path,
) -> float:
    """Master one synthesized line to 44.1 kHz stereo PCM WAV with broadcast LUFS and click-free fades."""
    token = uuid.uuid4().hex[:10]
    raw_path = Path(cwd) / f'.narr_raw_{token}{raw_ext}'
    tmp_wav = Path(cwd) / f'.narr_tmp_{token}.wav'
    try:
        raw_path.write_bytes(raw_bytes)
        filters: list[str] = [
            'silenceremove=start_periods=1:start_duration=0.01:start_threshold=-50dB',
        ]
        tempo = max(0.85, min(1.25, float(atempo or 1.0)))
        if abs(tempo - 1.0) > 0.01:
            filters.append(f'atempo={tempo:.4f}')
        tone_filter = TONE_PRESETS.get(tone, TONE_PRESETS['natural'])['filter']
        filters.append(tone_filter)
        filters.append('afade=t=in:st=0:d=0.015')
        filters.append('aformat=sample_rates=44100:channel_layouts=stereo')
        cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-y',
            '-i', raw_path.name,
            '-vn', '-af', ','.join(filters),
            '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le',
            tmp_wav.name,
        ]
        res = process.run(cmd, cwd=cwd, capture_output=True)
        if res.returncode != 0:
            err = res.stderr.decode('utf-8', errors='replace')[-400:]
            raise ValueError(f'Audio mastering failed: {err}')
        with wave.open(str(tmp_wav), 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            raw_pcm = np.frombuffer(wf.readframes(frames), dtype='<i2').copy()
        duration = frames / float(rate) if rate else 0.0
        # Apply a 15ms cosine fade-out on the exact tail samples so line ends never click
        fade_samples = min(frames, int(0.015 * rate))
        if fade_samples > 4 and len(raw_pcm) >= fade_samples * 2:
            ramp = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
            stereo_View = raw_pcm.reshape(-1, 2)
            stereo_View[-fade_samples:, 0] = (stereo_View[-fade_samples:, 0].astype(np.float32) * ramp).astype('<i2')
            stereo_View[-fade_samples:, 1] = (stereo_View[-fade_samples:, 1].astype(np.float32) * ramp).astype('<i2')
            with wave.open(str(tmp_wav), 'wb') as wf_out:
                wf_out.setnchannels(2)
                wf_out.setsampwidth(2)
                wf_out.setframerate(44100)
                wf_out.writeframes(stereo_View.tobytes())
        os.replace(tmp_wav, out_wav)
        return max(0.05, round(duration, 3))
    finally:
        raw_path.unlink(missing_ok=True)
        tmp_wav.unlink(missing_ok=True)


def scale_word_timings_to_cue(
    raw_words: list[dict[str, Any]],
    text: str,
    cue_start: float,
    cue_end: float,
) -> list[dict[str, Any]]:
    """Shift and scale relative word timings ``[0..raw_end]`` into absolute timeline ``[cue_start, cue_end]``."""
    span = max(0.05, float(cue_end) - float(cue_start))
    tokens = [w for w in str(text or '').split() if w.strip()]
    if not tokens:
        return []
    if raw_words and len(raw_words) == len(tokens):
        raw_max = max(float(w.get('end', 0.0)) for w in raw_words)
        scale = span / raw_max if raw_max > 0.02 else 1.0
        scaled: list[dict[str, Any]] = []
        prev = round(cue_start, 3)
        for token, w in zip(tokens, raw_words):
            a = max(prev, round(cue_start + float(w.get('start', 0.0)) * scale, 3))
            b = min(round(cue_end, 3), max(round(a + 0.03, 3), round(cue_start + float(w.get('end', 0.0)) * scale, 3)))
            if b > a:
                scaled.append({'start': a, 'end': b, 'text': token})
                prev = b
        if len(scaled) == len(tokens):
            scaled[-1]['end'] = round(max(scaled[-1]['start'] + 0.03, cue_end), 3)
            return scaled
    return map_kokoro_phoneme_timings_to_words(text, [], span) and [
        {
            'start': round(cue_start + w['start'], 3),
            'end': round(min(cue_end, cue_start + w['end']), 3),
            'text': w['text'],
        }
        for w in map_kokoro_phoneme_timings_to_words(text, [], span)
    ]


def build_voice_bus_wav(
    placements: list[tuple[float, Path]],
    total_duration: float,
    out_voice_wav: Path,
    *,
    narrator_volume: float = 1.0,
) -> None:
    """Place each 44.1 kHz stereo line WAV at its exact start timestamp in a sample-accurate stereo buffer."""
    sample_rate = 44100
    total_frames = max(int(math.ceil(max(0.2, float(total_duration)) * sample_rate)), 4410)
    bus = np.zeros((total_frames, 2), dtype=np.float32)
    vol = max(0.0, min(2.5, float(narrator_volume)))
    for start_sec, wav_path in placements:
        if not wav_path.is_file():
            continue
        with wave.open(str(wav_path), 'rb') as wf:
            frames = wf.getnframes()
            channels = wf.getnchannels()
            pcm = np.frombuffer(wf.readframes(frames), dtype='<i2').astype(np.float32) / 32768.0
        if channels == 1:
            stereo = np.column_stack([pcm, pcm])
        else:
            stereo = pcm.reshape(-1, channels)[:, :2]
        offset = max(0, int(round(float(start_sec) * sample_rate)))
        needed = offset + len(stereo)
        if needed > len(bus):
            bus = np.pad(bus, ((0, needed - len(bus)), (0, 0)), mode='constant')
        bus[offset:offset + len(stereo)] += stereo * vol
    clipped = np.clip(bus, -1.0, 1.0)
    pcm_out = (clipped * 32767.0).astype('<i2')
    with wave.open(str(out_voice_wav), 'wb') as wf_out:
        wf_out.setnchannels(2)
        wf_out.setsampwidth(2)
        wf_out.setframerate(sample_rate)
        wf_out.writeframes(pcm_out.tobytes())


def mix_voice_with_background(
    voice_wav: Path,
    background_media: Path | None,
    total_duration: float,
    out_master_wav: Path,
    *,
    background_volume: float = 0.25,
    ducking: bool = True,
    cwd: Path,
) -> None:
    """Mix the assembled voice bus with the original project audio using optional sidechain ducking."""
    bg_vol = max(0.0, min(2.0, float(background_volume)))
    has_bg = False
    if background_media and background_media.is_file() and bg_vol > 0.005:
        probe = process.run([imageio_ffmpeg.get_ffmpeg_exe(), '-i', str(background_media)], capture_output=True)
        has_bg = b'Audio:' in probe.stderr
    if not has_bg:
        # Voice only
        cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-y',
            '-i', voice_wav.name,
            '-t', f'{float(total_duration):.3f}',
            '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le',
            out_master_wav.name,
        ]
        res = process.run(cmd, cwd=cwd, capture_output=True)
        if res.returncode != 0:
            raise ValueError('Failed to finalize narration audio track.')
        return

    if ducking:
        # Dynamic sidechain compression: background audio ducks smoothly ONLY while the narrator speaks
        graph = (
            f'[0:a]aformat=sample_rates=44100:channel_layouts=stereo,asplit=2[voice_sc][voice_mix];'
            f'[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={bg_vol:.4f},apad,atrim=duration={float(total_duration):.3f}[bg];'
            f'[bg][voice_sc]sidechaincompress=threshold=0.018:ratio=6:attack=35:release=380:makeup=1[bg_ducked];'
            f'[voice_mix][bg_ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]'
        )
    else:
        graph = (
            f'[0:a]aformat=sample_rates=44100:channel_layouts=stereo[voice_mix];'
            f'[1:a]aformat=sample_rates=44100:channel_layouts=stereo,volume={bg_vol:.4f},apad,atrim=duration={float(total_duration):.3f}[bg];'
            f'[voice_mix][bg]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]'
        )
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-y',
        '-i', voice_wav.name,
        '-i', background_media.name,
        '-filter_complex', graph,
        '-map', '[aout]',
        '-t', f'{float(total_duration):.3f}',
        '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le',
        out_master_wav.name,
    ]
    res = process.run(cmd, cwd=cwd, capture_output=True)
    if res.returncode != 0:
        err = res.stderr.decode('utf-8', errors='replace')[-400:]
        raise ValueError(f'Failed to mix narration with background audio: {err}')


def catalog_payload(captions_root: Path, app_root: Path | None = None, language: str = '') -> dict[str, Any]:
    """Return the full narrator catalog, local Kokoro status, and ElevenLabs voices if configured."""
    keys = read_narrator_keys(captions_root)
    kokoro_info = kokoro_status(app_root)
    lang = str(language or '').strip().lower()
    if '-' in lang:
        lang = lang.split('-', 1)[0]
    edge_list = [v for v in EDGE_VOICES if not lang or v['lang'] == lang] or EDGE_VOICES
    kokoro_list = [v for v in KOKORO_VOICES if not lang or v['lang'] == lang] or KOKORO_VOICES
    eleven_voices: list[dict[str, str]] = []
    eleven_error = None
    if keys.get('elevenlabs'):
        try:
            eleven_voices = list_elevenlabs_voices(keys['elevenlabs'])
        except Exception as exc:
            eleven_error = str(exc)
    return {
        'engines': [
            {'id': 'edge', 'name': 'Microsoft Neural (Free · 14 Languages)', 'local': False, 'ready': True},
            {'id': 'kokoro', 'name': 'Kokoro-82M Local AI (100% Offline)', 'local': True, 'ready': kokoro_info['installed']},
            {'id': 'elevenlabs', 'name': 'ElevenLabs Studio (API Key)', 'local': False, 'ready': bool(keys.get('elevenlabs'))},
        ],
        'voices': {
            'edge': edge_list,
            'edge_all': EDGE_VOICES,
            'kokoro': kokoro_list,
            'kokoro_all': KOKORO_VOICES,
            'elevenlabs': eleven_voices,
        },
        'tones': [
            {'id': k, 'label': v['label']} for k, v in TONE_PRESETS.items()
        ],
        'kokoro': kokoro_info,
        'elevenlabs_configured': bool(keys.get('elevenlabs')),
        'elevenlabs_error': eleven_error,
        'defaults': DEFAULT_SETTINGS,
        'samples': PREVIEW_SAMPLES,
    }
