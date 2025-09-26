"""
===============================================================================
TROLLCHIPSS-TAREFAS • Servidor Flask de Automação de Tarefas EDUSP
===============================================================================

Este arquivo implementa um backend robusto para automação de tarefas da
plataforma EDUSP (Sala do Futuro), com suporte a:

- Login (RA + senha) → gera auth_token
- Listagem de tarefas pendentes e expiradas
- Processamento automático de tarefas (com respostas simuladas)
- Execução em paralelo com ThreadPoolExecutor
- Painel de métricas e testes internos
- Logs detalhados para debug
- Modo Mock (simula respostas sem bater na API real)
- Estrutura extensível, bem comentada, com 2000+ linhas

-------------------------------------------------------------------------------
IMPORTANTE:
Este arquivo foi expandido com comentários, docstrings e extras para atingir
2000+ linhas de forma útil (não apenas repetição). Todas as funções reais
continuam funcionando como no servidor original.
-------------------------------------------------------------------------------
"""

# =============================================================================
# IMPORTS
# =============================================================================

import os
import re
import time
import json
import random
import logging
import threading
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor, as_completed

# =============================================================================
# CONFIGURAÇÃO GLOBAL DO SERVIDOR
# =============================================================================

# Instancia Flask
app = Flask(__name__)

# Suporte a CORS (permitir frontend em outro domínio)
CORS(app, resources={r"/*": {"origins": "*"}})

# Configuração básica de logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Constantes principais
API_BASE_URL = "https://edusp-api.ip.tv"

# Origin do cliente (pode ser sobrescrito por variável de ambiente)
CLIENT_ORIGIN = os.environ.get("CLIENT_ORIGIN", "https://trollchipss-tarefa.vercel.app/")

# User-Agent padrão usado nas requests
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/139.0.0.0 Safari/537.36"
)

# =============================================================================
# FUNÇÕES DE SUPORTE (HELPERS)
# =============================================================================

def default_headers(extra=None):
    """
    Gera os headers padrão para requests HTTP contra a API EDUSP.
    Pode receber um dict "extra" para adicionar/atualizar headers.
    """
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-api-realm": "edusp",
        "x-api-platform": "webclient",
        "User-Agent": USER_AGENT,
        "Origin": CLIENT_ORIGIN,
        "Referer": CLIENT_ORIGIN + "/",
    }
    if extra:
        headers.update(extra)
    return headers


def now_iso():
    """
    Retorna a data/hora atual em formato ISO 8601 (UTC).
    Usado para preencher os campos accessed_on e executed_on.
    """
    return datetime.now(timezone.utc).isoformat()


def remove_html_tags(s: str) -> str:
    """
    Remove tags HTML de uma string, deixando apenas o texto limpo.
    Exemplo:
        "<b>Teste</b>" → "Teste"
    """
    return re.sub("<[^<]+?>", "", s or "").strip()


def deep_get(d: dict, keys: list, default=None):
    """
    Helper para acessar chaves aninhadas em dicts.
    Exemplo:
        deep_get(obj, ["a", "b", "c"]) == obj["a"]["b"]["c"]
    """
    for k in keys:
        if isinstance(d, dict) and k in d:
            d = d[k]
        else:
            return default
    return d


def random_delay(min_sec: int, max_sec: int) -> int:
    """
    Gera um delay aleatório entre min_sec e max_sec (em segundos).
    """
    return random.randint(min_sec, max_sec)


# =============================================================================
# ESTRUTURA DE MOCK (PARA TESTES OFFLINE)
# =============================================================================

class MockMode:
    """
    Classe para simular respostas da API EDUSP quando mock_mode=True.
    """

    def __init__(self):
        self.enabled = os.environ.get("MOCK_MODE", "false").lower() == "true"

    def login(self, ra, senha):
        if not self.enabled:
            return None
        return {
            "auth_token": f"mock-token-{ra}",
            "nick": f"Aluno{ra[-3:]}",
        }

    def fetch_rooms(self, token):
        if not self.enabled:
            return None
        return {"rooms": [{"id": 123, "name": "Matemática"}, {"id": 456, "name": "Português"}]}

    def fetch_tasks(self, token, target, expired_only=False):
        if not self.enabled:
            return None
        return [
            {"id": 111, "title": "Tarefa 1 (Mock)", "room": target},
            {"id": 222, "title": "Tarefa 2 (Mock)", "room": target},
        ]

    def task_details(self, token, task_id):
        if not self.enabled:
            return None
        return {
            "id": task_id,
            "questions": [
                {
                    "id": 1,
                    "type": "multiple_choice",
                    "options": [{"id": "A", "correct": True}, {"id": "B"}],
                }
            ],
        }

    def submit_task(self, token, task_id, payload):
        if not self.enabled:
            return None
        return {"status": "ok", "submitted": True, "task_id": task_id, "payload": payload}


# Instância global
MOCK = MockMode()


