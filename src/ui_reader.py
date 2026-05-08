import subprocess
import xml.etree.ElementTree as ET
import json
import time
import sys
from pathlib import Path


ADB = "E:/AA/platform-tools/adb.exe"

# Nodes that are purely layout containers — no user-visible info
CONTAINER_CLASSES = {
    "android.widget.FrameLayout",
    "android.widget.LinearLayout",
    "android.widget.RelativeLayout",
    "android.widget.GridLayout",
    "android.widget.TableLayout",
    "android.widget.ScrollView",
    "android.widget.HorizontalScrollView",
    "android.view.ViewGroup",
}


def adb(*args, timeout=15):
    """Run an ADB command, return stdout or raise on failure."""
    cmd = [ADB, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ADB failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def _local_path():
    return str(Path(__file__).parent.parent / "tmp_ui_dump.xml")


def dump_ui_tree():
    """Dump the current screen's UI hierarchy as XML and return the raw file path on device."""
    adb("shell", "uiautomator", "dump", "/sdcard/ui_dump.xml")
    time.sleep(0.3)
    # Use // prefix to prevent MSYS from mangling the path
    return "//sdcard/ui_dump.xml"


def pull_xml(device_path):
    """Pull the XML from device into a local temp file and return the local path."""
    local_path = _local_path()
    adb("pull", device_path, local_path)
    return local_path


def _clean(val):
    """Strip whitespace and treat the uiautomator placeholder 'null' as empty."""
    v = val.strip()
    return "" if v == "null" else v


def is_interactive(node):
    """Return True if this node carries information a user or AI would care about."""
    clickable = node.get("clickable") == "true"
    focusable = node.get("focusable") == "true"
    scrollable = node.get("scrollable") == "true"
    has_text = bool(_clean(node.get("text", "")))
    has_desc = bool(_clean(node.get("content-desc", "")))

    # Keep anything interactive or carrying visible text
    if clickable or focusable or scrollable or has_text or has_desc:
        return True
    return False


def should_skip(node):
    """Skip pure layout containers that carry no information."""
    cls = _clean(node.get("class", ""))
    if cls in CONTAINER_CLASSES:
        if not is_interactive(node):
            return True
    return False


def node_to_dict(node):
    """Convert an XML element to a flat dict with the fields we care about."""
    bounds = node.get("bounds", "")
    return {
        "class": _clean(node.get("class", "")),
        "text": _clean(node.get("text", "")),
        "content_desc": _clean(node.get("content-desc", "")),
        "resource_id": node.get("resource-id", ""),
        "bounds": bounds,
        "clickable": node.get("clickable") == "true",
        "focusable": node.get("focusable") == "true",
        "scrollable": node.get("scrollable") == "true",
        "enabled": node.get("enabled") == "true",
    }


def filter_nodes(root):
    """Walk the XML tree and return a flat list of informative nodes."""
    result = []
    for elem in root.iter():
        if elem.tag == "hierarchy":
            continue
        if should_skip(elem):
            continue
        if is_interactive(elem):
            result.append(node_to_dict(elem))
    return result


def get_ui_state():
    """Main entry: dump, pull, parse, filter. Returns list of node dicts."""
    local = _local_path()
    Path(local).unlink(missing_ok=True)

    device_path = dump_ui_tree()
    local_path = pull_xml(device_path)

    tree = ET.parse(local_path)
    root = tree.getroot()

    nodes = filter_nodes(root)

    Path(local_path).unlink(missing_ok=True)

    return nodes


if __name__ == "__main__":
    try:
        nodes = get_ui_state()
        out_path = Path(__file__).parent.parent / "ui_state.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(nodes, f, ensure_ascii=False, indent=2)
        print(f"Wrote {len(nodes)} nodes to {out_path}")
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
