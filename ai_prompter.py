from ai_runtime import serialized
import os
import threading
import gc
from PIL import Image

_blip_processor = None
_blip_model = None
_blip_timer = None

def is_ai_vision_available():
    try:
        import torch
        import transformers
        return True
    except ImportError:
        return False

@serialized
def unload_blip():
    global _blip_processor, _blip_model, _blip_timer
    if _blip_model is not None:
        print("Unloading BLIP model to free memory...")
        _blip_processor = None
        _blip_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()
    _blip_timer = None

@serialized
def get_blip_model():
    global _blip_processor, _blip_model, _blip_timer
    
    if _blip_timer is not None:
        _blip_timer.cancel()
        
    if _blip_model is None:
        try:
            import torch
            from transformers import BlipProcessor, BlipForConditionalGeneration
            # Use local cache if possible to avoid re-downloads
            _blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-large", use_safetensors=True)
            _blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-large", use_safetensors=True)
            
            # Use GPU if available, else CPU
            device = "cuda" if torch.cuda.is_available() else "cpu"
            _blip_model.to(device)
        except ImportError:
            print("Error: PyTorch or Transformers not installed.")
            return None, None
        except Exception as e:
            print(f"Error loading BLIP model: {e}")
            return None, None
            
    _blip_timer = threading.Timer(600, unload_blip)
    _blip_timer.daemon = True
    _blip_timer.start()
    return _blip_processor, _blip_model

@serialized
def extract_prompt_from_image(image_path):
    if not is_ai_vision_available():
        return "Error: AI Pack not installed. Please install the AI Engine pack to use prompt extraction."
        
    processor, model = get_blip_model()
    if not processor or not model:
        return "Error: Vision model could not be loaded. Please check your internet connection or GPU/RAM."
        
    try:
        import torch
        raw_image = Image.open(image_path).convert('RGB')
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        text_prefix = "a photo of "
        inputs_desc = processor(raw_image, text=text_prefix, return_tensors="pt").to(device)  # type: ignore
        out_desc = model.generate(
            **inputs_desc, 
            max_length=150,
            num_beams=4,
            repetition_penalty=1.5
        )
        detailed_caption = processor.decode(out_desc[0], skip_special_tokens=True)
        
        prompt = (
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
            "Prioritize alignment with the first frame over creative changes.\n\n"
            "Optional automatically generated scene description (may be inaccurate; "
            "use the actual images as the authority and ignore conflicting details):\n"
            f"{detailed_caption}"
        )
        return prompt
        
    except Exception as e:
        return f"Error analyzing image: {str(e)}"
