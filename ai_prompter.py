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
        
        text_prefix = "a highly detailed, cinematic photorealistic shot of "
        inputs_desc = processor(raw_image, text=text_prefix, return_tensors="pt").to(device)
        out_desc = model.generate(
            **inputs_desc, 
            max_length=150,
            min_length=20,
            num_beams=4,
            repetition_penalty=1.5
        )
        detailed_caption = processor.decode(out_desc[0], skip_special_tokens=True)
        
        prompt = (
            f"Generate a photorealistic image matching this exact scene: {detailed_caption}. "
            f"The main subject is [YOUR CHARACTER NAME/REFERENCE]. "
            f"Please maintain the exact same pose, lighting, mood, and framing as described. "
            f"High quality, highly detailed, 8k resolution, masterpiece."
        )
        return prompt
        
    except Exception as e:
        return f"Error analyzing image: {str(e)}"
