from .debug import KisekaeDebugJSON, KisekaeDebugPrompt
from .preset_io import KisekaeLoadPreset
from .prompt import KisekaePrompt
from .section import SECTION_NAMES, SECTION_NODES

NODE_CLASS_MAPPINGS = {
    "KisekaeLoadPreset": KisekaeLoadPreset,
    **SECTION_NODES,
    "KisekaePrompt": KisekaePrompt,
    "KisekaeDebugJSON": KisekaeDebugJSON,
    "KisekaeDebugPrompt": KisekaeDebugPrompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "KisekaeLoadPreset": "👘 Kisekae Load Preset",
    **SECTION_NAMES,
    "KisekaePrompt": "👘 Kisekae Prompt",
    "KisekaeDebugJSON": "👘 Kisekae Debug JSON",
    "KisekaeDebugPrompt": "👘 Kisekae Debug Prompt",
}
