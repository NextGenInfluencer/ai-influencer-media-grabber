"""Locality guard for Ollama models and the pinned built-in Qwen3-4B metadata.

Lyric translation itself runs through ``ai_core.translate`` (never cloud). This module keeps
the metadata check that refuses Ollama models proxied to a remote host before any lyrics
are sent, plus the verified Qwen3-4B file pin shared with the AI catalog.
"""
import requests

from job_process import check_cancelled

MODEL_SIZE = 2497280256
MODEL_SHA256 = '7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'
MODEL_URL = ('https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/'
             'bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf')
LOCAL_URL = 'http://127.0.0.1:11434'


def require_local_ollama_model(model):
    """Inspect metadata before sending lyrics: localhost can proxy cloud models."""
    check_cancelled()
    try:
        response = requests.post(LOCAL_URL + '/api/show', json={'model': model},
                                 timeout=(5, 10), allow_redirects=False)
        response.raise_for_status()
        metadata = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ValueError('Cannot verify that this Ollama model runs locally. Choose the built-in Qwen translator or a downloaded local model.') from exc
    if (response.status_code != 200 or not isinstance(metadata, dict)
            or metadata.get('remote_host') or metadata.get('remote_model')
            or not isinstance(metadata.get('model_info'), dict)
            or not metadata['model_info']):
        raise ValueError('This Ollama model is remote or cannot be verified as local. No lyrics were sent. Choose a downloaded local model.')
    check_cancelled()
