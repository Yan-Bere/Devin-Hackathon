"""Theme, CSS and HTML renderers for the Cold Plate Copilot UI."""

import html

import gradio as gr

import schema

APP_TITLE = "Cold Plate Copilot"
TAGLINE = "From competition specs to an optimized, manufacturable cold plate."

BG = "#0B1220"
PANEL = "#111A2E"
INSET = "#0E1628"
BORDER = "#1E2A44"
TEXT = "#E6EDF7"
MUTED = "#8FA3BF"
CYAN = "#22D3EE"
ORANGE = "#F97316"
RED = "#EF4444"
GREEN = "#22C55E"
AMBER = "#F59E0B"
BLUE = "#3B82F6"


def _theme():
    theme = gr.themes.Base(
        primary_hue="cyan",
        secondary_hue="orange",
        neutral_hue="slate",
        text_size=gr.themes.sizes.text_lg,
        radius_size=gr.themes.sizes.radius_lg,
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
    )
    colors = {
        "body_background_fill": BG,
        "body_text_color": TEXT,
        "body_text_color_subdued": MUTED,
        "background_fill_primary": PANEL,
        "background_fill_secondary": INSET,
        "block_background_fill": PANEL,
        "block_border_color": BORDER,
        "block_label_background_fill": PANEL,
        "block_label_text_color": MUTED,
        "block_label_border_color": BORDER,
        "block_title_text_color": TEXT,
        "block_info_text_color": MUTED,
        "block_shadow": "0 8px 24px rgba(0, 0, 0, 0.35)",
        "border_color_primary": BORDER,
        "border_color_accent": CYAN,
        "border_color_accent_subdued": BORDER,
        "color_accent": CYAN,
        "color_accent_soft": "rgba(34, 211, 238, 0.14)",
        "input_background_fill": INSET,
        "input_background_fill_focus": INSET,
        "input_border_color": BORDER,
        "input_border_color_focus": CYAN,
        "input_placeholder_color": MUTED,
        "link_text_color": CYAN,
        "link_text_color_hover": "#67E8F9",
        "link_text_color_visited": CYAN,
        "link_text_color_active": CYAN,
        "button_primary_background_fill": CYAN,
        "button_primary_background_fill_hover": "#67E8F9",
        "button_primary_text_color": BG,
        "button_primary_text_color_hover": BG,
        "button_primary_border_color": CYAN,
        "button_secondary_background_fill": "transparent",
        "button_secondary_background_fill_hover": "rgba(34, 211, 238, 0.08)",
        "button_secondary_text_color": TEXT,
        "button_secondary_text_color_hover": TEXT,
        "button_secondary_border_color": "#2C3D60",
        "button_secondary_border_color_hover": CYAN,
        "button_cancel_background_fill": RED,
        "table_even_background_fill": PANEL,
        "table_odd_background_fill": INSET,
        "table_border_color": BORDER,
        "table_row_focus": "rgba(34, 211, 238, 0.10)",
        "panel_background_fill": PANEL,
        "panel_border_color": BORDER,
        "code_background_fill": INSET,
        "shadow_drop": "0 4px 16px rgba(0, 0, 0, 0.35)",
        "shadow_drop_lg": "0 8px 24px rgba(0, 0, 0, 0.35)",
        "error_text_color": RED,
        "error_border_color": RED,
    }
    settings = {}
    for key, value in colors.items():
        for name in (key, f"{key}_dark"):
            if hasattr(theme, name):
                settings[name] = value
    for key, value in {
        "block_border_width": "1px",
        "block_radius": "12px",
        "button_border_width": "1px",
        "button_large_radius": "10px",
        "button_small_radius": "8px",
        "button_large_text_weight": "600",
    }.items():
        if hasattr(theme, key):
            settings[key] = value
    return theme.set(**settings)


THEME = _theme()

