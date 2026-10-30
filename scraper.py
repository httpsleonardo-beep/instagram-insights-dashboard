"""Coleta somente leituras produzidas pela interface autenticada do Instagram."""
from __future__ import annotations

import sys
import shutil
import json
import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote, urlsplit
from zoneinfo import ZoneInfo

from numeric import parse_number
from settings import AppError

LOGGER = logging.getLogger("insights")
TZ = ZoneInfo("America/Sao_Paulo")
NODE = "data.user.business_manager.account_insights_node"
OPERATIONS = {
    "PolarisAccountInsightFollowersActiveTimesChartQuery",
    "PolarisAccountInsightsFollowersQuery",
    "PolarisAccountInsightsViewsQuery",
    "PolarisAccountInsightsInteractionsQuery",
    "PolarisAccountInsightsProfileQuery",
    "PolarisAccountInsightsViewsByContentDataQuery",
    "PolarisAccountInsightsInteractionsByContentDataQuery",
}
METRICS = {
    "reach": ("Contas alcançadas", "reach_current_period", "Contas únicas alcançadas no período, conforme reach_current_period. Diferente de visualizadores."),
    "engaged_accounts": ("Contas engajadas", "engaged_accounts", "Contas únicas com engajamento no período; não é a quantidade de interações."),
    "followers": ("Total de seguidores", "", "Total atual no momento da coleta, não novos seguidores no período."),
    "interactions": ("Interações", "total_interactions", "Total de interações informado pelo Instagram."),
    "views": ("Visualizações no Instagram", "views_current_period", "Visualizações no Instagram no período; uma conta pode gerar várias visualizações."),
    "viewers": ("Visualizadores", "viewers_current_period", "Contagem de visualizadores retornada pelo Instagram, distinta de alcance."),
    "facebook_views": ("Visualizações no Facebook", "fb_views_current_period", "Visualizações no Facebook de conteúdo compartilhado entre plataformas."),
    "combined_views": ("Visualizações combinadas", "ccp_views_current_period", "Total combinado fornecido pelo Instagram para Instagram e Facebook."),
}
# Enum observado no módulo PolarisAccountInsightsUtils da interface em 02/10/2026.
# Estes códigos são MEDIA_PRODUCT_TYPE do painel, não o media_type de uma publicação.
CONTENT_TYPES = {"1": "Ao vivo", "2": "Posts", "16": "Reels", "3": "Stories", "5": "Vídeos"}


def path_value(data, path):
    current = data
    for key in path.split("."):
        if isinstance(current, list) and key.isdigit():
            current = current[int(key)] if int(key) < len(current) else None
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def single_value(node):
    """Só totais explícitos; nunca soma alcance diário ou escolhe uma linha arbitrária."""
    if not isinstance(node, dict):
        return None
    rows = node.get("results")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("dimension_values"):
        return None
    return parse_number(rows[0].get("value"))


def period_matches(start, end, days=30):
    return isinstance(start, (int, float)) and isinstance(end, (int, float)) and abs((end - start + 1) - days * 86400) <= 1


def thirty_days(start, end):
    return period_matches(start, end, 30)


