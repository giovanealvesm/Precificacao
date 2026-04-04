# -*- coding: utf-8 -*-
import smtplib
import socket
import subprocess
import os
import time
import json
import urllib.parse
import urllib.request
import urllib.error
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import sys
import io

from config_env import carregar_env_arquivo
from theme import BRAND_COLORS
from remote_control import build_control_urls, extract_trycloudflare_link, get_or_create_token

# Configura encoding para suportar emojis no Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
carregar_env_arquivo(BASE_DIR)

SEU_EMAIL = os.getenv("APP_EMAIL_SENDER", "").strip()
SENHA_APP = os.getenv("APP_EMAIL_PASSWORD", "").strip()
EMAIL_DESTINO = os.getenv("ALERTA_EMAIL_DESTINO", "").strip()
NUMERO_WHATSAPP = os.getenv("ALERTA_WHATSAPP_NUMERO", "").strip()

EMAIL_AUDIT_LOG = os.path.join(BASE_DIR, "email_envios.log")
EMAIL_AUDIT_MAX_LINES = 1000
DEFAULT_WEB_APP_URL = "https://giovanealvesm.github.io/Precificacao/"


def _env_bool(chave, padrao=False):
    valor = str(os.getenv(chave, "") or "").strip().lower()
    if not valor:
        return bool(padrao)
    return valor in {"1", "true", "sim", "yes", "on"}


def contexto_teste_ativo(log_path=""):
    if _env_bool("APP_TEST_PUBLIC_ADMIN", False):
        return True
    texto_log = str(log_path or "").strip().lower()
    return "_test" in texto_log or "teste" in texto_log


def _rotacionar_log_email(max_linhas=EMAIL_AUDIT_MAX_LINES):
    """Mantem apenas as ultimas N linhas do log de auditoria."""
    try:
        if not os.path.exists(EMAIL_AUDIT_LOG):
            return
        with open(EMAIL_AUDIT_LOG, "r", encoding="utf-8", errors="ignore") as f:
            linhas = f.readlines()
        if len(linhas) <= max_linhas:
            return
        with open(EMAIL_AUDIT_LOG, "w", encoding="utf-8") as f:
            f.writelines(linhas[-max_linhas:])
    except Exception:
        # Nao interrompe o fluxo principal se houver falha de IO no log.
        pass


