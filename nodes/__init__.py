from . import routes  # noqa: F401  (registers the Tansu page and API on ComfyUI's server)
from .debug import KisekaeDebugJSON, KisekaeDebugPrompt
from .preset_io import KisekaeLoadPreset, KisekaeSavePreset
from .prompt import KisekaePrompt
from .section import SECTION_NAMES, SECTION_NODES

NODE_CLASS_MAPPINGS = {
    "KisekaeLoadPreset": KisekaeLoadPreset,
    **SECTION_NODES,
    "KisekaePrompt": KisekaePrompt,
    "KisekaeSavePreset": KisekaeSavePreset,
    "KisekaeDebugJSON": KisekaeDebugJSON,
    "KisekaeDebugPrompt": KisekaeDebugPrompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "KisekaeLoadPreset": "👘 Kisekae Load Preset",
    **SECTION_NAMES,
    "KisekaePrompt": "👘 Kisekae Prompt",
    "KisekaeSavePreset": "👘 Kisekae Save Preset",
    "KisekaeDebugJSON": "👘 Kisekae Debug JSON",
    "KisekaeDebugPrompt": "👘 Kisekae Debug Prompt",
}
