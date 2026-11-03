"""Kling / Nano Banana identity-edit prompt builder fed by a structured local scene description."""
from ai_core import vision

PRESERVATION_PROMPT = (
    "Edit Image 1, the original first frame from my motion-reference video. "
    "Use Image 2 (and any additional influencer reference images) only as the "
    "identity reference for my AI influencer. Return one edited image.\n\n"
    "Replace the main foreground person's identity with my influencer's identity: "
    "match the reference face, facial features, skin tone, and hair. Adapt those "
    "features naturally to the original head angle, expression, gaze, and lighting. "
    "Do not copy the reference image's pose, clothes, background, or lighting. "
    "If several people are equally prominent, ask me which person to replace.\n\n"
    "Preserve Image 1's pose, body placement and scale, head angle, expression, "
    "gaze direction, hand positions, and visible body proportions. Keep the "
    "original clothing, accessories, and held objects. Fit the influencer's hair "
    "naturally around the existing pose and preserve foreground overlaps.\n\n"
    "Keep the camera angle, perspective, crop, framing, aspect ratio, and canvas "
    "dimensions unchanged. Preserve the background, other people, objects, text, "
    "and the scene's existing lighting, shadows, colors, focus, and texture. "
    "Only adjust the replaced person's appearance and necessary boundary blending. "
    "Do not recompose, zoom, beautify the scene, add objects, or apply cinematic styling.\n\n"
    "This image will be paired with the original video for Kling motion control. "
    "Prioritize alignment with the first frame over creative changes."
)
SCENE_FIELDS = (
    ('subject', 'Subject'), ('wardrobe', 'Outfit to keep'), ('action', 'Pose / action to keep'),
    ('camera', 'Camera and framing to keep'), ('lighting', 'Lighting to keep'), ('setting', 'Setting'),
    ('mood', 'Mood'),
)


def _clean(value, limit=300):
    text = ' '.join(str(value or '').split())
    return text[:limit]


def build_prompt(description):
    """Full editing prompt: the fixed preservation rules plus the (uncertain) scene details."""
    description = description if isinstance(description, dict) else {}
    details = [f'- {label}: {_clean(description.get(key))}' for key, label in SCENE_FIELDS if _clean(description.get(key))]
    colors = [c for c in (_clean(color, 40) for color in description.get('colors') or []) if c]
    if colors:
        details.append('- Main colors to keep: ' + ', '.join(colors[:6]))
    summary = _clean(description.get('summary'), 600)
    if summary:
        details.insert(0, f'- Summary: {summary}')
    if not details:
        return PRESERVATION_PROMPT
    source = _clean(description.get('source'), 80) or 'local vision model'
    return (f'{PRESERVATION_PROMPT}\n\n'
            f'Automatically generated scene description ({source}; may be inaccurate — use the actual '
            'images as the authority and ignore conflicting details):\n' + '\n'.join(details))


def extract_prompt_from_image(image_path):
    """Describe the frame locally (VLM, or BLIP-base on CPU) and build the editing prompt.

    Raises ``ai_core.AIUnavailable`` with a setup hint when no local vision model is installed;
    nothing is downloaded here.
    """
    return build_prompt(vision.describe_scene(image_path))