CSS = """
html, body, gradio-app, .gradio-container, .main, .wrap.app {
  background-color: #0B1220 !important;
}
body {
  background-image:
    radial-gradient(circle at 0% 0%, rgba(34, 211, 238, 0.08), transparent 42%),
    radial-gradient(circle at 100% 100%, rgba(249, 115, 22, 0.06), transparent 42%) !important;
  background-attachment: fixed !important;
}
gradio-app, .gradio-container, .main, .wrap.app { background: transparent !important; }
.gradio-container { max-width: 1840px !important; font-size: 16px; color: #E6EDF7; }
footer, .footer, gradio-app footer { display: none !important; }

.cp-mono, .cp-value, .cp-count, .cp-model-pill, .cp-results table td,
.cp-results .table-wrap td { font-family: "JetBrains Mono", ui-monospace, monospace !important; }

.cp-header-row { align-items: flex-end !important; margin-bottom: 4px; }
.cp-header-row > div { background: transparent !important; border: 0 !important; box-shadow: none !important; }
.cp-header h1 {
  font-size: 2.4rem; line-height: 1.15; font-weight: 800; letter-spacing: -0.02em;
  margin: 0; padding-bottom: 8px; display: inline-block; color: #E6EDF7;
  background-image: linear-gradient(90deg, #22D3EE, #F97316);
  background-size: 100% 3px; background-repeat: no-repeat; background-position: 0 100%;
}
.cp-header p { color: #8FA3BF; font-size: 1.1rem; margin: 10px 0 0; }
.cp-model-pill { display: flex !important; justify-content: flex-end; }
.cp-model-pill p {
  margin: 0 !important; padding: 6px 14px; border-radius: 999px; font-size: 0.85rem !important;
  color: #22D3EE !important; background: rgba(34, 211, 238, 0.08); border: 1px solid rgba(34, 211, 238, 0.35);
  white-space: nowrap;
}

.cp-stepper-wrap { background: transparent !important; border: 0 !important; box-shadow: none !important; padding: 0 !important; }
.cp-stepper { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 6px 0 4px; }
.cp-step {
  display: inline-flex; align-items: center; gap: 8px; padding: 7px 16px; border-radius: 999px;
  border: 1px solid #1E2A44; background: #111A2E; color: #8FA3BF; font-weight: 600; opacity: 0.5;
}
.cp-step .cp-step-n { font-family: "JetBrains Mono", monospace; }
.cp-step.cp-done { opacity: 1; color: #22D3EE; border-color: rgba(34, 211, 238, 0.45); }
.cp-step.cp-active {
  opacity: 1; color: #0B1220; background: #22D3EE; border-color: #22D3EE;
  box-shadow: 0 0 18px rgba(34, 211, 238, 0.35);
}
.cp-step-sep { color: #2C3D60; font-weight: 700; }
.cp-badge { margin-left: auto; color: #8FA3BF; font-size: 0.95rem; }
.cp-badge.cp-final { color: #22C55E; font-weight: 700; }

.cp-chat .message-row .message, .cp-chat .message { border-radius: 14px !important; }
.cp-chat .message-row.user-row .message, .cp-chat .user-row .message-content, .cp-chat .message.user {
  background: rgba(34, 211, 238, 0.14) !important; border: 1px solid rgba(34, 211, 238, 0.35) !important; color: #E6EDF7 !important;
}
.cp-chat .message-row.bot-row .message, .cp-chat .bot-row .message-content, .cp-chat .message.bot {
  background: #16213A !important; border: 1px solid #1E2A44 !important; color: #E6EDF7 !important;
}
.cp-chat .prose, .cp-chat .message { font-size: 16px !important; line-height: 1.55; }
.cp-input textarea { font-size: 16px !important; }

.cp-progress { margin: 2px 0 14px; }
.cp-progress-label { display: flex; justify-content: space-between; color: #8FA3BF; margin-bottom: 6px; font-size: 0.95rem; }
.cp-progress-label .cp-mono { color: #E6EDF7; }
.cp-bar { height: 10px; background: #0E1628; border: 1px solid #1E2A44; border-radius: 999px; overflow: hidden; }
.cp-fill { height: 100%; background: linear-gradient(90deg, #0EA5C6, #22D3EE); border-radius: 999px; }

.cp-checklist { max-height: 640px; overflow-y: auto; padding-right: 4px; }
.cp-group {
  background: #0E1628; border: 1px solid #1E2A44; border-radius: 12px; margin-bottom: 12px; overflow: hidden;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
}
.cp-group.cp-current { border-color: rgba(34, 211, 238, 0.7); box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.25), 0 4px 14px rgba(0, 0, 0, 0.25); }
.cp-group-h {
  display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 14px;
  font-weight: 700; color: #E6EDF7; background: #111A2E; border-bottom: 1px solid #1E2A44;
}
.cp-count { color: #8FA3BF; font-weight: 500; font-size: 0.9rem; white-space: nowrap; }
.cp-now {
  font-family: Inter, sans-serif; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em;
  color: #0B1220; background: #22D3EE; border-radius: 999px; padding: 2px 8px; margin-right: 8px;
}
.cp-row {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr) auto; gap: 12px; align-items: center;
  padding: 8px 14px; border-bottom: 1px solid rgba(30, 42, 68, 0.6); font-size: 0.95rem;
}
.cp-row:last-child { border-bottom: 0; }
.cp-label { color: #C9D6E8; overflow-wrap: anywhere; }
.cp-value { color: #E6EDF7; text-align: right; overflow-wrap: anywhere; font-size: 0.88rem; }
.cp-tag {
  display: inline-block; margin-left: 6px; font-size: 0.68rem; letter-spacing: 0.05em; color: #F97316;
  border: 1px solid rgba(249, 115, 22, 0.5); border-radius: 6px; padding: 0 5px; vertical-align: 1px;
}
.cp-status { font-size: 0.8rem; padding: 3px 10px; border-radius: 999px; white-space: nowrap; font-weight: 600; }
.cp-status.cp-ok { color: #4ADE80; background: rgba(34, 197, 94, 0.14); border: 1px solid rgba(34, 197, 94, 0.4); }
.cp-status.cp-proposed { color: #FBBF24; background: rgba(245, 158, 11, 0.14); border: 1px solid rgba(245, 158, 11, 0.4); }
.cp-status.cp-missing, .cp-status.cp-na { color: #A7B4C8; background: rgba(143, 163, 191, 0.12); border: 1px solid rgba(143, 163, 191, 0.35); }

.cp-section { font-weight: 700; font-size: 1.05rem; margin: 18px 0 8px; color: #E6EDF7; }
.cp-check {
  display: flex; gap: 10px; align-items: flex-start; background: #0E1628; border: 1px solid #1E2A44;
  border-left: 4px solid #8FA3BF; border-radius: 8px; padding: 10px 12px; margin: 6px 0; font-size: 0.95rem; color: #E6EDF7;
}
.cp-check b { color: #E6EDF7; margin-right: 4px; }
.cp-check-ok { border-left-color: #22C55E; }
.cp-check-warning { border-left-color: #F59E0B; }
.cp-check-error { border-left-color: #EF4444; }
.cp-check-info { border-left-color: #3B82F6; }
.cp-ack { color: #22C55E; font-weight: 600; margin-left: 6px; white-space: nowrap; }
.cp-empty { color: #8FA3BF; }

.cp-downloads { opacity: 0.92; }
.cp-actions button { font-size: 1rem !important; white-space: nowrap; min-width: 0 !important; }
.cp-optimize { background: #F97316 !important; border-color: #F97316 !important; color: #0B1220 !important; }
.cp-optimize:hover { background: #FB923C !important; }
.cp-optimize:disabled, .cp-optimize[disabled] { background: transparent !important; color: #8FA3BF !important; border-color: #2C3D60 !important; opacity: 0.6; }
.cp-banner p {
  margin: 0 !important; padding: 10px 14px; border-left: 4px solid #F97316; background: rgba(249, 115, 22, 0.08);
  border-radius: 8px; color: #FDBA74 !important;
}
"""