def normalize_records(records, account_id, period_label, dom_values=None, dom_range_confirmed=False, days=30):
    relevant = [r for r in records if r["account_id"] == account_id and r["operation"] in OPERATIONS]
    periods = {(r["start"], r["end"]) for r in relevant if period_matches(r.get("start"), r.get("end"), days)}
    if len(periods) > 1:
        raise AppError("period_conflict", "O Instagram retornou períodos diferentes. Atualize novamente para evitar misturar os dados.")
    if not periods and not (dom_range_confirmed and any(v is not None for v in (dom_values or {}).values())):
        raise AppError("period_unverified", f"Não foi possível confirmar as datas dos últimos {days} dias. Nenhum total foi publicado.")
    start, end = next(iter(periods)) if periods else (None, None)
    # Descarta respostas em cache de outra seleção de período.
    relevant = [r for r in relevant if r["operation"].endswith(("FollowersQuery", "ActiveTimesChartQuery")) or (periods and (r.get("start"), r.get("end")) == (start, end))]
    metrics = {key: {"label": meta[0], "value": None, "definition": meta[2], "source": None} for key, meta in METRICS.items()}
    content = {code: {"type": name, "code": code, "views": None, "interactions": None, "sources": {}} for code, name in CONTENT_TYPES.items()}
    warnings, raw = [], []
    if not periods:
        warnings.append(f"Período de {days} dias confirmado pelo seletor da interface; as datas exatas não foram retornadas. Dados por conteúdo indisponíveis.")
    for record in relevant:
        operation, payload = record["operation"], record["payload"]
        raw.append(record)
        node = path_value(payload, NODE) or {}
        for key, (_, field, _) in METRICS.items():
            value = parse_number(path_value(payload, "data.userInfo.follower_count")) if key == "followers" else single_value(node.get(field))
            if value is not None:
                metrics[key].update(value=value, source={"method": "network", "operation": operation, "path": "data.userInfo.follower_count" if key == "followers" else f"{NODE}.{field}.results.0.value"})
        for field, metric in (("views_by_media_and_follow_types", "views"), ("total_interactions_by_media_type", "interactions")):
            rows = (node.get(field) or {}).get("results")
            if not isinstance(rows, list):
                continue
            groups, seen, invalid = {}, set(), set()
            for row in rows:
                dims = row.get("dimension_values", [])
                if len(dims) != (2 if metric == "views" else 1):
                    warnings.append(f"Dimensão desconhecida em {field}; linha omitida.")
                    continue
                code = str(dims[0])
                dimension_key = tuple(map(str, dims))
                value = parse_number(row.get("value"))
                if dimension_key in seen or value is None:
                    invalid.add(code)
                    continue
                seen.add(dimension_key)
                groups[code] = groups.get(code, 0) + value
            for code, value in groups.items():
                row = content.setdefault(code, {"type": f"Outros (código {code})", "code": code, "views": None, "interactions": None, "sources": {}})
                if code in invalid:
                    warnings.append(f"Dados incompletos ou duplicados para {row['type']}; {metric} indisponível.")
                    continue
                row[metric] = value
                if metric == "views":
                    row["views_followers"] = next((parse_number(r.get("value")) for r in rows if list(map(str, r.get("dimension_values", []))) == [code, "1"]), None)
                    row["views_nonfollowers"] = next((parse_number(r.get("value")) for r in rows if list(map(str, r.get("dimension_values", []))) == [code, "2"]), None)
                row["sources"][metric] = {"method": "network", "operation": operation, "path": f"{NODE}.{field}.results", "aggregation": "Soma das dimensões disjuntas de seguidores por tipo" if metric == "views" else "Valor por MEDIA_PRODUCT_TYPE"}
    for key, value in (dom_values or {}).items():
        if key in metrics and metrics[key]["value"] is None and value is not None:
            metrics[key].update(value=value, source={"method": "DOM", "label": METRICS[key][0], "approximate": True})
            warnings.append(f"{METRICS[key][0]} veio da interface e pode estar arredondado.")
    for key in ("reach", "engaged_accounts", "followers"):
        if metrics[key]["value"] is None:
            warnings.append(f"{METRICS[key][0]} indisponível nesta coleta.")
    for metric in ("views", "interactions"):
        values = [r[metric] for r in content.values() if r[metric] is not None]
        total = metrics[metric]["value"]
        if values and total is not None and sum(values) != total:
            warnings.append(f"A soma por conteúdo para {metrics[metric]['label'].lower()} difere do total da conta; os valores da fonte foram preservados.")
    if any(code not in CONTENT_TYPES for code in content):
        warnings.append("O Instagram retornou tipos sem nome conhecido. Eles aparecem como Outros, com o código original.")
    if not any(v["value"] is not None for v in metrics.values()):
        raise AppError("schema_changed", "A estrutura dos Insights mudou ou nenhum dado está disponível. Confira o painel no Edge.")
    complete = all(metrics[k]["value"] is not None for k in ("reach", "engaged_accounts", "followers")) and all(content[k][m] is not None for k in ("2", "16", "3") for m in ("views", "interactions"))
    activity = {}
    for record in relevant:
        for row in path_value(record['payload'], NODE + '.hourly_30_day.results') or []:
            dims = row.get('dimension_values', [])
            if len(dims) == 2:
                activity[tuple(dims)] = {'day': dims[0], 'hours': dims[1], 'value': parse_number(row.get('value'))}
    return {
        "schema_version": 2,
        "selection": {"scope": "account", "days": days},
        "collected_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "account": {"id": account_id},
        "period": {"days": days, "start": datetime.fromtimestamp(start, TZ).isoformat() if start is not None else None, "end": datetime.fromtimestamp(end, TZ).isoformat() if end is not None else None, "start_epoch": start, "end_epoch": end, "timezone": str(TZ), "verified": True, "dates_verified": bool(periods), "label": period_label, "evidence": "currentPeriodStart/currentPeriodEnd das requisições observadas" if periods else f"Seletor visível Últimos {days} dias; datas exatas indisponíveis"},
        "status": "complete" if complete else "partial",
        "metrics": metrics,
        "content": sorted(content.values(), key=lambda r: {"2": 0, "16": 1, "3": 2, "1": 3, "5": 4}.get(r["code"], 5)),
        "warnings": list(dict.fromkeys(warnings)),
        "sources": raw,
        "activity": list(activity.values()),
    }


