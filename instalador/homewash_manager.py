import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from tkinter import messagebox, ttk

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config_env import carregar_env_arquivo, ler_env_variavel, salvar_env_variavel
from remote_control import extract_trycloudflare_link

try:
    import pystray  # type: ignore[import-not-found]
    from PIL import Image, ImageDraw, ImageTk  # type: ignore[import-not-found]
except Exception:
    pystray = None
    Image = None
    ImageDraw = None
    ImageTk = None


ENV_PATH = BASE_DIR / ".env"
MANAGER_HOST = "127.0.0.1"
MANAGER_PORT = 8766
RESTORE_SIGNAL = b"SHOW_HOMEWASH_MANAGER"
PID_FILES = [
    BASE_DIR / "streamlit_pro.pid",
    BASE_DIR / "cloudflare_tunnel.pid",
    BASE_DIR / "remote_control.pid",
    BASE_DIR / "control_tunnel.pid",
]

ENV_FIELDS = [
    ("APP_EMAIL_SENDER", "Email remetente"),
    ("APP_EMAIL_PASSWORD", "Senha app email", True),
    ("ALERTA_EMAIL_DESTINO", "Email destino link"),
    ("ALERTA_WHATSAPP_NUMERO", "WhatsApp destino (opcional)"),
    ("APP_PUBLIC_URL", "URL publica app (opcional)"),
    ("APP_CONTROL_URL", "URL publica controle (opcional)"),
    ("CF_TUNNEL_TOKEN", "Token tunnel app (opcional)", True),
    ("CF_CONTROL_TUNNEL_TOKEN", "Token tunnel controle (opcional)", True),
    ("APP_GOOGLE_CALENDAR_SYNC", "Google Calendar ativo (0/1)"),
    ("APP_GOOGLE_CALENDAR_ID", "Google Calendar ID (opcional)"),
    ("APP_GOOGLE_SERVICE_ACCOUNT_FILE", "Arquivo credencial Google"),
    ("APP_DB_PATH", "Banco de dados"),
]


class HomeWashManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Home Wash CRM - Gerenciador")
        self.geometry("920x680")
        self.minsize(780, 540)

        carregar_env_arquivo(str(BASE_DIR))

        self.mode_var = tk.StringVar(value="remoto")
        self.status_var = tk.StringVar(value="Status: parado")
        self.detail_var = tk.StringVar(value="")
        self.last_action_var = tk.StringVar(value="Ultima acao: nenhuma")
        self.cloudflare_status_var = tk.StringVar(value="Cloudflare: verificacao pendente")
        self.cloudflare_detail_var = tk.StringVar(value="")

        self.inputs = {}
        self._poll_job = None
        self.tray_icon = None
        self._window_icon_ref = None
        self.is_tray_enabled = pystray is not None and Image is not None and ImageDraw is not None
        self._instance_server = None
        self._instance_thread = None

        self._apply_window_icon_from_brand_logo()
        self._start_instance_server()
        self._build_ui()
        self._load_env()
        self._initial_checks()
        self._schedule_status_refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _logo_candidates(self):
        assets_dir = BASE_DIR / "assets"
        return [
            assets_dir / "logo.png",
            assets_dir / "logo_symbol_clean.png",
            assets_dir / "logo_full_clean.png",
            assets_dir / "favicon.png",
            assets_dir / "teste logo.jpeg",
            assets_dir / "teste logo.jpg",
            assets_dir / "logo.jpeg",
            assets_dir / "logo.jpg",
        ]

    def _load_icon_image(self):
        for candidate in self._logo_candidates():
            if not candidate.exists():
                continue
            try:
                suffix = candidate.suffix.lower()
                if suffix in (".png", ".gif", ".ppm", ".pgm"):
                    return tk.PhotoImage(file=str(candidate))
                if Image is not None and ImageTk is not None:
                    image = Image.open(candidate).convert("RGBA")
                    image.thumbnail((256, 256))
                    return ImageTk.PhotoImage(image)
            except Exception:
                continue
        return None

    def _apply_icon_to_window(self, window):
        icon_image = self._load_icon_image()
        if icon_image is None:
            return
        self._window_icon_ref = icon_image
        try:
            window.iconphoto(True, icon_image)
        except Exception:
            pass

    def _apply_window_icon_from_brand_logo(self):
        self._apply_icon_to_window(self)

    def _build_ui(self):
        wrapper = ttk.Frame(self, padding=14)
        wrapper.pack(fill="both", expand=True)

        title = ttk.Label(wrapper, text="Home Wash CRM - Painel de Controle", font=("Segoe UI", 15, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            wrapper,
            text="Configure uma vez e use como app normal no Windows. Inicie, pare ou reinicie sem reiniciar o computador.",
        )
        subtitle.pack(anchor="w", pady=(4, 10))

        control_panel = ttk.LabelFrame(wrapper, text="Controle do programa", padding=12)
        control_panel.pack(fill="x", pady=(0, 12))
        self._build_control_tab(control_panel)

        notebook = ttk.Notebook(wrapper)
        notebook.pack(fill="both", expand=True)

        config_tab = ttk.Frame(notebook, padding=12)
        cloudflare_tab = ttk.Frame(notebook, padding=12)
        notebook.add(config_tab, text="Configuracao inicial")
        notebook.add(cloudflare_tab, text="Cloudflare e celular")

        self.notebook = notebook
        self._build_config_tab(config_tab)
        self._build_cloudflare_tab(cloudflare_tab)
        self.notebook.select(1)

    def _create_scrollable_container(self, parent):
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas)

        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_window, width=event.width))
        self._bind_mousewheel(canvas, content)

        return content

    def _bind_mousewheel(self, canvas, content):
        def on_mousewheel(event):
            if event.delta:
                canvas.yview_scroll(int(-event.delta / 120), "units")
            elif getattr(event, "num", None) == 4:
                canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(1, "units")

        def bind_scroll(_event):
            canvas.bind_all("<MouseWheel>", on_mousewheel)
            canvas.bind_all("<Button-4>", on_mousewheel)
            canvas.bind_all("<Button-5>", on_mousewheel)

        def unbind_scroll(_event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        for widget in (canvas, content):
            widget.bind("<Enter>", bind_scroll)
            widget.bind("<Leave>", unbind_scroll)

    def _build_config_tab(self, parent):
        content = self._create_scrollable_container(parent)

        info = ttk.Label(
            content,
            text="Preencha os dados iniciais. Voce pode salvar e alterar depois quando quiser.",
        )
        info.pack(anchor="w", pady=(0, 10))

        form = ttk.Frame(content)
        form.pack(fill="both", expand=True)

        for row, field in enumerate(ENV_FIELDS):
            key = field[0]
            label = field[1]
            secret = len(field) > 2 and bool(field[2])

            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6)
            var = tk.StringVar(value="")
            entry = ttk.Entry(form, textvariable=var, width=62)
            if secret:
                entry.configure(show="*")
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            self.inputs[key] = var

        form.grid_columnconfigure(1, weight=1)

        actions = ttk.Frame(content)
        actions.pack(fill="x", pady=(14, 0))

        ttk.Button(actions, text="Salvar configuracoes", command=self.save_config).pack(side="left")
        ttk.Button(actions, text="Recarregar", command=self._load_env).pack(side="left", padx=8)
        ttk.Button(actions, text="Abrir pasta do projeto", command=self.open_project_folder).pack(side="left")

    def _build_button_grid(self, parent, buttons, columns=3, pady=(6, 6)):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=pady)

        for index, (label, command) in enumerate(buttons):
            row = index // columns
            column = index % columns
            ttk.Button(frame, text=label, command=command).grid(
                row=row,
                column=column,
                sticky="ew",
                padx=4,
                pady=4,
            )

        for column in range(columns):
            frame.grid_columnconfigure(column, weight=1)

        return frame

    def _build_control_tab(self, parent):
        mode_frame = ttk.Frame(parent)
        mode_frame.pack(fill="x")

        ttk.Label(mode_frame, text="Modo de inicializacao:").pack(side="left")
        mode_combo = ttk.Combobox(
            mode_frame,
            values=["local", "remoto"],
            textvariable=self.mode_var,
            width=14,
            state="readonly",
        )
        mode_combo.pack(side="left", padx=(8, 0))

        status_card = ttk.LabelFrame(parent, text="Status", padding=10)
        status_card.pack(fill="x", pady=(12, 10))

        ttk.Label(status_card, textvariable=self.status_var, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(status_card, textvariable=self.detail_var).pack(anchor="w", pady=(4, 0))
        ttk.Label(status_card, textvariable=self.last_action_var).pack(anchor="w", pady=(4, 0))

        self._build_button_grid(
            parent,
            [
                ("Iniciar", self.start_program),
                ("Iniciar gratis sem dominio", self.start_free_remote_mode),
                ("Parar", self.stop_program),
                ("Reiniciar", self.restart_program),
                ("Atualizar status", self.refresh_status),
                ("Minimizar para bandeja", self.minimize_to_tray),
            ],
            columns=3,
        )

        self._build_button_grid(
            parent,
            [
                ("Abrir sincronizacao web", self.open_sync_hub),
                ("Abrir CRM local", self.open_local_url),
                ("Ver startup_log", self.open_startup_log),
                ("Configurar iniciar com Windows", self.enable_startup),
            ],
            columns=3,
            pady=(2, 0),
        )

        notes = ttk.Label(
            parent,
            text="Observacao: no modo remoto, o sistema inicia CRM + tunnel + envio de link automaticamente.",
        )
        notes.pack(anchor="w", pady=(12, 0))

        if not self.is_tray_enabled:
            warn = ttk.Label(
                parent,
                text="Bandeja do sistema indisponivel. Instale pystray e pillow para habilitar.",
            )
            warn.pack(anchor="w", pady=(6, 0))

    def _build_cloudflare_tab(self, parent):
        content = self._create_scrollable_container(parent)

        intro = ttk.Label(
            content,
            text="Use esta aba para deixar o link do celular estavel e conferir se o acesso remoto esta pronto.",
        )
        intro.pack(anchor="w", pady=(0, 10))

        summary = ttk.LabelFrame(content, text="Diagnostico rapido", padding=10)
        summary.pack(fill="x")
        ttk.Label(summary, textvariable=self.cloudflare_status_var, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(summary, textvariable=self.cloudflare_detail_var, wraplength=820, justify="left").pack(anchor="w", pady=(6, 0))

        checklist = ttk.LabelFrame(content, text="Checklist para link estavel no celular", padding=10)
        checklist.pack(fill="x", pady=(12, 10))

        checklist_lines = [
            "1. cloudflared.exe precisa existir na pasta do projeto ou no PATH.",
            "2. Sem dominio (gratis): deixe tokens/URL em branco e use Quick Tunnel temporario.",
            "3. Com dominio (estavel): preencha CF_TUNNEL_TOKEN para o app principal (porta 8501).",
            "4. Com dominio (estavel): preencha APP_PUBLIC_URL com a URL publica fixa do CRM.",
            "5. Opcional: preencha CF_CONTROL_TUNNEL_TOKEN e APP_CONTROL_URL para reinicio remoto.",
            "6. Salve as configuracoes e inicie em modo remoto.",
        ]
        for line in checklist_lines:
            ttk.Label(checklist, text=line).pack(anchor="w", pady=2)

        primary_actions = ttk.LabelFrame(content, text="Acoes principais", padding=10)
        primary_actions.pack(fill="x", pady=(8, 8))
        self._build_button_grid(
            primary_actions,
            [
                ("Iniciar gratis sem dominio", self.start_free_remote_mode),
                ("Abrir sincronizacao web", self.open_sync_hub),
                ("Testar link publico", self.test_public_link),
                ("Copiar link publico", self.copy_public_link),
                ("Reenviar email", self.resend_remote_email),
                ("Corrigir acesso celular", self.auto_fix_cellular_access),
            ],
            columns=3,
            pady=(0, 0),
        )

        support_actions = ttk.LabelFrame(content, text="Configuracao e suporte", padding=10)
        support_actions.pack(fill="x", pady=(0, 8))
        self._build_button_grid(
            support_actions,
            [
                ("Assistente tunnel nomeado", self.open_named_tunnel_wizard),
                ("Validar configuracao remota", self.validate_cloudflare_setup),
                ("Abrir link publico", self.open_public_link),
                ("Instalar cloudflared", self.install_cloudflared),
                ("Abrir guia Cloudflare", self.open_cloudflare_guide),
                ("Abrir painel Cloudflare", self.open_cloudflare_dashboard),
                ("Ir para configuracao inicial", lambda: self.notebook.select(0)),
            ],
            columns=3,
            pady=(0, 0),
        )

        tips = ttk.LabelFrame(content, text="Recomendacao pratica", padding=10)
        tips.pack(fill="both", expand=True)
        ttk.Label(
            tips,
            text=(
                "Se os tokens e URLs nao estiverem preenchidos, o sistema usa Quick Tunnel temporario. "
                "Esse modo pode trocar o link, demorar para propagar ou falhar no celular. "
                "Fluxo gratis rapido: iniciar em modo remoto, aguardar gerar link, depois testar, copiar e abrir o link publico. "
                "Para uso estavel, configure o tunnel nomeado, salve os dados no painel e use o botao Testar link publico antes de confiar no acesso pelo celular."
            ),
            wraplength=820,
            justify="left",
        ).pack(anchor="w")

    def _initial_checks(self):
        missing_required = []
        for key in ("APP_EMAIL_SENDER", "APP_EMAIL_PASSWORD", "ALERTA_EMAIL_DESTINO"):
            value = (self.inputs.get(key).get() if key in self.inputs else "").strip()
            if not value:
                missing_required.append(key)

        if not ENV_PATH.exists() or missing_required:
            messagebox.showinfo(
                "Configuracao inicial",
                "Preencha os dados de email na aba Configuracao inicial e clique em Salvar.\n\n"
                "A janela vai permanecer no painel principal de controle.",
            )

    def _load_env(self):
        carregar_env_arquivo(str(BASE_DIR))
        for field in ENV_FIELDS:
            key = field[0]
            current = ler_env_variavel(str(BASE_DIR), key, "")
            self.inputs[key].set(current)
        self._update_cloudflare_summary()

    def save_config(self):
        required = ["APP_EMAIL_SENDER", "APP_EMAIL_PASSWORD", "ALERTA_EMAIL_DESTINO"]
        for key in required:
            if not self.inputs[key].get().strip():
                messagebox.showerror("Campo obrigatorio", f"Preencha o campo: {key}")
                return

        for field in ENV_FIELDS:
            key = field[0]
            value = self.inputs[key].get().strip()
            salvar_env_variavel(str(BASE_DIR), key, value)

        self._mark_action("Configuracoes salvas no .env")
        messagebox.showinfo("Sucesso", "Configuracoes salvas com sucesso.")

    def _run_background(self, args, shell=False):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.Popen(
            args,
            cwd=str(BASE_DIR),
            shell=shell,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def start_program(self, allow_unstable_remote=False, keep_control_tab=False):
        mode = self.mode_var.get().strip().lower()
        try:
            if mode == "local":
                self._run_background(["cmd", "/c", "iniciar_sistema.bat", "local-bg"])
                self._mark_action("Inicializacao local acionada")
            else:
                if not allow_unstable_remote and not self._remote_ready_for_stable_link():
                    allow_unstable_remote = True
                    self._mark_action("Inicializacao remota gratuita acionada por padrao")
                self._run_background(
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(BASE_DIR / "iniciar_cloudflare_background.ps1"),
                    ]
                )
                if allow_unstable_remote and not self._remote_ready_for_stable_link():
                    self._mark_action("Inicializacao remota gratuita acionada")
                else:
                    self._mark_action("Inicializacao remota acionada")
            if keep_control_tab:
                self.focus_force()
            self.after(2500, self.refresh_status)
        except Exception as exc:
            messagebox.showerror("Falha ao iniciar", str(exc))

    def start_free_remote_mode(self):
        for key in ("CF_TUNNEL_TOKEN", "APP_PUBLIC_URL", "CF_CONTROL_TUNNEL_TOKEN", "APP_CONTROL_URL"):
            self.inputs[key].set("")
            salvar_env_variavel(str(BASE_DIR), key, "")

        self.mode_var.set("remoto")
        self._load_env()
        self._mark_action("Modo gratis sem dominio preparado")
        self.start_program(allow_unstable_remote=True, keep_control_tab=True)

    def stop_program(self):
        thread = threading.Thread(target=self._stop_worker, daemon=True)
        thread.start()

    def _stop_worker(self):
        try:
            self._stop_by_pid_files()
            self._stop_by_commandline()
            self._mark_action("Parada concluida")
            self.after(1200, self.refresh_status)
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("Falha ao parar", str(exc)))

    def restart_program(self):
        def worker():
            self._stop_worker()
            time.sleep(2)
            self.after(0, self.start_program)
            self.after(0, lambda: self._mark_action("Reinicio acionado"))

        threading.Thread(target=worker, daemon=True).start()

    def _stop_by_pid_files(self):
        for pid_file in PID_FILES:
            pid = self._read_pid(pid_file)
            if not pid:
                continue
            self._taskkill_pid(pid)

    def _read_pid(self, path: Path):
        try:
            if not path.exists():
                return None
            value = path.read_text(encoding="ascii", errors="ignore").strip()
            return int(value) if value else None
        except Exception:
            return None

    def _taskkill_pid(self, pid: int):
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, text=True)

    def _stop_by_commandline(self):
        cmd = (
            "Get-CimInstance Win32_Process | Where-Object { "
            "($_.Name -match 'python|pythonw|cloudflared') -and ("
            "$_.CommandLine -match 'crm_pro.py' -or "
            "$_.CommandLine -match 'remote_control.py' -or "
            "$_.CommandLine -match 'localhost:8501' -or "
            "$_.CommandLine -match 'localhost:8765'"
            ") } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            capture_output=True,
            text=True,
        )

    def refresh_status(self):
        active_8501 = self._port_open(8501)
        active_8765 = self._port_open(8765)

        if active_8501:
            self.status_var.set("Status: ativo")
        else:
            self.status_var.set("Status: parado")

        detail = [
            f"CRM (8501): {'online' if active_8501 else 'offline'}",
            f"Controle remoto (8765): {'online' if active_8765 else 'offline'}",
            f".env: {'ok' if ENV_PATH.exists() else 'ausente'}",
        ]
        self.detail_var.set(" | ".join(detail))
        self._update_cloudflare_summary()

    def _schedule_status_refresh(self):
        self.refresh_status()
        self._poll_job = self.after(4000, self._schedule_status_refresh)

    def _port_open(self, port: int):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.8)
        try:
            return sock.connect_ex(("127.0.0.1", port)) == 0
        finally:
            sock.close()

    def _mark_action(self, text: str):
        now = time.strftime("%d/%m/%Y %H:%M:%S")
        self.last_action_var.set(f"Ultima acao: {text} ({now})")

    def open_local_url(self):
        subprocess.run(["cmd", "/c", "start", "", "http://127.0.0.1:8501"], check=False)

    def open_project_folder(self):
        subprocess.run(["explorer", str(BASE_DIR)], check=False)

    def open_cloudflare_guide(self):
        guide_path = BASE_DIR / "GUIA_CLOUDFLARE.md"
        if guide_path.exists():
            subprocess.run(["notepad", str(guide_path)], check=False)
        else:
            messagebox.showerror("Guia nao encontrado", "GUIA_CLOUDFLARE.md nao foi encontrado na pasta do projeto.")

    def open_cloudflare_dashboard(self):
        subprocess.run(["cmd", "/c", "start", "", "https://one.dash.cloudflare.com/"], check=False)

    def open_startup_log(self):
        log_path = BASE_DIR / "startup_log.txt"
        if not log_path.exists():
            log_path.write_text("", encoding="utf-8")
        subprocess.run(["notepad", str(log_path)], check=False)

    def resend_remote_email(self):
        sender = self.inputs["APP_EMAIL_SENDER"].get().strip()
        password = self.inputs["APP_EMAIL_PASSWORD"].get().strip()
        destination = self.inputs["ALERTA_EMAIL_DESTINO"].get().strip()
        if not sender or not password or not destination:
            messagebox.showwarning(
                "Email incompleto",
                "Preencha Email remetente, Senha app email e Email destino link antes de reenviar.",
            )
            self.notebook.select(0)
            return

        python_exe = str((BASE_DIR / ".venv" / "Scripts" / "python.exe"))
        if not (BASE_DIR / ".venv" / "Scripts" / "python.exe").exists():
            python_exe = sys.executable or "python"

        subprocess.Popen(
            [python_exe, str(BASE_DIR / "enviar_ip_email.py"), "cloudflare"],
            cwd=str(BASE_DIR),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._mark_action("Reenvio manual do email acionado")
        messagebox.showinfo(
            "Reenvio iniciado",
            "O sistema vai tentar reenviar o email com o link remoto atual. Aguarde alguns segundos e confira a caixa de entrada.",
        )

    def enable_startup(self):
        try:
            subprocess.run(["cmd", "/c", "configurar_automacao.bat"], cwd=str(BASE_DIR), check=False)
            self._mark_action("Configurado para iniciar com Windows")
            messagebox.showinfo("Sucesso", "Ativacao de inicio com Windows executada.")
        except Exception as exc:
            messagebox.showerror("Falha", str(exc))

    def install_cloudflared(self):
        if self._cloudflared_exists():
            messagebox.showinfo("Cloudflared", "cloudflared.exe ja esta disponivel para uso remoto.")
            self._update_cloudflare_summary()
            return

        def worker():
            ok, detail = self._download_cloudflared()

            def done():
                self._update_cloudflare_summary()
                if ok and self._cloudflared_exists():
                    self._mark_action("cloudflared instalado automaticamente")
                    messagebox.showinfo("Sucesso", "cloudflared.exe baixado com sucesso na pasta do projeto.")
                else:
                    messagebox.showerror(
                        "Falha no download",
                        (
                            "Nao foi possivel baixar o cloudflared automaticamente.\n\n"
                            "Verifique internet/permissoes e tente de novo.\n\n"
                            f"Detalhe tecnico: {detail}"
                        ),
                    )

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def validate_cloudflare_setup(self):
        self._load_env()
        summary = self._build_cloudflare_report()
        self.notebook.select(1)
        if self._remote_ready_for_stable_link():
            messagebox.showinfo("Cloudflare pronto", summary)
        else:
            messagebox.showwarning("Cloudflare incompleto", summary)

    def test_public_link(self):
        self._load_env()
        target_url = self.inputs["APP_PUBLIC_URL"].get().strip()
        if not target_url:
            messagebox.showwarning(
                "URL nao preenchida",
                "Preencha primeiro o campo APP_PUBLIC_URL ou use o assistente de tunnel nomeado.",
            )
            self.notebook.select(1)
            return

        target_url = self._normalize_url(target_url)

        def worker():
            outcome = self._probe_url(target_url)

            def done():
                ok, status, error_text = outcome
                if ok and status is not None and 200 <= status < 500:
                    self._mark_action("Link publico testado com sucesso")
                    messagebox.showinfo(
                        "Link funcionando",
                        f"O link publico respondeu corretamente.\n\nURL: {target_url}\nStatus HTTP: {status}",
                    )
                else:
                    messagebox.showwarning(
                        "Link ainda nao respondeu",
                        (
                            "O link publico ainda nao respondeu como esperado.\n\n"
                            f"URL: {target_url}\n"
                            f"Detalhe: {error_text or 'sem resposta valida'}\n\n"
                            "Se voce acabou de iniciar o tunnel, espere alguns segundos e teste de novo."
                        ),
                    )

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def auto_fix_cellular_access(self):
        self.notebook.select(1)
        self._mark_action("Correcao automatica do acesso celular iniciada")

        def worker():
            if not self._cloudflared_exists():
                ok, detail = self._download_cloudflared()
                if not ok:
                    self.after(
                        0,
                        lambda: messagebox.showerror(
                            "Falha na correcao automatica",
                            (
                                "Nao consegui instalar o cloudflared automaticamente.\n\n"
                                "Clique em 'Instalar cloudflared' ou tente novamente mais tarde.\n\n"
                                f"Detalhe: {detail}"
                            ),
                        ),
                    )
                    return

            main_token = ler_env_variavel(str(BASE_DIR), "CF_TUNNEL_TOKEN", "").strip()
            main_url = ler_env_variavel(str(BASE_DIR), "APP_PUBLIC_URL", "").strip()

            if not main_token or not main_url:
                def open_wizard_msg():
                    self._load_env()
                    messagebox.showwarning(
                        "Faltam dados do Cloudflare",
                        (
                            "Para concluir a correcao automatica, faltam o token e/ou a URL publica principal.\n\n"
                            "Vai abrir o assistente para voce colar esses dados."
                        ),
                    )
                    self.open_named_tunnel_wizard()

                self.after(0, open_wizard_msg)
                return

            restart_script = BASE_DIR / "reiniciar_link_mobile.ps1"
            if restart_script.exists():
                subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(restart_script),
                        "-ProjectDir",
                        str(BASE_DIR),
                    ],
                    cwd=str(BASE_DIR),
                    capture_output=True,
                    text=True,
                )

            target_url = self._normalize_url(main_url)
            outcome = (False, None, "timeout")
            for _ in range(6):
                outcome = self._probe_url(target_url, timeout=12)
                ok, status, _err = outcome
                if ok and status is not None and 200 <= status < 500:
                    break
                time.sleep(5)

            def done():
                self._load_env()
                ok, status, error_text = outcome
                if ok and status is not None and 200 <= status < 500:
                    self._mark_action("Correcao automatica concluida")
                    messagebox.showinfo(
                        "Correcao concluida",
                        (
                            "A correcao automatica terminou com sucesso.\n\n"
                            f"URL validada: {target_url}\n"
                            f"Status HTTP: {status}\n\n"
                            "Agora voce pode abrir ou copiar o link direto pelos botoes desta aba."
                        ),
                    )
                else:
                    messagebox.showwarning(
                        "Correcao parcial",
                        (
                            "As configuracoes foram aplicadas, mas o link ainda nao respondeu como esperado.\n\n"
                            f"URL testada: {target_url}\n"
                            f"Detalhe: {error_text or 'sem resposta valida'}\n\n"
                            "Espere alguns segundos e clique em 'Testar link publico' novamente."
                        ),
                    )

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def open_public_link(self):
        self._load_env()
        target_url = self._get_active_public_url()
        if not target_url:
            messagebox.showwarning(
                "URL nao preenchida",
                "Nenhuma URL publica foi encontrada ainda. Se estiver em modo gratis, aguarde a URL trycloudflare aparecer e tente novamente.",
            )
            self.notebook.select(1)
            return

        subprocess.run(["cmd", "/c", "start", "", target_url], check=False)
        self._mark_action("Link publico aberto no navegador")

    def copy_public_link(self):
        self._load_env()
        target_url = self._get_active_public_url()
        if not target_url:
            messagebox.showwarning(
                "URL nao preenchida",
                "Nenhuma URL publica foi encontrada ainda. Se estiver em modo gratis, aguarde a URL trycloudflare aparecer e tente novamente.",
            )
            self.notebook.select(1)
            return
        self.clipboard_clear()
        self.clipboard_append(target_url)
        self.update_idletasks()
        self._mark_action("Link publico copiado")
        messagebox.showinfo("Link copiado", f"A URL publica foi copiada:\n\n{target_url}")

    def open_named_tunnel_wizard(self):
        dialog = tk.Toplevel(self)
        dialog.title("Assistente de tunnel nomeado")
        dialog.geometry("760x430")
        dialog.transient(self)
        dialog.grab_set()

        wrapper = ttk.Frame(dialog, padding=14)
        wrapper.pack(fill="both", expand=True)

        ttk.Label(
            wrapper,
            text="Cole abaixo os dados do Cloudflare Zero Trust. O assistente grava no .env e no ambiente do Windows.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w")

        ttk.Label(
            wrapper,
            text="Passo pratico: crie os tunnels no painel Cloudflare, copie token e URL publica, cole aqui e clique Aplicar.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(6, 12))

        ttk.Label(
            wrapper,
            text="Se tiver duvida, clique em Passo a passo detalhado para abrir o guia completo com links de sites externos.",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        fields_frame = ttk.Frame(wrapper)
        fields_frame.pack(fill="both", expand=True)

        wizard_fields = [
            ("CF_TUNNEL_TOKEN", "Token principal do CRM", True),
            ("APP_PUBLIC_URL", "URL publica principal"),
            ("CF_CONTROL_TUNNEL_TOKEN", "Token do controle remoto", True),
            ("APP_CONTROL_URL", "URL publica do controle remoto"),
        ]
        vars_map = {}
        for row, field in enumerate(wizard_fields):
            key = field[0]
            label = field[1]
            secret = len(field) > 2 and bool(field[2])
            ttk.Label(fields_frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=8)
            var = tk.StringVar(value=self.inputs.get(key).get().strip())
            entry = ttk.Entry(fields_frame, textvariable=var, width=70)
            if secret:
                entry.configure(show="*")
            entry.grid(row=row, column=1, sticky="ew", pady=8)
            vars_map[key] = var
        fields_frame.grid_columnconfigure(1, weight=1)

        helper = ttk.Label(
            wrapper,
            text="Obrigatorio para link estavel: token principal + URL principal. Controle remoto e opcional.",
        )
        helper.pack(anchor="w", pady=(6, 10))

        buttons = ttk.Frame(wrapper)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Abrir painel Cloudflare", command=self.open_cloudflare_dashboard).pack(side="left")
        ttk.Button(buttons, text="Passo a passo detalhado", command=self.open_cloudflare_guide).pack(side="left", padx=8)
        ttk.Button(
            buttons,
            text="Aplicar configuracao",
            command=lambda: self.apply_named_tunnel_config(vars_map, dialog),
        ).pack(side="right")
        ttk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(side="right", padx=8)

    def apply_named_tunnel_config(self, vars_map, dialog):
        main_token = vars_map["CF_TUNNEL_TOKEN"].get().strip()
        main_url = vars_map["APP_PUBLIC_URL"].get().strip()
        control_token = vars_map["CF_CONTROL_TUNNEL_TOKEN"].get().strip()
        control_url = vars_map["APP_CONTROL_URL"].get().strip()

        if not main_token or not main_url:
            messagebox.showerror(
                "Campos obrigatorios",
                "Preencha pelo menos o token principal e a URL publica principal para configurar o link estavel.",
                parent=dialog,
            )
            return

        script_path = BASE_DIR / "configurar_tunnel_nomeado.ps1"
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-ProjectDir",
            str(BASE_DIR),
            "-MainToken",
            main_token,
            "-MainUrl",
            main_url,
            "-ControlToken",
            control_token,
            "-ControlUrl",
            control_url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            messagebox.showerror(
                "Falha ao aplicar configuracao",
                (result.stderr or result.stdout or "Nao foi possivel aplicar a configuracao do tunnel nomeado.").strip(),
                parent=dialog,
            )
            return

        self._load_env()
        self._mark_action("Tunnel nomeado configurado pela interface")
        dialog.destroy()
        self.notebook.select(1)
        messagebox.showinfo(
            "Configuracao aplicada",
            "Tunnel nomeado salvo com sucesso. Agora o link remoto estavel pode ser usado ao iniciar em modo remoto.",
        )

    def _cloudflared_exists(self):
        if (BASE_DIR / "cloudflared.exe").exists():
            return True
        result = subprocess.run("where cloudflared", capture_output=True, text=True, shell=True)
        return result.returncode == 0

    def _download_cloudflared(self):
        cmd = (
            "$ErrorActionPreference='Stop'; "
            "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' "
            "-OutFile 'cloudflared.exe'"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
        )
        detail = (result.stderr or result.stdout or "sem detalhes").strip()
        return (result.returncode == 0 and self._cloudflared_exists(), detail)

    def _normalize_url(self, url):
        target_url = (url or "").strip()
        if target_url and not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = f"https://{target_url}"
        return target_url

    def _get_quick_tunnel_url(self):
        for log_name in ("cloudflare_tunnel.err.log", "cloudflare_tunnel.log"):
            found = extract_trycloudflare_link(str(BASE_DIR / log_name))
            if found:
                return found
        return ""

    def _get_quick_api_tunnel_url(self):
        for log_name in ("api_tunnel.err.log", "api_tunnel.log"):
            found = extract_trycloudflare_link(str(BASE_DIR / log_name))
            if found:
                return found
        return ""

    def _get_active_public_url(self):
        target_url = self.inputs["APP_PUBLIC_URL"].get().strip()
        if not target_url:
            target_url = self._get_quick_tunnel_url()
        return self._normalize_url(target_url)

    def _get_active_api_public_url(self):
        target_url = ler_env_variavel(str(BASE_DIR), "APP_API_PUBLIC_URL", "").strip()
        if not target_url:
            target_url = self._get_quick_api_tunnel_url()
        return self._normalize_url(target_url)

    def _get_web_frontend_base_url(self):
        configured = ler_env_variavel(str(BASE_DIR), "APP_WEB_FRONTEND_URL", "").strip()
        if configured:
            return self._normalize_url(configured)
        return "https://giovanealvesm.github.io/Precificacao"

    def _build_sync_hub_url(self):
        web_base = self._get_web_frontend_base_url()
        api_url = self._get_active_api_public_url()
        if not web_base or not api_url:
            return ""
        query = urllib.parse.urlencode({"api": api_url})
        return f"{web_base}/sync.html?{query}"

    def _probe_url(self, target_url, timeout=12):
        try:
            req = urllib.request.Request(target_url, headers={"User-Agent": "homewash-health-check/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status = int(getattr(response, "status", 200) or 200)
            return (True, status, "")
        except urllib.error.HTTPError as exc:
            return (True, exc.code, "")
        except Exception as exc:
            return (False, None, str(exc))

    def _remote_ready_for_stable_link(self):
        app_token = self.inputs["CF_TUNNEL_TOKEN"].get().strip()
        app_url = self.inputs["APP_PUBLIC_URL"].get().strip()
        return bool(self._cloudflared_exists() and app_token and app_url)

    def _update_cloudflare_summary(self):
        if self._remote_ready_for_stable_link():
            self.cloudflare_status_var.set("Cloudflare: pronto para link estavel no celular")
            control_ready = bool(
                self.inputs["CF_CONTROL_TUNNEL_TOKEN"].get().strip() and self.inputs["APP_CONTROL_URL"].get().strip()
            )
            details = ["cloudflared detectado", "token principal configurado", "URL publica principal configurada"]
            if control_ready:
                details.append("controle remoto configurado")
            else:
                details.append("controle remoto ainda opcional")
            self.cloudflare_detail_var.set(" | ".join(details))
            return

        quick_url = self._get_quick_tunnel_url()
        if quick_url and self._cloudflared_exists():
            self.cloudflare_status_var.set("Cloudflare: Quick Tunnel ativo")
            self.cloudflare_detail_var.set(
                f"URL temporaria detectada: {quick_url} | Se houver erro 530, aguarde alguns segundos e teste novamente."
            )
            return

        missing = []
        if not self._cloudflared_exists():
            missing.append("cloudflared.exe")
        if not self.inputs["CF_TUNNEL_TOKEN"].get().strip():
            missing.append("CF_TUNNEL_TOKEN")
        if not self.inputs["APP_PUBLIC_URL"].get().strip():
            missing.append("APP_PUBLIC_URL")

        self.cloudflare_status_var.set("Cloudflare: incompleto para link estavel")
        self.cloudflare_detail_var.set("Faltando: " + ", ".join(missing) if missing else "Configuracao parcial detectada.")

    def _build_cloudflare_report(self):
        items = []
        items.append(f"cloudflared.exe: {'OK' if self._cloudflared_exists() else 'FALTANDO'}")
        items.append(f"CF_TUNNEL_TOKEN: {'OK' if self.inputs['CF_TUNNEL_TOKEN'].get().strip() else 'FALTANDO'}")
        items.append(f"APP_PUBLIC_URL: {'OK' if self.inputs['APP_PUBLIC_URL'].get().strip() else 'FALTANDO'}")
        items.append(f"CF_CONTROL_TUNNEL_TOKEN: {'OK' if self.inputs['CF_CONTROL_TUNNEL_TOKEN'].get().strip() else 'OPCIONAL'}")
        items.append(f"APP_CONTROL_URL: {'OK' if self.inputs['APP_CONTROL_URL'].get().strip() else 'OPCIONAL'}")

        if self._remote_ready_for_stable_link():
            items.append("")
            items.append("Resultado: o CRM esta pronto para usar link remoto estavel no celular.")
        else:
            items.append("")
            items.append("Resultado: se iniciar remoto agora, o sistema pode cair em Quick Tunnel temporario.")

        return "\n".join(items)

    def open_sync_hub(self):
        self._load_env()
        target_url = self._build_sync_hub_url()
        if not target_url:
            messagebox.showwarning(
                "Sincronizacao indisponivel",
                "A URL temporaria da API ainda nao foi encontrada.\n\nInicie o modo remoto, aguarde alguns segundos e clique novamente.",
            )
            self.notebook.select(1)
            return

        subprocess.run(["cmd", "/c", "start", "", target_url], check=False)
        self._mark_action("Central de sincronizacao aberta no navegador")

    def _on_close(self):
        if self.is_tray_enabled:
            self.minimize_to_tray()
            return
        self._shutdown()

    def _shutdown(self):
        if self._poll_job:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        self._stop_instance_server()
        self._stop_tray_icon()
        self.destroy()

    def _start_instance_server(self):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((MANAGER_HOST, MANAGER_PORT))
            server.listen(5)
            self._instance_server = server
        except OSError:
            self._instance_server = None
            return

        def serve():
            while self._instance_server:
              try:
                  client, _address = self._instance_server.accept()
              except OSError:
                  break
              try:
                  payload = client.recv(128)
                  if payload == RESTORE_SIGNAL:
                      self.after(0, self.restore_from_tray)
              except OSError:
                  pass
              finally:
                  try:
                      client.close()
                  except OSError:
                      pass

        self._instance_thread = threading.Thread(target=serve, daemon=True)
        self._instance_thread.start()

    def _stop_instance_server(self):
        if self._instance_server:
            try:
                self._instance_server.close()
            except OSError:
                pass
            self._instance_server = None

    def _create_tray_image(self):
        if Image is not None:
            for candidate in self._logo_candidates():
                if not candidate.exists():
                    continue
                try:
                    image = Image.open(candidate).convert("RGBA")
                    image.thumbnail((64, 64))
                    bg = Image.new("RGBA", (64, 64), (13, 47, 63, 255))
                    x = (64 - image.width) // 2
                    y = (64 - image.height) // 2
                    bg.alpha_composite(image, (x, y))
                    return bg.convert("RGB")
                except Exception:
                    continue

        image = Image.new("RGB", (64, 64), (13, 47, 63))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=10, fill=(22, 141, 160))
        draw.rounded_rectangle((18, 18, 46, 46), radius=8, fill=(231, 245, 247))
        draw.rectangle((26, 22, 38, 42), fill=(22, 141, 160))
        return image

    def minimize_to_tray(self):
        if not self.is_tray_enabled:
            return
        if self.tray_icon:
            self.withdraw()
            return

        self.withdraw()
        self._start_tray_icon()
        self._mark_action("Aplicativo minimizado para bandeja")

    def restore_from_tray(self):
        self.deiconify()
        self.state("normal")
        self.lift()
        self.attributes("-topmost", True)
        self.after(150, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _tray_safe(self, callback):
        self.after(0, callback)

    def _start_tray_icon(self):
        if self.tray_icon or not self.is_tray_enabled:
            return

        menu = pystray.Menu(
            pystray.MenuItem("Abrir painel", lambda icon, item: self._tray_safe(self.restore_from_tray)),
            pystray.MenuItem("Iniciar", lambda icon, item: self._tray_safe(self.start_program)),
            pystray.MenuItem("Parar", lambda icon, item: self._tray_safe(self.stop_program)),
            pystray.MenuItem("Reiniciar", lambda icon, item: self._tray_safe(self.restart_program)),
            pystray.MenuItem("Sair", lambda icon, item: self._tray_safe(self._shutdown)),
        )

        self.tray_icon = pystray.Icon("homewash_crm", self._create_tray_image(), "Home Wash CRM", menu)
        thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        thread.start()

    def _stop_tray_icon(self):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None


def notify_existing_manager():
    try:
        client = socket.create_connection((MANAGER_HOST, MANAGER_PORT), timeout=1.5)
        client.sendall(RESTORE_SIGNAL)
        client.close()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    if notify_existing_manager():
        sys.exit(0)
    app = HomeWashManager()
    app.mainloop()
