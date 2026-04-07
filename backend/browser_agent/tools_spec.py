# OpenAI Chat Completions tool definitions.

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_observation",
            "description": "Refresh the structured view of the current page (URL, title, interactive elements with [ref=N] markers). Call after navigation or when the DOM may have changed.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Open a URL in the current tab.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full https URL"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "go_back",
            "description": "Browser back navigation.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click an element that appeared in the last observation with [ref=N].",
            "parameters": {
                "type": "object",
                "properties": {"ref": {"type": "string", "description": "Numeric ref from observation"}},
                "required": ["ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill",
            "description": "Fill an input or textarea identified by ref.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["ref", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": "Press a key or named key (e.g. Enter, Tab).",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the main viewport.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "left", "right"],
                    },
                    "pixels": {"type": "integer", "description": "Pixels to scroll (default 400)"},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_ms",
            "description": "Wait for UI or network; capped at 120s.",
            "parameters": {
                "type": "object",
                "properties": {"ms": {"type": "integer"}},
                "required": ["ms"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_option",
            "description": "Select an option in a select element. Provide value or label (or both).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "value": {"type": "string", "description": "Option value attribute"},
                    "label": {"type": "string", "description": "Visible label"},
                },
                "required": ["ref"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot_viewport_jpeg",
            "description": "Save a viewport JPEG under log/screenshots for debugging or archival.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_page_pdf",
            "description": "Export the current page to PDF (print layout) under log/pdf.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Finish the task when the user goal is satisfied.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string", "description": "Short outcome summary"}},
                "required": ["summary"],
            },
        },
    },
]