def check_login(page):
    path = urlsplit(page.url).path
    if any(part in path for part in ("/challenge", "/checkpoint", "/accounts/suspended", "/accounts/disabled")):
        raise AppError("verification_required", "O Instagram pediu uma verificação da conta. Conclua-a no Edge e atualize o sessionid.")
    if "/accounts/login" in path or page.locator('input[name="username"]').count():
        raise AppError("session_expired", "Sessão inválida ou expirada. Atualize o sessionid em Secrets do Streamlit e clique em Atualizar dados.")


def read_dom(page, selectors):
    values = {}
    labels = {"reach": ["Contas alcançadas", "Accounts reached"], "engaged_accounts": ["Contas com engajamento", "Contas engajadas", "Accounts engaged"], "followers": ["Total de seguidores", "Total followers"]}
    for key, names in labels.items():
        if selectors.get(key):
            element = page.locator(selectors[key])
            if element.count() == 1:
                values[key] = parse_number(element.inner_text())
            continue
        for name in names:
            label = page.get_by_text(name, exact=True)
            if label.count() != 1:
                continue
            # Aceita somente um número sem percentuais no menor bloco do rótulo.
            for depth in (1, 2, 3):
                text = label.locator("xpath=" + "/".join([".."] * depth)).inner_text()
                if len(text) > 120 or "%" in text:
                    break
                candidates = [parse_number(line) for line in text.splitlines()]
                candidates = [x for x in candidates if x is not None]
                if len(candidates) == 1:
                    values[key] = candidates[0]
                    break
    return values


def browser_options(cfg):
    if sys.platform == "win32":
        return {"channel": "msedge", "headless": True}
    executable = shutil.which("chromium") or shutil.which("chromium-browser")
    if not executable:
        raise AppError("browser_unavailable", "Chromium não está instalado no servidor. Confira packages.txt na raiz do repositório e reinicie o aplicativo.")
    return {"executable_path": executable, "headless": True, "args": ["--disable-dev-shm-usage"]}