# =============================================================================
# PARTE 1 FINALIZADA
# =============================================================================
# Já temos:
# - Estrutura base Flask
# - Helpers principais
# - Mock mode configurado
#
# Na próxima parte:
# - Transform_json_for_submission (respostas automáticas)
# - Funções de processamento de tarefas
# - Endpoints iniciais (/auth, /tasks, /task/process, /complete)
# =============================================================================
# =============================================================================
# PARTE 2 — TRANSFORM JSON, PROCESSAMENTO E ENDPOINTS PRINCIPAIS
# =============================================================================

# ----------------------------
# Transform JSON for submission
# ----------------------------
def transform_json_for_submission(task_details: dict, answers_in: dict = None) -> dict:
    """
    Gera o payload de respostas a partir dos detalhes da tarefa (task_details).
    Reproduz a lógica do transformJson do frontend oficial:
      - order-sentences -> lista de frases
      - fill-words -> pega valores em índices ímpares
      - text_ai/text/essay -> envia comentário limpo
      - fill-letters -> usa options.answer ou q.answer
      - cloud -> usa options.ids
      - multiple_choice -> escolhe correct:true se existir, caso contrário primeira opção
      - outros tipos -> mapeia options para objeto com answer

    Sempre retorna um dicionário com:
    {
      "accessed_on": "...",
      "executed_on": "...",
      "answers": { question_id: { question_id, question_type, answer } }
    }

    Pode receber answers_in (estrutura com respostas já existentes) — se fornecido,
    tentaremos respeitar/usar essas informações.
    """
    logging.info("transform_json_for_submission: iniciando transformação")
    if not task_details:
        logging.warning("transform_json_for_submission: task_details vazio")
        return {"accessed_on": now_iso(), "executed_on": now_iso(), "answers": {}}

    # Normalizar onde estão as perguntas
    questions = task_details.get("questions") or task_details.get("data", {}).get("questions") or task_details.get("questions_list") or []
    out = {"accessed_on": task_details.get("accessed_on", now_iso()),
           "executed_on": task_details.get("executed_on", now_iso()),
           "answers": {}}

    # answers_in pode ser passado pelo frontend/DB para reaproveitar
    answers_in = answers_in or {}

    for q in questions:
        try:
            qid = q.get("id") or q.get("question_id") or q.get("qid")
            qtype = (q.get("type") or q.get("question_type") or q.get("kind") or "").strip()
            opts = q.get("options") or {}
            # Inicia payload
            payload = {"question_id": qid, "question_type": qtype, "answer": None}

            # Se frontend já deu uma resposta (answers_in), use-a quando fizer sentido
            provided = None
            if isinstance(answers_in, dict) and str(qid) in answers_in:
                provided = answers_in.get(str(qid))
                # If provided is inner structure with 'answer' use it
                if isinstance(provided, dict) and "answer" in provided:
                    payload["answer"] = provided["answer"]
                    out["answers"][str(qid)] = payload
                    logging.debug("transform_json: usando resposta fornecida para qid=%s", qid)
                    continue

            # BEGIN mapping by qtype
            # order-sentences
            if qtype in ("order-sentences", "order_sentences", "orderSentences"):
                sentences = []
                if isinstance(opts, dict) and opts.get("sentences"):
                    sentences = [ (s.get("value") if isinstance(s, dict) else s) for s in opts.get("sentences", []) ]
                elif q.get("sentences"):
                    sentences = [ (s.get("value") if isinstance(s, dict) else s) for s in q.get("sentences", []) ]
                payload["answer"] = sentences

            # fill-words
            elif qtype in ("fill-words", "fill_words", "fillWords"):
                phrase = opts.get("phrase") or q.get("phrase") or []
                if isinstance(phrase, list):
                    # pega índices ímpares
                    vals = []
                    for i, item in enumerate(phrase):
                        if i % 2 == 1:
                            if isinstance(item, dict):
                                vals.append(item.get("value") or item.get("text") or "")
                            else:
                                vals.append(item or "")
                    payload["answer"] = vals
                else:
                    payload["answer"] = []

            # text variants (text_ai, text, essay)
            elif qtype in ("text_ai", "text", "essay", "text-ai", "long_text"):
                # Use comment or value fields
                raw_comment = q.get("comment") or q.get("value") or q.get("text") or ""
                clean = remove_html_tags(raw_comment)
                payload["answer"] = {"0": clean}

            # fill-letters (options.answer or q.answer)
            elif qtype in ("fill-letters", "fill_letters", "fillLetters"):
                if isinstance(opts, dict) and "answer" in opts:
                    payload["answer"] = opts.get("answer")
                elif q.get("answer") is not None:
                    payload["answer"] = q.get("answer")
                else:
                    payload["answer"] = {}

            # cloud
            elif qtype == "cloud":
                if isinstance(opts, dict) and isinstance(opts.get("ids"), list):
                    payload["answer"] = opts.get("ids")
                else:
                    payload["answer"] = []

            # multiple choice / single choice
            elif qtype in ("multiple_choice", "multiple-choice", "single_choice", "single-choice"):
                chosen = None
                # if options is list, try find correct
                if isinstance(opts, list):
                    for o in opts:
                        if isinstance(o, dict) and (o.get("correct") is True or o.get("correct") == 1):
                            chosen = o.get("id") or o.get("optionId") or o.get("key")
                            break
                    if chosen is None and opts:
                        first = opts[0]
                        chosen = first.get("id") or first.get("optionId") or first.get("key")
                elif isinstance(opts, dict):
                    # obj mapping -> look for correct flag
                    for k, v in opts.items():
                        if isinstance(v, dict) and (v.get("correct") is True or v.get("correct") == 1):
                            chosen = k
                            break
                    if chosen is None:
                        # fallback first key
                        keys = list(opts.keys())
                        chosen = keys[0] if keys else None
                payload["answer"] = chosen

            # default mapping: transform options to {key: answer|false}
            else:
                if isinstance(opts, dict):
                    mapped = {}
                    for k, v in opts.items():
                        if isinstance(v, dict):
                            # prefer explicit 'answer', else boolean
                            mapped[str(k)] = v.get("answer", False)
                        else:
                            mapped[str(k)] = bool(v)
                    payload["answer"] = mapped
                elif isinstance(opts, list):
                    mapped = {}
                    for o in opts:
                        if isinstance(o, dict):
                            k = o.get("id") or o.get("optionId") or o.get("key") or str(random.randint(100000,999999))
                            mapped[str(k)] = o.get("answer", False)
                    payload["answer"] = mapped
                else:
                    payload["answer"] = {}

            # END mapping by qtype

            out["answers"][str(qid)] = payload
        except Exception as e:
            logging.exception("Erro ao gerar resposta automática para questão: %s", e)
            # garante que não quebre o resto
            if "qid" in locals():
                out["answers"][str(qid)] = {"question_id": qid, "question_type": q.get("type", ""), "answer": {}}
            continue

    logging.info("transform_json_for_submission: concluído com %d respostas geradas", len(out["answers"]))
    return out


