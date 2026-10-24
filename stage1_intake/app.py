"""Gradio UI for requirements intake."""

import argparse
import base64
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

import gradio as gr
import pandas as pd

import agent as intake_agent
import llm
import schema
import state as intake_state
import plots
import ui_style


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SESSIONS_DIR = BASE_DIR / "sessions"
THINKING = "…thinking"
DOWNLOAD_NAMES = ("notes.txt", "requirements.json", "requirements_final.json")
PARETO_COLUMNS = ["T_hbm_max_C", "delta_p_nominal_kPa", "kind"]
# Server-side API base (POST target) vs the URL the browser opens.
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://127.0.0.1:8000")
DASHBOARD_BROWSER_URL = os.getenv("DASHBOARD_BROWSER_URL", DASHBOARD_URL)
UPLOAD_TYPES = [".md", ".pptx", ".ppt", ".txt", ".csv"]
READY_MSG = ("Requirements finalized — I'm ready for stage 3 modelling. "
             "Click **Open modelling dashboard** to run it.")


def render_checklist(session, presented_group=None):
    return ui_style.checklist_html(session, presented_group, intake_state.DONE)


def _stage(agent_state):
    if agent_state is None:
        return "specs"
    session = agent_state.session
    if session.finalized:
        return "optimize"
    done, total = session.progress()
    return "validate" if done >= total else "specs"


def download_paths(session):
    return [
        str(path)
        for name in DOWNLOAD_NAMES
        if (path := session.dir / name).is_file()
    ]


def _provider_name(provider):
    if isinstance(provider, llm.MockProvider):
        return "mock"
    if isinstance(provider, llm.GeminiProvider):
        return "gemini"
    return type(provider).__name__.removesuffix("Provider").lower()


def _configured_provider_name(provider_name):
    configured = provider_name or os.getenv("LLM_PROVIDER")
    if configured:
        return configured
    return "gemini" if os.getenv("GEMINI_API_KEY") else "mock"


def _footer(agent_state, provider_name=None):
    if agent_state is not None:
        provider = agent_state.provider
        name = _provider_name(provider)
        model = getattr(provider, "model", None)
        return f"LLM: {name}/{model}" if model else f"LLM: {name}"
    name = _configured_provider_name(provider_name)
    if name == "mock":
        return "LLM: mock"
    if name == "gemini":
        return f"LLM: gemini/{os.getenv('LLM_MODEL', 'gemini-3.8-flash')}"
    return f"LLM: {name}"


def _panel(agent_state, provider_name=None):
    if agent_state is None:
        return (
            _empty_progress(),
            "Load the preset or send a message to begin.",
            [],
            _footer(None, provider_name),
        )
    session = agent_state.session
    done, total = session.progress()
    badge = "Finalized ✅" if session.finalized else "In progress"
    return (
        ui_style.stepper_html(_stage(agent_state), badge),
        render_checklist(session, agent_state.presented_group),
        download_paths(session),
        _footer(agent_state, provider_name),
    )


def _empty_progress():
    return ui_style.stepper_html("specs", "In progress")


def _chat(chat):
    if chat is None:
        return [{"role": "assistant", "content": intake_agent.OPENING_LINE}]
    return list(chat)


def _outputs(agent_state, chat, busy, provider_name, textbox_value=""):
    progress, checklist, files, footer = _panel(agent_state, provider_name)
    interactive = not busy
    optimize_interactive = bool(
        interactive
        and agent_state is not None
        and agent_state.session.finalized
    )
    return (
        agent_state,
        chat,
        progress,
        checklist,
        files,
        footer,
        gr.update(value=textbox_value, interactive=interactive),
        gr.update(interactive=interactive),
        gr.update(interactive=interactive),
        gr.update(interactive=interactive),
        gr.update(interactive=optimize_interactive),
        gr.update(interactive=optimize_interactive),
    )


