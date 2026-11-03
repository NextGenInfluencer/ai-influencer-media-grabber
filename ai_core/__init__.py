"""Local AI layer for AI Influencer Media Grabber (v5).

Modules are imported lazily by callers; importing ``ai_core`` itself is cheap and
never loads torch, onnxruntime or llama.cpp.
"""
from .errors import AIUnavailable, ConsentRequired, ModelMissing

__all__ = ['AIUnavailable', 'ConsentRequired', 'ModelMissing']