def collect(cfg, progress=lambda message: None):
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout, Error as PlaywrightError

    days = cfg.get("selection", {}).get("days", 30)
    secret = cfg["sessionid"]
    if not secret:
        raise AppError("session_missing", "Preencha sessionid em INSTAGRAM_SESSIONID nos Secrets do Streamlit.")
    account_id = unquote(secret).split(":", 1)[0]
    if not account_id.isdigit():
        raise AppError("session_invalid", "O sessionid não tem o formato esperado. Copie somente o valor do cookie sessionid.")
    records, response_errors = [], set()

    def on_response(response):
        try:
            url = urlsplit(response.url)
            if url.hostname not in {"www.instagram.com", "instagram.com", "i.instagram.com"} or url.path not in {"/api/graphql", "/graphql/query"}:
                return
            params = parse_qs(response.request.post_data or url.query)
            operation = params.get("fb_api_req_friendly_name", [""])[0]
            if operation not in OPERATIONS:
                return
            if response.status in (401, 403, 429):
                response_errors.add(response.status)
                return
            if response.status != 200:
                return
            variables = json.loads(params.get("variables", ["{}"]) [0])
            viewer = str((variables.get("query_params") or {}).get("id") or variables.get("userID") or "")
            if viewer != account_id:
                return
            payload = response.json()
            # Somente campos de Insights. Nunca salva cabeçalhos, cookies ou tokens.
            clean = {"data": {}}
            info = path_value(payload, "data.userInfo")
            if info is not None:
                clean["data"]["userInfo"] = {"follower_count": info.get("follower_count")}
            node = path_value(payload, NODE)
            if node is not None:
                allowed = {meta[1] for meta in METRICS.values()} | {"views_by_media_and_follow_types", "total_interactions_by_media_type", "hourly_30_day"}
                safe_node = {}
                for key, value in node.items():
                    if key in allowed and isinstance(value, dict):
                        safe_node[key] = {"results": [{k: row[k] for k in ("value", "dimension_values") if k in row} for row in (value.get("results") or []) if isinstance(row, dict)]}
                clean["data"]["user"] = {"business_manager": {"account_insights_node": safe_node}}
            records.append({"operation": operation, "account_id": viewer, "start": variables.get("currentPeriodStart"), "end": variables.get("currentPeriodEnd"), "endpoint": "https://www.instagram.com" + url.path, "payload": clean})
        except (ValueError, TypeError, KeyError, AttributeError, PlaywrightError):
            LOGGER.debug("Uma resposta de Insights não pôde ser interpretada.")

    progress("Abrindo o Edge e verificando a sessão…")
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(**browser_options(cfg))
            except PlaywrightError:
                raise AppError("browser_unavailable", "Não foi possível iniciar o navegador. Verifique se o Chromium está instalado pelo packages.txt.") from None
            try:
                context = browser.new_context(locale="pt-BR", timezone_id=str(TZ), viewport={"width": 1440, "height": 1000})
                context.add_cookies([{"name": "sessionid", "value": secret, "domain": ".instagram.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"}])
                page = context.new_page()
                page.set_default_timeout(cfg["timeout_seconds"] * 1000)
                page.on("response", on_response)
                page.goto(cfg["start_url"], wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                check_login(page)
                welcome = page.get_by_text("Entendi", exact=True).filter(visible=True)
                if welcome.count():
                    welcome.click()
                progress("Abrindo Insights da conta…")
                if "/accounts/insights" not in urlsplit(page.url).path:
                    try:
                        page.get_by_text("Insights", exact=True).click(timeout=8000)
                        page.get_by_text(re.compile(r"^(Conta|Account)$"), exact=True).filter(visible=True).click(timeout=5000)
                    except PlaywrightTimeout:
                        page.goto("https://www.instagram.com/accounts/insights/", wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                check_login(page)
                if "/accounts/insights" not in urlsplit(page.url).path:
                    raise AppError("insights_unavailable", "O painel de Insights não abriu. Verifique se a conta é profissional e tem acesso aos Insights na versão web.")
                try:
                    page.get_by_text(re.compile(r"^(Últimos \d+ dias|Last \d+ days)$")).first.wait_for(state="visible")
                except PlaywrightTimeout:
                    check_login(page)
                    raise AppError("period_unverified", "O painel carregou sem um seletor de período reconhecido. Verifique os Insights no Edge.") from None
                period = page.get_by_text(re.compile(rf"^(Últimos {days} dias|Last {days} days)$"))
                if not period.count():
                    dropdown = page.get_by_text(re.compile(r"^(Últimos \d+ dias|Last \d+ days)$"))
                    if dropdown.count():
                        dropdown.first.click()
                        page.get_by_text(re.compile(rf"^(Últimos {days} dias|Last {days} days)$")).last.click()
                    else:
                        raise AppError("period_unverified", f"Não foi possível localizar o seletor dos últimos {days} dias no painel.")
                progress("Coletando os totais e os resultados por conteúdo…")
                deadline = time.monotonic() + cfg["timeout_seconds"]
                required = OPERATIONS - {"PolarisAccountInsightsProfileQuery", "PolarisAccountInsightFollowersActiveTimesChartQuery"}
                while time.monotonic() < deadline:
                    names = {r["operation"] for r in records if r["operation"].endswith("FollowersQuery") or period_matches(r.get("start"), r.get("end"), days)}
                    if required <= names:
                        break
                    check_login(page)
                    page.wait_for_timeout(500)
                page.wait_for_timeout(cfg["settle_seconds"] * 1000)
                check_login(page)
                if 429 in response_errors:
                    raise AppError("rate_limited", "O Instagram limitou as consultas. Aguarde alguns minutos antes de atualizar novamente.")
                if response_errors & {401, 403}:
                    raise AppError("session_expired", "O Instagram recusou a sessão ou o acesso aos Insights. Atualize o sessionid e confirme o acesso à conta.")
                dom = read_dom(page, cfg["dom_selectors"])
                result = normalize_records(records, account_id, f"Últimos {days} dias", dom, dom_range_confirmed=period.count() == 1 and period.is_visible(), days=days)
                # Nome da conta a partir do link de perfil já presente na navegação.
                links = page.locator('a[href]').evaluate_all('(els) => els.map(e => e.getAttribute("href"))')
                excluded = {"reels", "explore", "direct", "accounts", "legal", "popular", "web", "ad_tools"}
                profiles = [href.strip("/") for href in links if re.fullmatch(r"/[A-Za-z0-9_.]+/", href or "") and href.strip("/") not in excluded]
                if len(set(profiles)) == 1:
                    result["account"]["username"] = profiles[0]
                return result
            finally:
                browser.close()
    except AppError:
        raise
    except PlaywrightTimeout:
        raise AppError("timeout", "O Instagram demorou a responder. Verifique a conexão e tente atualizar novamente.") from None
    except PlaywrightError:
        raise AppError("browser_error", "A conexão com o Instagram foi interrompida. Confira a rede e tente novamente.") from None