def start_modelling(agent_state, opener=None):
    """POST the finalized requirements to the dashboard's modelling endpoint."""
    if agent_state is None or not agent_state.session.finalized:
        return "Finalize requirements first."
    final_path = agent_state.session.dir / "requirements_final.json"
    try:
        payload = {"requirements_final": json.loads(
            final_path.read_text(encoding="utf-8"))}
    except (OSError, json.JSONDecodeError) as exc:
        return f"Cannot read finalized requirements: {exc}"
    uploads = getattr(agent_state, "uploads", None) or {}
    if uploads.get("markdown"):
        payload["requirements_markdown"] = "\n\n".join(
            f"## {name}\n\n{text}" for name, text in uploads["markdown"])
    if uploads.get("reference_files"):
        payload["reference_files"] = [
            {"name": path.name,
             "content_base64": base64.b64encode(path.read_bytes()).decode("ascii")}
            for path in uploads["reference_files"]]
    url = f"{DASHBOARD_URL}/api/modelling/start"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    open_url = opener or urllib.request.urlopen
    try:
        open_url(request, timeout=5)
    except Exception:
        return (f"Dashboard not reachable at {url} — start it with "
                f"`python run_demo_stack.py`")
    return f"Modelling started — opening the dashboard at {DASHBOARD_BROWSER_URL}"


def extract_pptx(path, media_dir):
    """Return (slide text, slide count) and save embedded images to media_dir."""
    def slide_no(name):
        return int(re.search(r"(\d+)\.xml$", name).group(1))

    with zipfile.ZipFile(path) as z:
        slides = sorted(
            (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=slide_no)
        parts = []
        for name in slides:
            xml = z.read(name).decode("utf-8", errors="replace")
            paragraphs = []
            for para in re.findall(r"<a:p\b.*?</a:p>", xml, flags=re.S):
                text = "".join(re.findall(r"<a:t>(.*?)</a:t>", para, flags=re.S))
                if text.strip():
                    paragraphs.append(_xml_unescape(text))
            parts.append(f"### Slide {slide_no(name)}\n" + "\n".join(paragraphs))
        media = [n for n in z.namelist() if n.startswith("ppt/media/")]
        if media:
            Path(media_dir).mkdir(parents=True, exist_ok=True)
            for name in media:
                (Path(media_dir) / Path(name).name).write_bytes(z.read(name))
    return "\n\n".join(parts), len(slides)


def _xml_unescape(text):
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                         ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(entity, char)
    return text


def _append_ready_message(active_agent, final_chat):
    """Append the stage-3 ready message exactly once after finalization."""
    if (
        active_agent is not None
        and active_agent.session.finalized
        and not getattr(active_agent, "_dashboard_ready_announced", False)
    ):
        final_chat = final_chat + [{"role": "assistant", "content": READY_MSG}]
        active_agent._dashboard_ready_announced = True
    return final_chat


def _on_start(chat, start_method, provider_name, sessions_dir):
    current_chat = _chat(chat)
    waiting_chat = current_chat + [{"role": "assistant", "content": THINKING}]
    yield _outputs(None, waiting_chat, True, provider_name)
    active_agent = None
    try:
        session_dir = sessions_dir if sessions_dir is not None else SESSIONS_DIR
        session = intake_state.Session(base_dir=session_dir)
        provider = llm.get_provider(
            provider_name if provider_name is not None else os.getenv("LLM_PROVIDER")
        )
        active_agent = intake_agent.Agent(session, provider)
        reply = getattr(active_agent, start_method)()
    except Exception as exc:
        reply = f"Something went wrong: {exc}"
    final_chat = current_chat + [{"role": "assistant", "content": reply}]
    final_chat = _append_ready_message(active_agent, final_chat)
    yield _outputs(active_agent, final_chat, False, provider_name)


def on_preset(agent_state, chat, provider_name=None, sessions_dir=None):
    yield from _on_start(chat, "start_preset", provider_name, sessions_dir)


def on_blank(agent_state, chat, provider_name=None, sessions_dir=None):
    yield from _on_start(chat, "start_blank", provider_name, sessions_dir)


def on_send(text, agent_state, chat, provider_name=None, sessions_dir=None):
    current_chat = _chat(chat)
    if not isinstance(text, str) or not text.strip():
        yield _outputs(agent_state, current_chat, False, provider_name)
        return
    waiting_chat = current_chat + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": THINKING},
    ]
    yield _outputs(agent_state, waiting_chat, True, provider_name, text)
    active_agent = agent_state
    try:
        if active_agent is None:
            session_dir = sessions_dir if sessions_dir is not None else SESSIONS_DIR
            session = intake_state.Session(base_dir=session_dir)
            provider = llm.get_provider(
                provider_name if provider_name is not None else os.getenv("LLM_PROVIDER")
            )
            active_agent = intake_agent.Agent(session, provider)
            active_agent.start_blank()
        reply = active_agent.handle(text)
    except Exception as exc:
        reply = f"Something went wrong: {exc}"
    final_chat = current_chat + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply},
    ]
    final_chat = _append_ready_message(active_agent, final_chat)
    yield _outputs(active_agent, final_chat, False, provider_name)


