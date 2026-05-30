from .chat import ApiChatNode, PersonaNode, PersonaManagerNode
from .image import OpenAICodexImageNode, XAIImagineNode, GoogleImagenNode, GoogleGeminiNanoBananaNode, GoogleGeminiNanoBananaProNode, GoogleGeminiNanoBanana2Node
from .video import XAIVideoEditNode, XAIVideoExtendNode, XAIVideoNode, XAIVideoReferenceNode

NODE_CLASS_MAPPINGS = {
    "LLMMiniApiChat": ApiChatNode,
    "LLMMiniLoadPersona": PersonaNode,
    "LLMMiniPersonaManager": PersonaManagerNode,
    "LLMMiniOpenAICodexImage": OpenAICodexImageNode,
    "LLMMiniXAIImagine": XAIImagineNode,
    "LLMMiniGoogleImagen": GoogleImagenNode,
    "LLMMiniGoogleGeminiNanoBanana": GoogleGeminiNanoBananaNode,
    "LLMMiniGoogleGeminiNanoBananaPro": GoogleGeminiNanoBananaProNode,
    "LLMMiniGoogleGeminiNanoBanana2": GoogleGeminiNanoBanana2Node,
    "LLMMiniXAIVideo": XAIVideoNode,
    "LLMMiniXAIVideoReference": XAIVideoReferenceNode,
    "LLMMiniXAIVideoEdit": XAIVideoEditNode,
    "LLMMiniXAIVideoExtend": XAIVideoExtendNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LLMMiniApiChat": "API Chat",
    "LLMMiniLoadPersona": "Load Persona",
    "LLMMiniPersonaManager": "Persona Manager",
    "LLMMiniOpenAICodexImage": "OpenAI/Codex Image",
    "LLMMiniXAIImagine": "xAI Imagine",
    "LLMMiniGoogleImagen": "Google Imagen",
    "LLMMiniGoogleGeminiNanoBanana": "Nano Banana",
    "LLMMiniGoogleGeminiNanoBananaPro": "Nano Banana Pro",
    "LLMMiniGoogleGeminiNanoBanana2": "Nano Banana 2",
    "LLMMiniXAIVideo": "xAI Video",
    "LLMMiniXAIVideoReference": "xAI Multi-Reference Video",
    "LLMMiniXAIVideoEdit": "xAI Video Edit",
    "LLMMiniXAIVideoExtend": "xAI Video Extend",
}
