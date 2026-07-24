import os
import torch
from PIL import Image

_blip_processor = None
_blip_model = None

def get_blip_model():
    global _blip_processor, _blip_model
    if _blip_model is None:
        try:
            from transformers import BlipProcessor, BlipForConditionalGeneration
            # Use local cache if possible to avoid re-downloads
            _blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base", use_safetensors=True)
            _blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base", use_safetensors=True)
            
            # Use GPU if available, else CPU
            device = "cuda" if torch.cuda.is_available() else "cpu"
            _blip_model.to(device)
        except Exception as e:
            print(f"Error loading BLIP model: {e}")
            return None, None
            
    return _blip_processor, _blip_model

def extract_prompt_from_image(image_path):
    processor, model = get_blip_model()
    if not processor or not model:
        return "Error: Vision model not loaded. Please restart the app or check dependencies."
        
    try:
        raw_image = Image.open(image_path).convert('RGB')
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Generate basic caption
        inputs = processor(raw_image, return_tensors="pt").to(device)
        out = model.generate(**inputs, max_length=150)
        basic_caption = processor.decode(out[0], skip_special_tokens=True)
        
        # Generate descriptive details
        text_prefix = "a cinematic photorealistic shot of "
        inputs_desc = processor(raw_image, text=text_prefix, return_tensors="pt").to(device)
        out_desc = model.generate(**inputs_desc, max_length=150)
        detailed_caption = processor.decode(out_desc[0], skip_special_tokens=True)
        
        # Format as a high-quality AI prompt
        prompt = f"{detailed_caption}, highly detailed, 8k resolution, cinematic lighting, photorealistic --ar 9:16"
        return prompt
        
    except Exception as e:
        return f"Error analyzing image: {str(e)}"