def registrar_log_email(status, destino, link, erro=""):
    """Registra auditoria de envio de email com data/hora local."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        _rotacionar_log_email()
        with open(EMAIL_AUDIT_LOG, "a", encoding="utf-8") as f:
            linha = f"{timestamp} | status={status} | destino={destino} | link={link}"
            if erro:
                linha += f" | erro={erro}"
            f.write(linha + "\n")
        _rotacionar_log_email()
    except Exception:
        # Nao interrompe o fluxo principal se houver falha de IO no log.
        pass


def _candidate_cloudflare_logs(log_path):
    """Retorna candidatos de arquivo de log para o tunnel (stdout/stderr)."""
    candidatos = []
    if log_path:
        candidatos.append(log_path)
        if log_path.endswith(".log") and not log_path.endswith(".err.log"):
            candidatos.append(log_path[:-4] + ".err.log")
        if log_path.endswith(".err.log"):
            candidatos.append(log_path.replace(".err.log", ".log"))

    # Fallback padrao quando chamado sem argumento.
    candidatos.extend(["cloudflare_tunnel.err.log", "cloudflare_tunnel.log"])

    vistos = set()
    resultado = []
    for caminho in candidatos:
        if not caminho:
            continue
        abs_path = caminho if os.path.isabs(caminho) else os.path.join(BASE_DIR, caminho)
        norm = os.path.normcase(os.path.abspath(abs_path))
        if norm not in vistos:
            vistos.add(norm)
            resultado.append(abs_path)
    return resultado

def obter_link_cloudflare(log_path, tentativas=30, espera=2):
    """Lê o log do cloudflared e extrai o link trycloudflare"""
    print("[CLOUDFLARE] Aguardando link do tunnel...")
    padrao = re.compile(r"https://[a-zA-Z0-9\-.]+\.trycloudflare\.com")
    candidatos = _candidate_cloudflare_logs(log_path)

    for i in range(tentativas):
        for caminho in candidatos:
            try:
                if os.path.exists(caminho):
                    with open(caminho, "r", encoding="utf-8", errors="ignore") as f:
                        conteudo = f.read()
                    encontrados = padrao.findall(conteudo)
                    if encontrados:
                        link = encontrados[-1]
                        print(f"[CLOUDFLARE] Link encontrado: {link}")
                        return link
            except Exception:
                continue

        print(f"[CLOUDFLARE] Tentativa {i+1}/{tentativas} - aguardando {espera}s...")
        time.sleep(espera)

    print("[CLOUDFLARE] Não foi possível obter o link do Cloudflare.")
    return None


def obter_url_publica_env(var_name):
    """Le URL publica configurada por variavel de ambiente para tunnels nomeados."""
    valor = str(os.getenv(var_name, "") or "").strip()
    if not valor:
        return None
    if not valor.startswith("http://") and not valor.startswith("https://"):
        valor = f"https://{valor}"
    return valor


def normalizar_url(url):
    valor = str(url or "").strip()
    if not valor:
        return ""
    if not valor.startswith("http://") and not valor.startswith("https://"):
        valor = f"https://{valor}"
    return valor.rstrip("/")


def obter_url_web_publica():
    return normalizar_url(os.getenv("APP_WEB_FRONTEND_URL", "").strip()) or DEFAULT_WEB_APP_URL.rstrip("/")


def montar_link_web(base_url, page, api_url):
    if not base_url or not api_url:
        return ""
    base = normalizar_url(base_url)
    page_path = str(page or "dashboard.html").lstrip("/")
    query = urllib.parse.urlencode({"api": api_url})
    return f"{base}/{page_path}?{query}"


def url_esta_online(url, timeout=8):
    """Valida se a URL responde no momento da checagem."""
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "homewash-link-check/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            return 200 <= status < 500
    except Exception:
        return False


def garantir_link_cloudflare_ativo(link_inicial, log_path, tentativas=10, espera=6):
    """Tenta garantir um link Cloudflare ativo antes do envio do email."""
    link_atual = link_inicial

    for i in range(tentativas):
        if url_esta_online(link_atual):
            if i > 0:
                print(f"[CLOUDFLARE] Link validado apos nova tentativa: {link_atual}")
            return link_atual

        print(f"[CLOUDFLARE] Link indisponivel ({i+1}/{tentativas}). Tentando recuperar...")
        novo_link = obter_link_cloudflare(log_path, tentativas=3, espera=2)
        if novo_link:
            link_atual = novo_link
        time.sleep(espera)

    if link_atual:
        print(
            "[CLOUDFLARE] Link remoto encontrado, mas ainda nao validado a tempo. "
            "Ele sera enviado mesmo assim para evitar fallback para IP local."
        )
        return link_atual

    print("[CLOUDFLARE] Link nao ficou online a tempo e nenhum link remoto foi encontrado.")
    return None

def obter_ip_local():
    """Obtém o IP local da máquina"""
    try:
        result = subprocess.run(['ipconfig'], capture_output=True, text=True)
        linhas = result.stdout.split('\n')
        for i, linha in enumerate(linhas):
            if '192.168' in linha or '10.0' in linha or '172.16' in linha:
                if 'IPv4' in linhas[i-1]:
                    ip = linha.split(':')[-1].strip()
                    return ip
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def enviar_email(link_pro, ip_local=None, control_link=None, api_link=None, web_base_url=None, ambiente_teste=False):
    """Envia email com link do CRM Pro."""
    if not SEU_EMAIL or not SENHA_APP or not EMAIL_DESTINO:
        print("[ERRO] Variaveis APP_EMAIL_SENDER, APP_EMAIL_PASSWORD ou ALERTA_EMAIL_DESTINO nao configuradas no .env")
        return False

    try:
        mensagem = MIMEMultipart("alternative")
        assunto_base = "🔗 Link do CRM Home Wash Pro"
        mensagem["Subject"] = f"[TESTE] {assunto_base}" if ambiente_teste else assunto_base
        mensagem["From"] = SEU_EMAIL
        mensagem["To"] = EMAIL_DESTINO

        ip_pro = f"http://{ip_local}:8501" if ip_local else ""
        token_controle = get_or_create_token()
        painel_url, restart_url = build_control_urls(control_link, token_controle)
        web_base = normalizar_url(web_base_url) or obter_url_web_publica()
        dashboard_sync_url = montar_link_web(web_base, "dashboard.html", api_link)
        sync_hub_url = montar_link_web(web_base, "sync.html", api_link)
        clients_sync_url = montar_link_web(web_base, "clients.html", api_link)
        schedules_sync_url = montar_link_web(web_base, "agendamentos.html", api_link)
        quotes_sync_url = montar_link_web(web_base, "app.html", api_link)
        card_local = ""
        if ip_local:
            card_local = f"""
            <div style=\"background: linear-gradient(180deg, {BRAND_COLORS['surface_alt']} 0%, {BRAND_COLORS['surface']} 100%); padding: 16px; border-radius: 12px; margin: 14px 0 0; border: 1px solid {BRAND_COLORS['border']};\">
                <p style=\"margin: 0 0 8px; color: {BRAND_COLORS['muted']}; font-size: 13px;\">Acesso local no mesmo Wi-Fi</p>
                <p style=\"margin: 4px 0; color: {BRAND_COLORS['text']}; font-size: 14px;\"><strong>Use este link apenas dentro da rede local:</strong> {ip_pro}</p>
            </div>
            """

        card_controle = ""
        if painel_url and restart_url:
            card_controle = f"""
            <div style=\"background: linear-gradient(180deg, {BRAND_COLORS['surface_alt']} 0%, {BRAND_COLORS['surface']} 100%); padding: 16px; border-radius: 12px; margin: 14px 0 0; border: 1px solid {BRAND_COLORS['border']};\">
                <p style=\"margin: 0 0 8px; color: {BRAND_COLORS['muted']}; font-size: 13px;\">Recuperacao remota</p>
                <p style=\"margin: 0 0 10px; color: {BRAND_COLORS['text']}; font-size: 14px;\">Se o link principal falhar, use o controle remoto abaixo para reiniciar o CRM e receber um link novo.</p>
                <p style=\"margin: 0 0 12px;\">
                    <a href=\"{restart_url}\" style=\"display: inline-block; background-color: {BRAND_COLORS['primary']}; color: white; padding: 10px 18px; border-radius: 8px; text-decoration: none; font-size: 15px; font-weight: bold;\">Reiniciar remotamente</a>
                </p>
                <p style=\"margin: 4px 0; color: {BRAND_COLORS['text']}; font-size: 13px;\"><strong>Painel:</strong> {painel_url}</p>
                <p style=\"margin: 4px 0; color: {BRAND_COLORS['text']}; font-size: 13px;\"><strong>Reiniciar:</strong> {restart_url}</p>
                <p style=\"margin: 8px 0 0; color: {BRAND_COLORS['muted']}; font-size: 12px;\">Nao compartilhe este link. Ele funciona como uma chave privada de controle.</p>
            </div>
            """

        card_sync = ""
        if sync_hub_url:
            api_line = f'<p style="margin: 4px 0; color: {BRAND_COLORS["text"]}; font-size: 13px;"><strong>URL temporaria da API:</strong> {api_link}</p>' if api_link else ''
            card_sync = f"""
            <div style=\"background: linear-gradient(180deg, {BRAND_COLORS['surface_alt']} 0%, {BRAND_COLORS['surface']} 100%); padding: 16px; border-radius: 12px; margin: 14px 0 0; border: 1px solid {BRAND_COLORS['border']};\">
                <p style=\"margin: 0 0 8px; color: {BRAND_COLORS['muted']}; font-size: 13px;\">Sincronizacao do app web</p>
                <p style=\"margin: 0 0 10px; color: {BRAND_COLORS['text']}; font-size: 14px;\">Estes links ja abrem o painel web com a URL temporaria da API preenchida automaticamente. Basta abrir e usar o botao de sincronizar pendentes.</p>
                <p style=\"margin: 0 0 12px;\">
                    <a href=\"{sync_hub_url}\" style=\"display: inline-block; background-color: {BRAND_COLORS['primary']}; color: white; padding: 10px 18px; border-radius: 8px; text-decoration: none; font-size: 15px; font-weight: bold;\">Abrir central de sincronizacao</a>
                </p>
                <p style=\"margin: 4px 0; color: {BRAND_COLORS['text']}; font-size: 13px;\"><strong>Central:</strong> {sync_hub_url}</p>
                <p style=\"margin: 4px 0; color: {BRAND_COLORS['text']}; font-size: 13px;\"><strong>Painel:</strong> {dashboard_sync_url}</p>
                <p style=\"margin: 4px 0; color: {BRAND_COLORS['text']}; font-size: 13px;\"><strong>Clientes:</strong> {clients_sync_url}</p>
                <p style=\"margin: 4px 0; color: {BRAND_COLORS['text']}; font-size: 13px;\"><strong>Agendamentos:</strong> {schedules_sync_url}</p>
                <p style=\"margin: 4px 0; color: {BRAND_COLORS['text']}; font-size: 13px;\"><strong>Orcamentos:</strong> {quotes_sync_url}</p>
                {api_line}
                <p style=\"margin: 8px 0 0; color: {BRAND_COLORS['muted']}; font-size: 12px;\">Fluxo simples para sua esposa: ligar o computador, esperar o email novo chegar, clicar no painel web e depois sincronizar os pendentes.</p>
            </div>
            """

        faixa_teste = ""
        texto_intro = "Olá! Seu CRM Pro está online."
        texto_card = "Link remoto para acesso externo (4G/fora de casa):"
        botao_label = "Abrir CRM Pro"
        if ambiente_teste:
            texto_intro = "Olá! Seu CRM Pro de TESTE está online."
            texto_card = "Link remoto para acesso externo (4G/fora de casa) - TESTE:"
            botao_label = "Abrir CRM Pro TESTE"
            faixa_teste = f"""
            <div style=\"background: linear-gradient(135deg, rgba(255, 196, 0, 0.25) 0%, rgba(60, 39, 0, 0.78) 100%); padding: 12px; border-radius: 10px; border: 1px solid rgba(255, 196, 0, 0.6); margin-bottom: 14px;\">
                <strong style=\"color: #fff2bf;\">AMBIENTE DE TESTE</strong>
                <p style=\"margin: 8px 0 0; color: #ffe7a1; font-size: 13px;\">Este link e somente para testes. Nao usar para operacao real.</p>
            </div>
            """

        html = f"""
        <html>
                    <body style="font-family: Arial, sans-serif; background-color: {BRAND_COLORS['background']}; padding: 20px;">
                        <div style="max-width: 600px; margin: 0 auto; background: linear-gradient(180deg, {BRAND_COLORS['surface']} 0%, {BRAND_COLORS['background_soft']} 100%); padding: 30px; border-radius: 18px; box-shadow: 0 12px 30px rgba(0,0,0,0.35); border: 1px solid {BRAND_COLORS['border']};">
                            <h1 style="color: {BRAND_COLORS['text']}; text-align: center; letter-spacing: 1px;">HOME WASH SOLUTIONS</h1>
                            <hr style="border: none; border-top: 2px solid {BRAND_COLORS['primary']};">
                            {faixa_teste}
                            <p style="font-size: 16px; color: {BRAND_COLORS['text']};">{texto_intro}</p>
                            <div style="background: linear-gradient(180deg, {BRAND_COLORS['surface_alt']} 0%, {BRAND_COLORS['surface']} 100%); padding: 20px; border-radius: 14px; margin: 20px 0; text-align: center; border: 1px solid {BRAND_COLORS['border']};">
                                <p style="margin: 10px 0; color: {BRAND_COLORS['muted']};">{texto_card}</p>
                                <a href="{link_pro}" style="display: inline-block; background-color: {BRAND_COLORS['primary']}; color: white; padding: 12px 30px; border-radius: 8px; text-decoration: none; font-size: 16px; font-weight: bold;">
                                    {botao_label}
                </a>
                                <p style="margin: 15px 0; color: {BRAND_COLORS['text']}; font-size: 14px;">
                                    <strong>Link remoto principal:</strong> {link_pro}
                </p>
                                <p style="margin: 0; color: {BRAND_COLORS['muted']}; font-size: 12px;">
                                    Este e o link para uso externo no celular.
                                </p>
              </div>
                            {card_sync}
                            {card_local}
                            {card_controle}
                            <p style="font-size: 14px; color: {BRAND_COLORS['muted']};"><strong>Hora:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</p>
                            <hr style="border: none; border-top: 1px solid {BRAND_COLORS['border']};">
                            <p style="font-size: 12px; color: {BRAND_COLORS['muted']}; text-align: center;">Email enviado automaticamente pelo sistema Home Wash Solutions</p>
            </div>
          </body>
        </html>
        """
        mensagem.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SEU_EMAIL, SENHA_APP)
            server.sendmail(SEU_EMAIL, EMAIL_DESTINO, mensagem.as_string())
        print("[OK] Email enviado com sucesso!")
        registrar_log_email("sucesso", EMAIL_DESTINO, link_pro)
        return True
    except Exception as e:
        print(f"[ERRO] Erro ao enviar email: {e}")
        registrar_log_email("falha", EMAIL_DESTINO, link_pro, str(e))
        return False

def enviar_whatsapp(link_publico, ambiente_teste=False):
    """Envia link via WhatsApp usando Twilio"""
    if not NUMERO_WHATSAPP:
        print("[WHATSAPP] ALERTA_WHATSAPP_NUMERO nao configurado, pulando envio.")
        return False

    try:
        from twilio.rest import Client
        # ===== CONFIGURE AQUI =====
        # Crie conta grátis em: https://www.twilio.com/try-twilio
        # (dá US$15 de crédito grátis para testes)
        TWILIO_SID   = "SEU_TWILIO_SID"    # Account SID do dashboard Twilio
        TWILIO_TOKEN = "SEU_TWILIO_TOKEN"  # Auth Token do dashboard Twilio
        TWILIO_FROM  = "whatsapp:+14155238886"  # Número Twilio (sandbox)
        # ==========================

        if "SEU_TWILIO_SID" in TWILIO_SID:
            print("[WHATSAPP] Twilio não configurado, pulando envio.")
            return False

        client = Client(TWILIO_SID, TWILIO_TOKEN)
        cabecalho = "🏠 *HOME WASH CRM online!*"
        if ambiente_teste:
            cabecalho = "🧪 *HOME WASH CRM TESTE online!*"
        client.messages.create(
            body=f"{cabecalho}\n\nAcesse de qualquer lugar:\n{link_publico}\n\n⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            from_=TWILIO_FROM,
            to=f"whatsapp:{NUMERO_WHATSAPP}"
        )
        print("[OK] WhatsApp enviado com sucesso!")
        return True
    except ImportError:
        print("[WHATSAPP] Twilio não instalado. Execute: pip install twilio")
        return False
    except Exception as e:
        print(f"[ERRO] Erro ao enviar WhatsApp: {e}")
        return False

def iniciar_crm():
    """Inicia o CRM"""
    try:
        caminho_bat = os.path.join(BASE_DIR, "iniciar_app.bat")
        if not os.path.exists(caminho_bat):
            print(f"[ERRO] Arquivo não encontrado: {caminho_bat}")
            return
        os.system(f'start "" "{caminho_bat}"')
    except Exception as e:
        print(f"[ERRO] Erro ao iniciar CRM: {e}")

if __name__ == "__main__":
    print("[STARTUP] Iniciando HOME WASH CRM...")
    print()

    ip_local = obter_ip_local()
    if ip_local:
        print(f"[OK] IP Local: {ip_local}")

    provider = "cloudflare"
    link = None
    if len(sys.argv) > 1:
        provider = sys.argv[1].strip().lower()

    if provider == "cloudflare":
        log_path = "cloudflare_tunnel.log"
        control_log_path = "control_tunnel.log"
        api_log_path = "api_tunnel.log"
        if len(sys.argv) > 2:
            log_path = sys.argv[2]
        if len(sys.argv) > 3:
            control_log_path = sys.argv[3]
        if len(sys.argv) > 4:
            api_log_path = sys.argv[4]
        public_url_env = obter_url_publica_env("APP_PUBLIC_URL")
        control_url_env = obter_url_publica_env("APP_CONTROL_URL")
        api_public_url_env = obter_url_publica_env("APP_API_PUBLIC_URL")
        web_public_url = obter_url_web_publica()

        link = public_url_env or obter_link_cloudflare(log_path)
        link = garantir_link_cloudflare_ativo(link, log_path)

        if control_url_env:
            control_link = control_url_env
        else:
            control_link = obter_link_cloudflare(control_log_path, tentativas=20, espera=2)
            control_link = garantir_link_cloudflare_ativo(control_link, control_log_path, tentativas=4, espera=3)

        api_link = api_public_url_env or obter_link_cloudflare(api_log_path, tentativas=20, espera=2)
        api_link = garantir_link_cloudflare_ativo(api_link, api_log_path, tentativas=4, espera=3)
    else:
        print("[AVISO] Somente o modo cloudflare e suportado neste projeto.")
        link = None
        control_link = None
        api_link = None
        web_public_url = obter_url_web_publica()

    ambiente_teste = contexto_teste_ativo(log_path if provider == "cloudflare" else "")

    primary_link = link
    if not primary_link and web_public_url:
        primary_link = montar_link_web(web_public_url, "dashboard.html", api_link) or normalizar_url(web_public_url)
    if not primary_link and api_link:
        primary_link = api_link

    if primary_link:
        print()
        print(f"[LINK] {primary_link}")
        if api_link:
            print(f"[API] {api_link}")
        print()
        print("[EMAIL] Enviando email...")
        enviar_email(primary_link, ip_local, control_link, api_link=api_link, web_base_url=web_public_url, ambiente_teste=ambiente_teste)
        print()
        print("[WHATSAPP] Enviando WhatsApp...")
        enviar_whatsapp(primary_link, ambiente_teste=ambiente_teste)
    else:
        print("[AVISO] Link publico não encontrado. Verifique os tunnels do Cloudflare em execução.")
        if ip_local:
            print(f"[AVISO] Usando IP local como fallback: http://{ip_local}:8501")
            enviar_email(f"http://{ip_local}:8501", ip_local)