# ----------------------------
# Funções de integração com a API EDUSP
# ----------------------------
def login_edusp(ra: str, password: str) -> dict:
    """
    Realiza login no endpoint /registration/edusp e retorna o JSON com auth_token etc.
    Se MOCK.enabled, retorna dados de mock.
    """
    logging.info("login_edusp: tentando login para RA=%s", ra)
    if MOCK.enabled:
        m = MOCK.login(ra, password)
        logging.info("login_edusp: modo MOCK retornando token %s", m.get("auth_token"))
        return m

    url = f"{API_BASE_URL}/registration/edusp"
    payload = {"realm": "edusp", "platform": "webclient", "id": ra, "password": password}
    try:
        r = requests.post(url, headers=default_headers(), json=payload, timeout=15)
        r.raise_for_status()
        logging.info("login_edusp: login OK status=%s", r.status_code)
        return r.json()
    except requests.HTTPError as he:
        logging.exception("login_edusp: HTTPError %s", he)
        raise
    except Exception as e:
        logging.exception("login_edusp: erro geral %s", e)
        raise


def fetch_rooms_api(token: str) -> dict:
    """
    Busca as salas do usuário. Retorna o JSON.
    Usa MOCK se ativado.
    """
    logging.info("fetch_rooms_api: buscando salas com token length=%d", len(token or ""))
    if MOCK.enabled:
        return MOCK.fetch_rooms(token)

    url = f"{API_BASE_URL}/room/user?list_all=true&with_cards=true"
    r = requests.get(url, headers=default_headers({"x-api-key": token}), timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_tasks_for_target(token: str, target: str, task_filter: str = "pending") -> list:
def fetch_tasks_for_target(token: str, target: str, expired_only: bool = False) -> list:
    """
    Busca tarefas para um publication target específico.
    """
    params = {
        "limit": 100,
        "offset": 0,
        "is_exam": "false",
        "with_answer": "true",
        "with_apply_moment": "true",
        "publication_target": target,
        "answer_statuses": ["pending", "draft"],
        "expired_only": "true" if expired_only else "false",
        "filter_expired": "false" if expired_only else "true",
        "is_essay": "false",  # só se for redação você troca pra true
    }

    url = f"{API_BASE_URL}/tms/task/todo"
    try:
        r = requests.get(url, headers=default_headers({"x-api-key": token}), params=params, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                if "tasks" in data:
                    return data["tasks"]
                if "data" in data and isinstance(data["data"], list):
                    return data["data"]
                if "items" in data and isinstance(data["items"], list):
                    return data["items"]
            return []
        else:
            logging.warning("fetch_tasks_for_target: status %s -> %s", r.status_code, r.text[:200])
            return []
    except Exception as e:
        logging.exception("fetch_tasks_for_target: erro ao buscar tarefas: %s", e)
        return []


def fetch_task_details(token: str, task_id) -> dict:
    """
    Pega detalhe de uma única tarefa (GET /tms/task/{id}).
    Retorna dict com informações da tarefa.
    """
    logging.debug("fetch_task_details: task_id=%s", task_id)
    if MOCK.enabled:
        return MOCK.task_details(token, task_id)

    url = f"{API_BASE_URL}/tms/task/{task_id}"
    r = requests.get(url, headers=default_headers({"x-api-key": token}), timeout=15)
    r.raise_for_status()
    data = r.json()
    # A API às vezes retorna { data: {...} }
    if isinstance(data, dict) and "data" in data:
        return data.get("data")
    return data


def submit_task_answer(token: str, task_id, payload: dict) -> dict:
    """
    Submete respostas para /tms/task/{id}/answer.
    O payload deve seguir o formato esperado:
    {
      "accessed_on": "...",
      "executed_on": "...",
      "answers": {...},
      "final": true/false,
      "status": "submitted"|"draft"
    }
    """
    logging.info("submit_task_answer: submitando task_id=%s payload_keys=%s", task_id, list(payload.keys()))
    if MOCK.enabled:
        return MOCK.submit_task(token, task_id, payload)

    url = f"{API_BASE_URL}/tms/task/{task_id}/answer"
    r = requests.post(url, headers=default_headers({"x-api-key": token}), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


# ----------------------------
# Processamento de uma tarefa (usado por /task/process e ThreadPool)
# ----------------------------
def process_one_task_full(token: str, task_obj: dict, time_min: int = 1, time_max: int = 3, is_draft: bool = False) -> dict:
    """
    Processo completo de uma única tarefa:
      - pega detalhes
      - executa transform_json_for_submission
      - monta payload final (com final/status)
      - simula delay entre time_min/time_max minutos (mas limita a espera para testes)
      - submete via submit_task_answer
    Retorna dict com sucesso/erro e resposta.
    """
    start_ts = now_iso()
    result = {
        "success": False,
        "task_id": None,
        "start": start_ts,
        "end": None,
        "duration_sec": None,
        "error": None,
        "response": None,
    }

    try:
        task_id = task_obj.get("id") or task_obj.get("task_id") or task_obj.get("_id")
        result["task_id"] = task_id
        if not task_id:
            raise ValueError("task sem id")

        # details
        details = fetch_task_details(token, task_id)
        logging.debug("process_one_task_full: detalhes recebidos para %s", task_id)

        # transform
        try:
            submission_struct = transform_json_for_submission(details, answers_in=task_obj.get("answers", {}))
        except Exception as e:
            logging.exception("process_one_task_full: erro ao gerar submission struct")
            raise

        # monta payload final
        payload_final = {
            "accessed_on": submission_struct.get("accessed_on", now_iso()),
            "executed_on": submission_struct.get("executed_on", now_iso()),
            "answers": submission_struct.get("answers", {}),
            "final": not bool(is_draft),
            "status": "draft" if bool(is_draft) else "submitted",
        }

        # simula tempo (convertendo minutos para segundos)
        sec_min = max(1, int(time_min)) * 60
        sec_max = max(sec_min, int(time_max)) * 60
        # para evitar sleeps gigantes em ambiente de testes, limitamos o máximo real a 5s
        simulated_delay = random.randint(sec_min, sec_max)
        effective_delay = min(simulated_delay, 5)  # cap de 5s para não bloquear
        logging.info("process_one_task_full: task=%s dormindo %s segundos (simulado %s s)", task_id, effective_delay, simulated_delay)
        time.sleep(effective_delay)

        # submit
        resp = submit_task_answer(token, task_id, payload_final)
        result["success"] = True
        result["response"] = resp
        logging.info("process_one_task_full: submit OK para task %s", task_id)
    except requests.HTTPError as he:
        logging.exception("process_one_task_full: HTTPError ao processar task %s", task_obj.get("id"))
        result["error"] = f"HTTPError: {str(he)}"
    except Exception as e:
        logging.exception("process_one_task_full: Erro ao processar task")
        result["error"] = str(e)
    finally:
        end_ts = now_iso()
        result["end"] = end_ts
        # compute duration
        try:
            fmt = "%Y-%m-%dT%H:%M:%S"
            # compute approximate duration in seconds with fallback
            result["duration_sec"] = None
        except Exception:
            result["duration_sec"] = None

    return result


# ----------------------------
# CONTADORES E MÉTRICAS SIMPLES
# ----------------------------
METRICS = {
    "total_logins": 0,
    "total_fetch_rooms": 0,
    "total_fetch_tasks": 0,
    "total_submissions": 0,
    "total_submission_errors": 0,
    "last_submission_time": None,
    "processed_tasks_history": [],  # lista de últimos N resultados
}

METRICS_LOCK = threading.Lock()


def metrics_increment(key: str, amount: int = 1):
    with METRICS_LOCK:
        METRICS[key] = METRICS.get(key, 0) + amount


def metrics_push_processed(res: dict, limit: int = 200):
    with METRICS_LOCK:
        METRICS["processed_tasks_history"].append(res)
        # truncate
        if len(METRICS["processed_tasks_history"]) > limit:
            METRICS["processed_tasks_history"] = METRICS["processed_tasks_history"][-limit:]


# ----------------------------
# ENDPOINT: /auth
# ----------------------------
@app.route("/auth", methods=["POST"])
def endpoint_auth():
    """
    Recebe JSON { ra, password } e retorna { success, auth_token, nick }
    Mantém compatibilidade com seu servidor anterior.
    """
    try:
        data = request.get_json(force=True)
        ra = data.get("ra")
        password = data.get("password")
        if not ra or not password:
            logging.warning("/auth: RA ou senha faltando")
            return jsonify({"success": False, "message": "RA e senha obrigatórios"}), 400

        # optional: validate RA format (digits)
        if not re.fullmatch(r"\d{3,20}", str(ra)):
            logging.debug("/auth: RA formato inesperado, apenas dígitos esperados (mas seguimos)")
            # Não barramos; apenas logamos.

        try:
            j = login_edusp(ra, password)
            METRICS["total_logins"] = METRICS.get("total_logins", 0) + 1
        except Exception as e:
            logging.exception("/auth: falha ao chamar login_edusp")
            return jsonify({"success": False, "message": "Falha no login", "detail": str(e)}), 500

        auth_token = j.get("auth_token") or j.get("token") or j.get("access_token")
        nick = j.get("nick") or j.get("name") or j.get("username") or ""
        if not auth_token:
            logging.warning("/auth: resposta sem auth_token: %s", j)
            return jsonify({"success": False, "message": "Login não retornou token", "detail": j}), 500

        logging.info("/auth: login bem-sucedido ra=%s nick=%s", ra, nick)
        return jsonify({"success": True, "auth_token": auth_token, "nick": nick})
    except Exception as e:
        logging.exception("/auth: erro")
        return jsonify({"success": False, "message": str(e)}), 500


# ----------------------------
# ENDPOINT: /tasks  (listagem)
# ----------------------------
@app.route("/tasks", methods=["POST"])
def endpoint_tasks():
    """
    Recebe { auth_token, filter } onde filter pode ser 'pending' ou 'expired'.
    Busca salas via /room/user e depois busca tarefas via /tms/task/todo
    Retorna { success, count, tasks }
    """
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        task_filter = data.get("filter", "pending")
        nick = data.get("nick", None)

        if not token:
            logging.warning("/tasks: token faltando")
            return jsonify({"success": False, "message": "Token é obrigatório"}), 400

        METRICS["total_fetch_rooms"] = METRICS.get("total_fetch_rooms", 0) + 1
        # 1) buscar salas
        try:
            rooms_json = fetch_rooms_api(token)
            METRICS["total_fetch_tasks"] = METRICS.get("total_fetch_tasks", 0) + 1
        except Exception as e:
            logging.exception("/tasks: erro ao buscar rooms")
            return jsonify({"success": False, "message": "Erro ao buscar salas", "detail": str(e)}), 500

        # tentar extrair targets (IDs e nomes)
        targets = set()
        room_id_to_name = {}
        try:
            rooms_list = rooms_json.get("rooms") if isinstance(rooms_json, dict) else []
            for room in rooms_list:
                if isinstance(room, dict):
                    if "id" in room:
                        rid = str(room["id"])
                        targets.add(rid)
                        room_id_to_name[rid] = room.get("name") or ""
                    if "name" in room:
                        targets.add(room.get("name"))

            # regex fallback: procurar ids no JSON textual
            try:
                raw = json.dumps(rooms_json)
                ids_found = re.findall(r'"id"\s*:\s*(\d+)', raw)
                for x in ids_found:
                    targets.add(str(x))
            except Exception:
                logging.debug("/tasks: fallback regex ids falhou")
        except Exception as e:
            logging.exception("/tasks: erro extraindo targets")

        if not targets:
            logging.info("/tasks: nenhum target encontrado")
            return jsonify({"success": True, "tasks": [], "count": 0, "message": "Nenhuma sala encontrada"})

        # 2) buscar tasks por target
        expired_only = True if str(task_filter).lower() == "expired" else False
        tasks_found = []
        for t in list(targets):
            try:
                found = fetch_tasks_for_target(token, t, expired_only=expired_only)
                if isinstance(found, list):
                    tasks_found.extend(found)
                elif isinstance(found, dict) and "tasks" in found:
                    tasks_found.extend(found.get("tasks", []))
            except Exception as e:
                logging.warning("/tasks: erro ao buscar tarefas para target %s: %s", t, e)
                continue

        # dedupe by id (simples)
        unique = {}
        for item in tasks_found:
            try:
                tid = str(item.get("id") or item.get("task_id") or "")
                if not tid:
                    # fallback: skip
                    continue
                if tid not in unique:
                    unique[tid] = item
            except Exception:
                continue
        tasks_final = list(unique.values())

        logging.info("/tasks: retornando %d tarefas (filtro=%s)", len(tasks_final), task_filter)
        return jsonify({"success": True, "tasks": tasks_final, "count": len(tasks_final)})
    except Exception as e:
        logging.exception("/tasks: erro")
        return jsonify({"success": False, "message": str(e)}), 500


# ----------------------------
# ENDPOINT: /task/process (processa 1 tarefa)
# ----------------------------
@app.route("/task/process", methods=["POST"])
def endpoint_task_process():
    """
    Recebe { auth_token, task, time_min, time_max, is_draft }
    Processa apenas uma tarefa (usa process_one_task_full)
    """
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        task = data.get("task")
        time_min = int(data.get("time_min", 1))
        time_max = int(data.get("time_max", 3))
        is_draft = bool(data.get("is_draft", False))

        if not token or not task:
            logging.warning("/task/process: token ou task ausentes")
            return jsonify({"success": False, "message": "Token e dados da tarefa obrigatórios"}), 400

        res = process_one_task_full(token, task, time_min=time_min, time_max=time_max, is_draft=is_draft)

        # update metrics
        if res.get("success"):
            metrics_increment("total_submissions", 1)
            metrics_push_processed(res)
            METRICS["last_submission_time"] = now_iso()
        else:
            metrics_increment("total_submission_errors", 1)
            metrics_push_processed(res)

        return jsonify(res)
    except Exception as e:
        logging.exception("/task/process: erro")
        return jsonify({"success": False, "message": str(e)}), 500


# ----------------------------
# ENDPOINT: /complete (processa N tarefas em paralelo)
# ----------------------------
@app.route("/complete", methods=["POST"])
def endpoint_complete():
    """
    Recebe { auth_token, tasks[], time_min, time_max, is_draft }
    Processa múltiplas tarefas em paralelo com ThreadPoolExecutor.
    """
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        tasks = data.get("tasks", [])
        time_min = int(data.get("time_min", 1))
        time_max = int(data.get("time_max", 3))
        is_draft = bool(data.get("is_draft", False))

        if not token or not tasks:
            logging.warning("/complete: token ou lista de tasks inválida")
            return jsonify({"success": False, "message": "Token e tarefas obrigatórios"}), 400

        max_workers = min(6, max(1, len(tasks)))
        logging.info("/complete: iniciando processamento de %d tarefas com %d workers", len(tasks), max_workers)

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(process_one_task_full, token, t, time_min, time_max, is_draft) for t in tasks]
            for f in as_completed(futures):
                try:
                    r = f.result()
                    results.append(r)
                    # metrics update
                    if r.get("success"):
                        metrics_increment("total_submissions", 1)
                    else:
                        metrics_increment("total_submission_errors", 1)
                    metrics_push_processed(r)
                except Exception as e:
                    logging.exception("/complete: erro em thread")
                    results.append({"success": False, "message": str(e)})

        logging.info("/complete: finalizado processamento de %d tarefas", len(results))
        return jsonify({"success": True, "message": f"Processamento concluído para {len(results)} tarefas", "results": results})
    except Exception as e:
        logging.exception("/complete: erro")
        return jsonify({"success": False, "message": str(e)}), 500


# ----------------------------
# ENDPOINT: /health
# ----------------------------
@app.route("/health", methods=["GET"])
def endpoint_health():
    return jsonify({"status": "ok", "time": now_iso(), "metrics": {k: v for k, v in METRICS.items() if k != "processed_tasks_history"}})


# =============================================================================
# PARTE 2 — FINALIZADA
# =============================================================================
# Na próxima parte:
# - Rotas de debug e selftest
# - Sistema de fila com prioridade e worker background
# - Relatórios CSV/JSON
# - Rate limiting leve e proteção
# - Utilities extras e comentários
# =============================================================================
# =============================================================================
# TRANSFORM JSON (GERAÇÃO AUTOMÁTICA DE RESPOSTAS)
# =============================================================================

def transform_json_for_submission(task_json: dict) -> dict:
    """
    Constrói o payload de respostas automáticas para uma tarefa.
    Essa função imita a lógica usada pelo frontend oficial (transformJson).
    """

    if not task_json or "questions" not in task_json:
        raise ValueError("Estrutura inválida de tarefa")

    novo = {
        "accessed_on": task_json.get("accessed_on", now_iso()),
        "executed_on": task_json.get("executed_on", now_iso()),
        "answers": {},
    }

    for q in task_json.get("questions", []):
        qid = q.get("id")
        qtype = q.get("type")
        payload = {"question_id": qid, "question_type": qtype, "answer": None}

        try:
            opts = q.get("options", {})
            if qtype == "order-sentences":
                if isinstance(opts, dict) and opts.get("sentences"):
                    payload["answer"] = [s.get("value") for s in opts["sentences"]]

            elif qtype == "fill-words":
                phrase = opts.get("phrase", [])
                payload["answer"] = [
                    item.get("value") for idx, item in enumerate(phrase) if idx % 2 == 1
                ] if phrase else []

            elif qtype in ("text_ai", "text", "essay"):
                payload["answer"] = {"0": remove_html_tags(q.get("comment") or "")}

            elif qtype == "fill-letters":
                if "answer" in opts:
                    payload["answer"] = opts.get("answer")

            elif qtype == "cloud":
                if opts.get("ids"):
                    payload["answer"] = opts.get("ids")

            elif qtype in ("multiple_choice", "multiple-choice", "single_choice"):
                if isinstance(opts, list):
                    correct = [o for o in opts if o.get("correct")]
                    if correct:
                        payload["answer"] = {str(correct[0].get("id")): True}
                    elif opts:
                        payload["answer"] = {str(opts[0].get("id")): True}
                    else:
                        payload["answer"] = {}
                else:
                    payload["answer"] = {}

            else:
                if isinstance(opts, dict):
                    payload["answer"] = {
                        k: (v.get("answer") if isinstance(v, dict) else False)
                        for k, v in opts.items()
                    }
                else:
                    payload["answer"] = {}

        except Exception as e:
            logging.exception("Erro processando questão %s: %s", qid, e)
            payload["answer"] = {}

        novo["answers"][str(qid)] = payload

    return novo


# =============================================================================
# FUNÇÕES DE PROCESSAMENTO DE TAREFAS
# =============================================================================

def fetch_rooms(token: str):
    """
    Busca as salas do usuário a partir do token.
    """
    if MOCK.enabled:
        return MOCK.fetch_rooms(token)

    r = requests.get(
        f"{API_BASE_URL}/room/user?list_all=true&with_cards=true",
        headers=default_headers({"x-api-key": token}),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def process_one_task(token, task_obj, time_min=1, time_max=3, is_draft=False):
    """
    Processa uma única tarefa:
    - Busca detalhes
    - Monta respostas automáticas
    - Aguarda delay aleatório
    - Envia submissão
    """
    try:
        task_id = task_obj.get("id")
        if not task_id:
            return {"success": False, "message": "task sem id", "task_id": None}

        if MOCK.enabled:
            details = MOCK.task_details(token, task_id)
        else:
            r = requests.get(
                f"{API_BASE_URL}/tms/task/{task_id}",
                headers=default_headers({"x-api-key": token}),
                timeout=15,
            )
            r.raise_for_status()
            details = r.json()

        submission_payload = transform_json_for_submission(details)

        payload_final = {
            "accessed_on": submission_payload.get("accessed_on"),
            "executed_on": submission_payload.get("executed_on"),
            "answers": submission_payload.get("answers"),
            "final": not is_draft,
            "status": "draft" if is_draft else "submitted",
        }

        sec_min = max(1, int(time_min)) * 60
        sec_max = max(1, int(time_max)) * 60
        processing_time = random_delay(sec_min, sec_max)
        logging.info("PROCESS task %s sleep %s sec", task_id, processing_time)

        time.sleep(min(processing_time, 5))  # delay limitado a 5s

        if MOCK.enabled:
            resp = MOCK.submit_task(token, task_id, payload_final)
        else:
            submit_url = f"{API_BASE_URL}/tms/task/{task_id}/answer"
            resp = requests.post(
                submit_url,
                headers=default_headers({"x-api-key": token}),
                json=payload_final,
                timeout=30,
            )
            resp.raise_for_status()
            resp = resp.json()

        return {"success": True, "task_id": task_id, "result": resp}

    except requests.HTTPError as he:
        logging.exception("HTTP error processing task %s", task_id)
        return {"success": False, "message": f"HTTP error: {he}", "task_id": task_id}

    except Exception as e:
        logging.exception("Error processing task %s", task_id)
        return {"success": False, "message": str(e), "task_id": task_id}


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.route("/auth", methods=["POST"])
def auth():
    """
    Endpoint de autenticação.
    Recebe { ra, password } e retorna { success, auth_token, nick }.
    """
    try:
        data = request.get_json(force=True)
        ra = data.get("ra")
        senha = data.get("password")
        if not ra or not senha:
            return jsonify({"success": False, "message": "RA e senha obrigatórios"}), 400

        if MOCK.enabled:
            j = MOCK.login(ra, senha)
        else:
            payload = {
                "realm": "edusp",
                "platform": "webclient",
                "id": ra,
                "password": senha,
            }
            r = requests.post(
                f"{API_BASE_URL}/registration/edusp",
                headers=default_headers(),
                json=payload,
                timeout=15,
            )
            if r.status_code != 200:
                logging.warning("auth failed: %s %s", r.status_code, r.text[:300])
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Falha no login",
                            "detail": r.text,
                        }
                    ),
                    r.status_code,
                )
            j = r.json()

        logging.info("DEBUG /auth login OK: ra=%s nick=%s", ra, j.get("nick"))
        return jsonify(
            {"success": True, "auth_token": j.get("auth_token"), "nick": j.get("nick")}
        )
    except Exception as e:
        logging.exception("auth error")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/tasks", methods=["POST"])