def on_upload(files, agent_state, chat, provider_name=None, sessions_dir=None):
    current_chat = _chat(chat)
    yield _outputs(agent_state, current_chat, True, provider_name)
    active_agent = agent_state
    try:
        if active_agent is None:
            session_dir = sessions_dir if sessions_dir is not None else SESSIONS_DIR
            session = intake_state.Session(base_dir=session_dir)
            provider = llm.get_provider(
                provider_name if provider_name is not None else os.getenv("LLM_PROVIDER")
            )
            active_agent = intake_agent.Agent(session, provider)
            active_agent.start_blank()
        uploads = getattr(active_agent, "uploads", None)
        if uploads is None:
            uploads = active_agent.uploads = {"markdown": [], "reference_files": []}
        upload_dir = active_agent.session.dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        for item in files or []:
            src = Path(item if isinstance(item, (str, Path)) else item.name)
            name, ext = src.name, src.suffix.lower()
            if ext == ".ppt":
                current_chat.append({"role": "assistant", "content":
                                     f"{name}: Please save as .pptx"})
                continue
            if ext not in UPLOAD_TYPES:
                current_chat.append({"role": "assistant", "content":
                                     f"{name}: unsupported file type"})
                continue
            dest = upload_dir / name
            shutil.copyfile(src, dest)
            if ext == ".csv":
                uploads["reference_files"].append(dest)
                current_chat.append({"role": "user", "content":
                                     f"Uploaded {name} (reference file)"})
                continue
            if ext == ".pptx":
                text, n_slides = extract_pptx(dest, upload_dir / f"{dest.stem}_media")
                label = f"Uploaded {name} ({n_slides} slides)"
            else:
                text = dest.read_text(encoding="utf-8", errors="replace")
                label = f"Uploaded {name}"
            uploads["markdown"].append((name, text))
            current_chat.append({"role": "user", "content": label})
            current_chat.append({"role": "assistant",
                                 "content": active_agent.handle(text)})
    except Exception as exc:
        current_chat.append({"role": "assistant",
                             "content": f"Something went wrong: {exc}"})
    current_chat = _append_ready_message(active_agent, current_chat)
    yield _outputs(active_agent, current_chat, False, provider_name)


def _run_optimizer(requirements_path):
    from stage2_optimizer.run import run

    return run(requirements_path)


def _format_design_status(record):
    if record["feasible"]:
        return "PASS"
    return "FAIL: " + "; ".join(
        f'{item["name"]} {item["actual"]:.2f} > '
        f'{item["limit"]:.2f} {item["unit"]}'
        for item in record["failing_constraints"]
    )


