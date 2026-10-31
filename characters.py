"""Universal Character Profile Library for AI Influencers and Creators.

Manages character identities (e.g. @Airi), reference images (portrait & triptych
turnaround sheets), and prompt templates for Google Flow and Nano Banana.
All character data is safely persisted in the user's Documents directory.
"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import uuid

DATA_DIR = Path(os.environ.get('MEDIA_GRABBER_DATA_DIR') or Path.home() / 'Documents' / 'Media Grabber')
CHARACTERS_DIR = DATA_DIR / 'Characters'
CHARACTERS_FILE = CHARACTERS_DIR / 'characters.json'


def _ensure_storage():
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)
    if not CHARACTERS_FILE.exists():
        default_seed = [
            {
                "id": "airi",
                "name": "Airi",
                "tag": "@Airi",
                "bio": "Virtual AI singer and influencer with a futuristic R&B and hip-hop aesthetic.",
                "trigger_prompt": "Airi, 22yo Japanese virtual singer, dark purple highlighted bob haircut, amber eyes, subtle silver ear cuff, streetwear cropped oversized hoodie, cinematic lighting, 8k masterpiece",
                "negative_prompt": "blurry, low quality, distorted anatomy, extra limbs, mutated fingers, face alteration",
                "aspect_ratio": "9:16",
                "portrait_file": "",
                "triptych_file": ""
            }
        ]
        CHARACTERS_FILE.write_text(json.dumps(default_seed, indent=2, ensure_ascii=False), encoding='utf-8')


def list_characters():
    _ensure_storage()
    try:
        data = json.loads(CHARACTERS_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_character(character_id):
    chars = list_characters()
    for c in chars:
        if c.get('id') == character_id or c.get('tag', '').lower() == character_id.lower() or c.get('name', '').lower() == character_id.lower():
            return copy.deepcopy(c)
    return None


def save_character(payload):
    chars = list_characters()
    cid = payload.get('id') or payload.get('name', '').lower().replace(' ', '_') or uuid.uuid4().hex[:8]
    cid = re.sub(r'[^a-zA-Z0-9_\-]', '', cid)
    if not cid:
        cid = uuid.uuid4().hex[:8]

    name = str(payload.get('name') or cid).strip()
    tag = payload.get('tag') or ('@' + name.replace(' ', ''))
    if not tag.startswith('@'):
        tag = '@' + tag

    record = {
        "id": cid,
        "name": name,
        "tag": tag,
        "bio": str(payload.get('bio', '')).strip(),
        "trigger_prompt": str(payload.get('trigger_prompt', '')).strip(),
        "negative_prompt": str(payload.get('negative_prompt', '')).strip(),
        "aspect_ratio": str(payload.get('aspect_ratio', '9:16')).strip(),
        "portrait_file": str(payload.get('portrait_file', '')).strip(),
        "triptych_file": str(payload.get('triptych_file', '')).strip()
    }

    updated = False
    for i, c in enumerate(chars):
        if c.get('id') == cid:
            # preserve existing image files if not provided in payload
            if not record['portrait_file'] and c.get('portrait_file'):
                record['portrait_file'] = c['portrait_file']
            if not record['triptych_file'] and c.get('triptych_file'):
                record['triptych_file'] = c['triptych_file']
            chars[i] = record
            updated = True
            break
    if not updated:
        chars.append(record)

    CHARACTERS_FILE.write_text(json.dumps(chars, indent=2, ensure_ascii=False), encoding='utf-8')
    return record


def delete_character(character_id):
    chars = list_characters()
    filtered = [c for c in chars if c.get('id') != character_id]
    if len(filtered) != len(chars):
        CHARACTERS_FILE.write_text(json.dumps(filtered, indent=2, ensure_ascii=False), encoding='utf-8')
        # delete folder if exists
        char_media = CHARACTERS_DIR / character_id
        if char_media.is_dir():
            try:
                shutil.rmtree(char_media)
            except Exception:
                pass
        return True
    return False


def save_character_image(character_id, image_type, filename, raw_bytes):
    _ensure_storage()
    char_media = CHARACTERS_DIR / character_id
    char_media.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower() or '.png'
    dest_name = f"{image_type}{ext}"
    dest_path = char_media / dest_name
    dest_path.write_bytes(raw_bytes)

    chars = list_characters()
    for c in chars:
        if c.get('id') == character_id:
            if image_type == 'portrait':
                c['portrait_file'] = dest_name
            elif image_type == 'triptych':
                c['triptych_file'] = dest_name
            break
    CHARACTERS_FILE.write_text(json.dumps(chars, indent=2, ensure_ascii=False), encoding='utf-8')
    return dest_name


def get_image_path(character_id, filename):
    char_media = CHARACTERS_DIR / character_id
    path = char_media / filename
    return path if path.is_file() else None