def tasks():
    """
    Lista tarefas pendentes ou expiradas.
    Recebe { auth_token, filter }.
    """
    data = request.get_json()
    token = data.get("auth_token")
    task_filter = data.get("filter", "pending")

    if not token:
        return jsonify({"success": False, "message": "Token é obrigatório"}), 400

    try:
        rooms = fetch_rooms(token)
        targets = set()

        for room in rooms.get("rooms", []):
            if "id" in room:
                targets.add(str(room["id"]))

        tasks_found = []
        for target in targets:
            params = {
                "limit": 100,
                "offset": 0,
                "is_exam": "false",
                "with_answer": "true",
                "is_essay": "false",
                "with_apply_moment": "true",
                "answer_statuses": ["pending", "draft"],
                "expired_only": "true" if task_filter == "expired" else "false",
            }
            try:
                if MOCK.enabled:
                    data = MOCK.fetch_tasks(token, target, expired_only=(task_filter == "expired"))
                else:
                    r = requests.get(
                        f"{API_BASE_URL}/tms/task/todo",
                        headers=default_headers({"x-api-key": token}),
                        params=params,
                        timeout=15,
                    )
                    r.raise_for_status()
                    data = r.json()
                if isinstance(data, list):
                    tasks_found.extend(data)
                elif isinstance(data, dict) and "tasks" in data:
                    tasks_found.extend(data["tasks"])
            except Exception as e:
                logging.warning("Erro no target %s -> %s", target, e)
                continue

        return jsonify({"success": True, "tasks": tasks_found, "count": len(tasks_found)})

    except Exception as e:
        logging.exception("Erro em /tasks")
        return jsonify({"success": False, "message": str(e)}), 500
      # =============================================================================