def _optimizer_summary(result):
    lines = [
        "| Design | Fin thickness (mm) | Gap (mm) | Fin count | "
        "Max GPU (°C) | Max HBM (°C) | ΔP nominal (kPa / psi) | "
        "Pumping power (W) | FoM | Limits |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for label in ("baseline", "optimized"):
        record = result[label]
        nominal = record["nominal"]
        lines.append(
            f'| {label.title()} | {record["fin_thickness_mm"]:.3f} | '
            f'{record["gap_mm"]:.3f} | {record["fin_count"]} | '
            f'{record["T_gpu_max_C"]:.2f} | {record["T_hbm_max_C"]:.2f} | '
            f'{nominal["delta_p_kPa"]:.2f} / {nominal["delta_p_psi"]:.2f} | '
            f'{nominal["pumping_power_W"]:.3f} | {record["fom"]:.5f} | '
            f'{_format_design_status(record)} |'
        )
    if not result["feasible"]:
        lines.extend(
            [
                "",
                "**No feasible design found; returning the best-FoM design.**",
                "",
                "**Failing constraints:**",
            ]
        )
        lines.extend(
            f'- {item["name"]}: {item["actual"]:.2f} {item["unit"]} '
            f'(limit {item["limit"]:.2f} {item["unit"]})'
            for item in result["failing_constraints"]
        )
    return "\n".join(lines)


def _sweep_rows(result):
    return [
        {
            "Flow (L/min)": point["flow_L_min"],
            "Inlet (°C)": point["inlet_temp_C"],
            "ΔP (kPa)": round(point["delta_p_kPa"], 2),
            "ΔP (psi)": round(point["delta_p_psi"], 3),
            "GPU max (°C)": round(point["max_gpu_C"], 2),
            "HBM max (°C)": round(point["max_hbm_C"], 2),
            "Coolant rise (K)": round(point["coolant_outlet_rise_K"], 2),
        }
        for point in result["sweep"]
    ]


def _pareto_frame(result):
    rows = []
    for record in result["evaluations"]:
        rows.append(
            {
                "T_hbm_max_C": record["T_hbm_max_C"],
                "delta_p_nominal_kPa": record["delta_p_nominal_kPa"],
                "kind": (
                    "candidate (feasible)"
                    if record["feasible"]
                    else "candidate (infeasible)"
                ),
            }
        )
    for name, kind in (("baseline", "baseline"), ("optimized", "optimum")):
        record = result[name]
        rows.append(
            {
                "T_hbm_max_C": record["T_hbm_max_C"],
                "delta_p_nominal_kPa": record["delta_p_nominal_kPa"],
                "kind": kind,
            }
        )
    return pd.DataFrame(rows, columns=PARETO_COLUMNS)


def _render(fn, source, path):
    try:
        return fn(source, path)
    except Exception:
        return None


def on_optimize(agent_state, runner=None):
    finalized = bool(
        agent_state is not None and agent_state.session.finalized
    )
    empty_pareto = None
    if not finalized:
        yield (
            "Optimize is available after requirements are finalized.",
            "",
            [],
            empty_pareto,
            None,
            [],
            gr.update(interactive=False),
        )
        return

    yield (
        "Optimizing… (reduced-order model)",
        "",
        [],
        empty_pareto,
        None,
        [],
        gr.update(interactive=False),
    )
    try:
        run_optimizer = runner or _run_optimizer
        out_dir = agent_state.session.dir
        result = run_optimizer(
            agent_state.session.dir / "requirements_final.json"
        )
        files = [
            path
            for path in (
                result["files"].get("step_path"),
                result["files"].get("stl_path"),
            )
            if path
        ]
        status = (
            f"Optimization complete in {result['run_elapsed_seconds']:.2f} s."
            if result["feasible"]
            else (
                f"No feasible design; best-FoM result returned in "
                f"{result['run_elapsed_seconds']:.2f} s."
            )
        )
        yield (
            status,
            _optimizer_summary(result),
            pd.DataFrame(_sweep_rows(result)),
            _render(plots.pareto_png, result, out_dir / "pareto.png"),
            _render(plots.plate_png, result["files"].get("stl_path"), out_dir / "plate.png"),
            files,
            gr.update(interactive=True),
        )
    except Exception as exc:
        yield (
            f"Optimization failed: {type(exc).__name__}: {exc}",
            "",
            [],
            empty_pareto,
            None,
            [],
            gr.update(interactive=True),
        )


def build_app(provider_name=None):
    with gr.Blocks(title=ui_style.APP_TITLE) as demo:
        with gr.Row(elem_classes="cp-header-row"):
            gr.HTML(ui_style.header_html(), scale=4)
            footer = gr.Markdown(
                _footer(None, provider_name),
                elem_classes="cp-model-pill",
            )
        progress = gr.HTML(_empty_progress(), elem_classes="cp-stepper-wrap")
        agent_state = gr.State(None)
        with gr.Row(equal_height=False):
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    value=[{"role": "assistant", "content": intake_agent.OPENING_LINE}],
                    label="Chat",
                    show_label=False,
                    height=620,
                    elem_classes="cp-chat",
                )
                textbox = gr.Textbox(
                    placeholder="Describe your package or answer the bot…",
                    show_label=False,
                    submit_btn=False,
                    elem_classes="cp-input",
                )
                with gr.Row():
                    send_button = gr.Button("Send", variant="primary")
                    upload_button = gr.UploadButton(
                        "Upload files",
                        file_types=UPLOAD_TYPES,
                        file_count="multiple",
                    )
                with gr.Row(elem_classes="cp-actions"):
                    preset_button = gr.Button("Load ITherm 2027 preset", variant="primary")
                    blank_button = gr.Button("Start blank", variant="secondary")
                    optimize_button = gr.Button(
                        "Optimize",
                        variant="primary",
                        interactive=False,
                        elem_classes="cp-optimize",
                    )
                    dashboard_button = gr.Button(
                        "Open modelling dashboard",
                        variant="secondary",
                        interactive=False,
                        elem_classes="cp-dashboard",
                    )
                downloads = gr.File(
                    label="Downloads",
                    file_count="multiple",
                    interactive=False,
                    elem_classes="cp-downloads",
                )
            with gr.Column(scale=2):
                checklist = gr.HTML("Load the preset or send a message to begin.")
        with gr.Column(elem_classes="cp-results"):
            gr.Markdown(
                "**Reduced-order model (not CFD). Use for design screening only.**",
                elem_classes="cp-banner",
            )
            optimizer_status = gr.Markdown("Finalize requirements to optimize.")
            optimizer_summary = gr.Markdown()
            with gr.Row(equal_height=False):
                with gr.Column(scale=3):
                    sweep_results = gr.Dataframe(
                        headers=[
                            "Flow (L/min)",
                            "Inlet (°C)",
                            "ΔP (kPa)",
                            "ΔP (psi)",
                            "GPU max (°C)",
                            "HBM max (°C)",
                            "Coolant rise (K)",
                        ],
                        interactive=False,
                        label="Operating-point sweep",
                    )
                    pareto_plot = gr.Image(
                        label="Pareto candidates",
                        type="filepath",
                        interactive=False,
                        show_label=False,
                    )
                with gr.Column(scale=2):
                    optimized_model = gr.Image(
                        label="Optimized cold plate (STL render)",
                        type="filepath",
                        interactive=False,
                        show_label=False,
                    )
                    optimizer_files = gr.File(
                        label="Optimized STEP/STL",
                        file_count="multiple",
                        interactive=False,
                        elem_classes="cp-downloads",
                    )

        outputs = [
            agent_state,
            chatbot,
            progress,
            checklist,
            downloads,
            footer,
            textbox,
            send_button,
            preset_button,
            blank_button,
            optimize_button,
            dashboard_button,
        ]
        optimizer_outputs = [
            optimizer_status,
            optimizer_summary,
            sweep_results,
            pareto_plot,
            optimized_model,
            optimizer_files,
            optimize_button,
        ]

        def send_handler(text, current_agent, current_chat):
            yield from on_send(
                text,
                current_agent,
                current_chat,
                provider_name,
                SESSIONS_DIR,
            )

        def preset_handler(current_agent, current_chat):
            yield from on_preset(
                current_agent,
                current_chat,
                provider_name,
                SESSIONS_DIR,
            )

        def blank_handler(current_agent, current_chat):
            yield from on_blank(
                current_agent,
                current_chat,
                provider_name,
                SESSIONS_DIR,
            )

        def upload_handler(files, current_agent, current_chat):
            yield from on_upload(
                files,
                current_agent,
                current_chat,
                provider_name,
                SESSIONS_DIR,
            )

        upload_button.upload(
            upload_handler,
            inputs=[upload_button, agent_state, chatbot],
            outputs=outputs,
        )

        def optimize_handler(current_agent):
            yield from on_optimize(current_agent)

        textbox.submit(
            send_handler,
            inputs=[textbox, agent_state, chatbot],
            outputs=outputs,
        )
        send_button.click(
            send_handler,
            inputs=[textbox, agent_state, chatbot],
            outputs=outputs,
        )
        preset_button.click(
            preset_handler,
            inputs=[agent_state, chatbot],
            outputs=outputs,
        )
        blank_button.click(
            blank_handler,
            inputs=[agent_state, chatbot],
            outputs=outputs,
        )
        optimize_button.click(
            optimize_handler,
            inputs=[agent_state],
            outputs=optimizer_outputs,
        )
        dashboard_button.click(
            fn=start_modelling,
            inputs=[agent_state],
            outputs=[optimizer_status],
            js=f"() => {{ window.open('{DASHBOARD_BROWSER_URL}', '_blank'); }}",
        )
    return demo


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("mock", "gemini"))
    args = parser.parse_args(argv)
    build_app(args.provider).queue().launch(
        **ui_style.LAUNCH_KWARGS,
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("PORT", "7860")),
    )


if __name__ == "__main__":
    main()
