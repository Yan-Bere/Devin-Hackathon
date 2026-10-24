"""Gradio UI for requirements intake."""

import argparse
import os
import sys
from pathlib import Path

import gradio as gr
import pandas as pd

import agent as intake_agent
import llm
import schema
import state as intake_state


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SESSIONS_DIR = BASE_DIR / "sessions"
THINKING = "…thinking"
DOWNLOAD_NAMES = ("notes.txt", "requirements.json", "requirements_final.json")
PARETO_COLUMNS = ["T_hbm_max_C", "delta_p_nominal_kPa", "kind"]


def render_checklist(session, presented_group=None):
    lines = []
    for group_number, group_name in schema.GROUPS.items():
        group_fields = [item for item in schema.FIELDS if item.group == group_number]
        required_fields = [item for item in group_fields if session.is_required(item.id)]
        done = sum(
            session.fields[item.id].status in intake_state.DONE
            for item in required_fields
        )
        current = " ← current" if group_number == presented_group else ""
        lines.append(
            f"### Group {group_number} — {group_name} "
            f"({done}/{len(required_fields)}){current}"
        )
        for item in group_fields:
            field_state = session.fields[item.id]
            if field_state.status == "missing" and not session.is_required(item.id):
                continue
            if field_state.status == "user_provided":
                icon, status = "✅", "user provided"
                assumption = ""
            elif field_state.status == "assumption_confirmed":
                icon, status = "☑️", "assumption confirmed"
                assumption = " (ASSUMPTION)"
            elif field_state.status == "default_proposed":
                icon, status = "🟡", "proposed"
                assumption = " (ASSUMPTION)" if item.is_assumption else ""
            elif field_state.status == "not_applicable":
                icon, status = "➖", "not applicable"
                assumption = ""
            else:
                icon, status = "⬜", "missing"
                assumption = " (ASSUMPTION)" if item.is_assumption else ""
            display = session._display_value(item, field_state)
            lines.append(
                f"- {icon} {item.label}: {display}{assumption} — {status}"
            )

    lines.append("### Checks")
    results = sorted(session.checks(), key=lambda result: result.id)
    if results:
        icons = {
            "ok": "✅",
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
        }
        for result in results:
            acknowledged = (
                " — acknowledged"
                if result.level == "warning" and result.acknowledged
                else ""
            )
            lines.append(
                f"- {icons[result.level]} {result.id}: "
                f"{result.message}{acknowledged}"
            )
    else:
        lines.append("Checks: not enough data yet")
    return "\n".join(lines)


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
        f"**{done}/{total} required fields complete** · {badge}",
        render_checklist(session, agent_state.presented_group),
        download_paths(session),
        _footer(agent_state, provider_name),
    )


def _empty_progress():
    total = sum(schema.is_required(item, {}) for item in schema.FIELDS)
    return f"**0/{total} required fields complete** · In progress"


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
    )


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
    yield _outputs(active_agent, final_chat, False, provider_name)


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
            "ΔP (kPa)": point["delta_p_kPa"],
            "ΔP (psi)": point["delta_p_psi"],
            "GPU max (°C)": point["max_gpu_C"],
            "HBM max (°C)": point["max_hbm_C"],
            "Coolant rise (K)": point["coolant_outlet_rise_K"],
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


def on_optimize(agent_state, runner=None):
    finalized = bool(
        agent_state is not None and agent_state.session.finalized
    )
    empty_pareto = pd.DataFrame(columns=PARETO_COLUMNS)
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
            _pareto_frame(result),
            result["files"].get("stl_path"),
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
    with gr.Blocks(title="Cold Plate Requirements Intake — ITherm 2027") as demo:
        gr.Markdown(
            "## Cold Plate Requirements Intake — ITherm 2027\n\n"
            "Collects and validates the simulation inputs and writes "
            "`requirements_final.json` for the optimizer stage."
        )
        agent_state = gr.State(None)
        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    value=[{"role": "assistant", "content": intake_agent.OPENING_LINE}],
                    label="Chat",
                    show_label=False,
                    height=600,
                )
                textbox = gr.Textbox(
                    placeholder="Describe your package or answer the bot…",
                    show_label=False,
                    submit_btn=False,
                )
                send_button = gr.Button("Send", variant="primary")
                with gr.Row():
                    preset_button = gr.Button("Load ITherm 2027 preset")
                    blank_button = gr.Button("Start blank")
                    optimize_button = gr.Button(
                        "Optimize",
                        variant="primary",
                        interactive=False,
                    )
            with gr.Column(scale=2):
                progress = gr.Markdown(_empty_progress())
                checklist = gr.Markdown("Load the preset or send a message to begin.")
                downloads = gr.File(
                    label="Downloads",
                    file_count="multiple",
                    interactive=False,
                )
                footer = gr.Markdown(_footer(None, provider_name))
                gr.Markdown(
                    "**Reduced-order model (not CFD). Use for design screening only.**"
                )
                optimizer_status = gr.Markdown("Finalize requirements to optimize.")
                optimizer_summary = gr.Markdown()
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
                pareto_plot = gr.ScatterPlot(
                    value=pd.DataFrame(columns=PARETO_COLUMNS),
                    x="delta_p_nominal_kPa",
                    y="T_hbm_max_C",
                    color="kind",
                    color_map={
                        "candidate (feasible)": "#398439",
                        "candidate (infeasible)": "#999999",
                        "baseline": "#d9534f",
                        "optimum": "#337ab7",
                    },
                    colors_in_legend=[
                        "candidate (feasible)",
                        "candidate (infeasible)",
                        "baseline",
                        "optimum",
                    ],
                    title="Pareto candidates",
                    x_title="ΔP at nominal flow (kPa)",
                    y_title="Worst HBM maximum temperature (°C)",
                    height=320,
                )
                optimized_model = gr.Model3D(
                    label="Optimized cold plate (STL)",
                    height=400,
                )
                optimizer_files = gr.File(
                    label="Optimized STEP/STL",
                    file_count="multiple",
                    interactive=False,
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
    return demo


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("mock", "gemini"))
    args = parser.parse_args(argv)
    build_app(args.provider).queue().launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        server_port=int(os.getenv("PORT", "7860")),
    )


if __name__ == "__main__":
    main()