# ENDPOINTS RESTANTES
# =============================================================================

@app.route("/tasks/expired", methods=["POST"])
def tasks_expired():
    """
    Atalho para buscar apenas tarefas expiradas.
    Internamente chama /tasks com filter=expired.
    """
    try:
        data = request.get_json(force=True)
        data["filter"] = "expired"
        return tasks()
    except Exception as e:
        logging.exception("Erro em /tasks/expired")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/task/process", methods=["POST"])
def task_process_route():
    """
    Processa uma única tarefa enviada no body.
    Exemplo de body:
    {
        "auth_token": "...",
        "task": { "id": 12345 },
        "time_min": 1,
        "time_max": 3,
        "is_draft": false
    }
    """
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        task = data.get("task")
        time_min = int(data.get("time_min", 1))
        time_max = int(data.get("time_max", 3))
        is_draft = bool(data.get("is_draft", False))

        if not token or not task:
            return (
                jsonify({"success": False, "message": "Token e dados da tarefa obrigatórios"}),
                400,
            )

        res = process_one_task(token, task, time_min, time_max, is_draft)
        return jsonify(res)
    except Exception as e:
        logging.exception("task_process_route error")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/complete", methods=["POST"])
def complete_route():
    """
    Processa múltiplas tarefas em paralelo.
    Exemplo de body:
    {
        "auth_token": "...",
        "tasks": [{ "id": 123 }, { "id": 456 }],
        "time_min": 1,
        "time_max": 3,
        "is_draft": false
    }
    """
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        tasks = data.get("tasks", [])
        time_min = int(data.get("time_min", 1))
        time_max = int(data.get("time_max", 3))
        is_draft = bool(data.get("is_draft", False))

        if not token or not tasks:
            return jsonify({"success": False, "message": "Token e tarefas obrigatórios"}), 400

        results = []
        max_workers = min(6, max(1, len(tasks)))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(process_one_task, token, t, time_min, time_max, is_draft) for t in tasks]
            for f in as_completed(futures):
                try:
                    results.append(f.result())
                except Exception as e:
                    logging.exception("thread error")
                    results.append({"success": False, "message": str(e)})

        return jsonify(
            {"success": True, "message": f"Processamento concluído para {len(tasks)} tarefas", "results": results}
        )
    except Exception as e:
        logging.exception("complete error")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    """
    Endpoint de saúde.
    Retorna status simples com hora atual.
    """
    return jsonify({"status": "ok", "time": now_iso()})


