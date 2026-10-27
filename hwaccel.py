"""Compatibility import for the encoder shipped in the OTA-compatible assets payload."""
import sys
from assets import hwaccel as _implementation
sys.modules[__name__] = _implementation
