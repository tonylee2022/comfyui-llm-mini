from .chat import ApiChatNode, PersonaNode, PersonaManagerNode
from .image import NODE_CLASS_MAPPINGS as IMAGE_NODE_CLASS_MAPPINGS
from .image import NODE_DISPLAY_NAME_MAPPINGS as IMAGE_NODE_DISPLAY_NAME_MAPPINGS
from .manager import LLMMiniProviderManager
from .video import NODE_CLASS_MAPPINGS as VIDEO_NODE_CLASS_MAPPINGS
from .video import NODE_DISPLAY_NAME_MAPPINGS as VIDEO_NODE_DISPLAY_NAME_MAPPINGS

NODE_CLASS_MAPPINGS = {
    "LLMMiniApiChat": ApiChatNode,
    "LLMMiniLoadPersona": PersonaNode,
    "LLMMiniPersonaManager": PersonaManagerNode,
    "LLMMiniProviderManager": LLMMiniProviderManager,
}
NODE_CLASS_MAPPINGS.update(IMAGE_NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(VIDEO_NODE_CLASS_MAPPINGS)

NODE_DISPLAY_NAME_MAPPINGS = {
    "LLMMiniApiChat": "API Chat",
    "LLMMiniLoadPersona": "Load Persona",
    "LLMMiniPersonaManager": "Persona Manager",
    "LLMMiniProviderManager": "Provider Manager",
}
NODE_DISPLAY_NAME_MAPPINGS.update(IMAGE_NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(VIDEO_NODE_DISPLAY_NAME_MAPPINGS)