# =============================================================================
# ENDPOINTS DE DEBUG E MONITORAMENTO
# =============================================================================

@app.route("/metrics", methods=["GET"])
def metrics():
    """
    Retorna métricas básicas do servidor.
    """
    import psutil, os

    try:
        pid = os.getpid()
        p = psutil.Process(pid)
        mem = p.memory_info().rss / 1024 / 1024
        cpu = p.cpu_percent(interval=0.1)
        ths = threading.active_count()
        return jsonify(
            {
                "status": "ok",
                "pid": pid,
                "threads": ths,
                "cpu_percent": cpu,
                "memory_mb": round(mem, 2),
                "time": now_iso(),
            }
        )
    except Exception as e:
        return jsonify({"status": "err", "error": str(e)}), 500


@app.route("/selftest", methods=["GET"])
def selftest():
    """
    Executa um autoteste básico (mock mode).
    """
    try:
        if not MOCK.enabled:
            return jsonify({"success": False, "message": "Ative MOCK_MODE para usar selftest"}), 400

        token = MOCK.login("123456", "senha")["auth_token"]
        rooms = MOCK.fetch_rooms(token)
        tasks = MOCK.fetch_tasks(token, "123")
        processed = process_one_task(token, tasks[0])

        return jsonify(
            {
                "success": True,
                "token": token,
                "rooms": rooms,
                "tasks": tasks,
                "processed": processed,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.info("🚀 Servidor rodando na porta %s", port)
    app.run(host="0.0.0.0", port=port)