FORCE_DARK_JS = """
() => {
  document.body.classList.add('dark');
  document.documentElement.classList.add('dark');
}
"""

LAUNCH_KWARGS = {
    "theme": THEME,
    "css": CSS,
    "js": FORCE_DARK_JS,
    "footer_links": [],
}

STATUS = {
    "user_provided": ("✓", "confirmed", "ok"),
    "assumption_confirmed": ("✓", "assumption ✓", "ok"),
    "default_proposed": ("●", "proposed", "proposed"),
    "not_applicable": ("–", "n/a", "na"),
    "missing": ("○", "missing", "missing"),
}
CHECK_ICONS = {"ok": "✓", "info": "i", "warning": "!", "error": "✕"}
STEPS = (("specs", "Specs"), ("validate", "Validate"), ("optimize", "Optimize"), ("cad", "CAD"))


def header_html():
    return (
        f'<div class="cp-header"><h1>{APP_TITLE}</h1>'
        f"<p>{html.escape(TAGLINE)}</p></div>"
    )


def stepper_html(stage, badge):
    keys = [key for key, _ in STEPS]
    current = keys.index(stage)
    parts = []
    for index, (key, label) in enumerate(STEPS):
        if index < current:
            css = "cp-step cp-done"
        elif index == current:
            css = "cp-step cp-active"
        else:
            css = "cp-step"
        if index:
            parts.append('<span class="cp-step-sep">→</span>')
        parts.append(
            f'<span class="{css}"><span class="cp-step-n">{"①②③④"[index]}</span>{label}</span>'
        )
    final = " cp-final" if "Finalized" in badge else ""
    parts.append(f'<span class="cp-badge{final}">{html.escape(badge)}</span>')
    return f'<div class="cp-stepper">{"".join(parts)}</div>'


