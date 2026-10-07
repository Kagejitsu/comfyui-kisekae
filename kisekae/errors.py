class KisekaeError(Exception):
    """A user-facing error: bad preset, bad reference, bad template.

    Messages are written to be shown as-is in ComfyUI's error dialog.
    """