def checklist_html(session, presented_group=None, done_statuses=()):
    escape = html.escape
    done, total = session.progress()
    percent = 100 * done / total if total else 0
    parts = [
        '<div class="cp-checklist"><div class="cp-progress"><div class="cp-progress-label">'
        f'<span>Requirements</span><span class="cp-mono">{done} / {total} confirmed</span></div>'
        f'<div class="cp-bar"><div class="cp-fill" style="width:{percent:.1f}%"></div></div></div>'
    ]
    for group_number, group_name in schema.GROUPS.items():
        group_fields = [item for item in schema.FIELDS if item.group == group_number]
        required = [item for item in group_fields if session.is_required(item.id)]
        group_done = sum(session.fields[item.id].status in done_statuses for item in required)
        rows = []
        for item in group_fields:
            field_state = session.fields[item.id]
            if field_state.status == "missing" and not session.is_required(item.id):
                continue
            icon, status, css = STATUS.get(field_state.status, STATUS["missing"])
            tag = '<span class="cp-tag">ASSUMPTION</span>' if item.is_assumption else ""
            value = session._display_value(item, field_state)
            rows.append(
                f'<div class="cp-row"><div class="cp-label">{escape(item.label)}{tag}</div>'
                f'<div class="cp-value">{escape(str(value))}</div>'
                f'<div class="cp-status cp-{css}">{icon} {status}</div></div>'
            )
        current = group_number == presented_group
        now = '<span class="cp-now">current</span>' if current else ""
        parts.append(
            f'<div class="cp-group{" cp-current" if current else ""}"><div class="cp-group-h">'
            f"<span>Group {group_number} — {escape(group_name)}</span>"
            f'<span class="cp-count">{now}{group_done}/{len(required)}</span></div>'
            f'{"".join(rows)}</div>'
        )
    parts.append('<div class="cp-section">Checks</div>')
    results = sorted(session.checks(), key=lambda result: result.id)
    if results:
        for result in results:
            acknowledged = (
                '<span class="cp-ack">— acknowledged</span>'
                if result.level == "warning" and result.acknowledged
                else ""
            )
            parts.append(
                f'<div class="cp-check cp-check-{result.level}" data-check="{result.id}">'
                f"<span class=\"cp-icon\">{CHECK_ICONS[result.level]}</span><div><b class=\"cp-mono\">{result.id}</b>"
                f"{escape(result.message)}{acknowledged}</div></div>"
            )
    else:
        parts.append('<div class="cp-empty">Checks: not enough data yet</div>')
    parts.append("</div>")
    return "".join(parts)

CSS += """
.cp-status, .cp-check > span:first-child, .cp-badge {
  font-family: Inter, "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif !important;
}
"""
LAUNCH_KWARGS["css"] = CSS

CSS += """
.cp-icon {
  flex: 0 0 22px; height: 22px; border-radius: 999px; display: inline-flex; align-items: center;
  justify-content: center; font-weight: 800; font-size: 0.8rem; color: #0B1220; margin-top: 1px;
}
.cp-check-ok .cp-icon { background: #22C55E; }
.cp-check-warning .cp-icon { background: #F59E0B; }
.cp-check-error .cp-icon { background: #EF4444; }
.cp-check-info .cp-icon { background: #3B82F6; color: #E6EDF7; }
"""
LAUNCH_KWARGS["css"] = CSS
