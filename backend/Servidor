# app.py
import os
import time
import logging
from datetime import datetime, timezone
from functools import partial
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# Configuration
API_BASE = "https://edusp-api.ip.tv"
DEFAULT_HEADERS = {
    "x-api-platform": "webclient",
    "x-api-realm": "edusp",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)
CORS(app)  # permite CORS para o frontend

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def default_headers(extra=None):
    h = DEFAULT_HEADERS.copy()
    if extra:
        h.update(extra)
    return h

# ------------------ AUTH ------------------ #
@app.route("/auth", methods=["POST"])
def auth():
    """
    POST /auth
    body: { ra, password }
    Faz POST em https://edusp-api.ip.tv/registration/edusp
    Tenta múltiplos formatos de login para evitar erro 400
    Retorna { success, auth_token, nick, debug }
    """
    try:
        data = request.get_json(force=True)
        ra = data.get("ra")
        password = data.get("password")

        if not ra or not password:
            return jsonify({"success": False, "message": "ra e password são obrigatórios"}), 400

        login_url = f"{API_BASE}/registration/edusp"

        # Formatos possíveis de login
        payloads = [
            {"login": ra, "password": password},
            {"ra": ra, "password": password},
            {"username": ra, "password": password}
        ]

        headers = default_headers()

        for p in payloads:
            try:
                resp = requests.post(login_url, json=p, headers=headers, timeout=15)
                # se 200, usamos esse
                if resp.status_code == 200:
                    body = resp.json()
                    token = body.get("auth_token") or (body.get("data") and body["data"].get("token")) or body.get("token")
                    nick = body.get("nick") or (body.get("data") and body["data"].get("nick")) or body.get("user", {}).get("nick", "")

                    if token:
                        return jsonify({"success": True, "auth_token": token, "nick": nick, "debug_payload": p})
                    else:
                        logging.warning("Login retornou sem token: %s", body)
                        return jsonify({"success": False, "message": "Autenticação falhou", "raw": body, "debug_payload": p}), 401
                else:
                    logging.info("Tentativa falhou %s com payload %s", resp.status_code, p)
            except Exception as e_inner:
                logging.exception("Erro ao tentar payload %s: %s", p, e_inner)

        return jsonify({"success": False, "message": "Todos formatos falharam", "debug_payloads": payloads}), 400

    except Exception as e:
        logging.exception("Erro interno em /auth")
        return jsonify({"success": False, "message": str(e)}), 500# ------------------ TASKS ------------------ #
def fetch_rooms(auth_token):
    url = f"{API_BASE}/room/user?list_all=true&with_cards=true"
    headers = default_headers({"x-api-key": auth_token})
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_tasks_for_room(auth_token, publication_target=None, filter_expired=True):
    # Chamamos o endpoint /tms/task/todo com parâmetros. A implementação aceita publication_target se conhecido.
    params = {
        "expired_only": "false",
        "limit": 200,
        "offset": 0,
        "filter_expired": "true" if filter_expired else "false",
        "is_exam": "false",
        "with_answer": "true",
        "is_essay": "false",
        "with_apply_moment": "true"
    }
    if publication_target:
        # o frontend costuma enviar muitos publication_target; aqui enviamos apenas um (se disponível)
        params["publication_target"] = publication_target

    url = f"{API_BASE}/tms/task/todo"
    headers = default_headers({"x-api-key": auth_token})
    r = requests.get(url, headers=headers, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

@app.route("/tasks", methods=["POST"])
def tasks():
    """
    POST /tasks
    body: { auth_token, filter } -> filter: pending | expired
    Retorna { success, count, tasks }
    """
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        filter_type = data.get("filter", "pending")
        if not token:
            return jsonify({"success": False, "message": "auth_token obrigatório"}), 400

        filter_expired = (filter_type == "expired")

        rooms_resp = fetch_rooms(token)
        # rooms_resp pode ter estrutura { data: { rooms: [...] } } ou uma lista direta
        rooms = []
        if isinstance(rooms_resp, dict):
            # tenta diferentes formatos
            rooms = rooms_resp.get("data") or rooms_resp.get("rooms") or rooms_resp.get("rooms_list") or rooms_resp.get("rooms", [])
            # se data for dict e contiver rooms
            if isinstance(rooms, dict) and "rooms" in rooms:
                rooms = rooms["rooms"]
        if not rooms and isinstance(rooms_resp, list):
            rooms = rooms_resp

        tasks_accum = []
        # se não houver rooms, tentamos buscar tasks direto (algumas integrações esperam isso)
        try:
            if rooms:
                for r in rooms:
                    publication_target = None
                    # tenta detectar publication target no objeto da sala
                    if isinstance(r, dict):
                        publication_target = r.get("publication_target") or r.get("id") or r.get("room_id")
                    try:
                        t_resp = fetch_tasks_for_room(token, publication_target=publication_target, filter_expired=filter_expired)
                        # extrai lista de tarefas do retorno
                        if isinstance(t_resp, dict):
                            items = t_resp.get("data") or t_resp.get("items") or t_resp.get("tasks") or t_resp.get("rows") or []
                        else:
                            items = t_resp
                    except Exception as e:
                        logging.warning("Falha ao obter tasks para room %s: %s", publication_target, e)
                        items = []
                    if items:
                        # normalizar tarefas: adicionar token e room para uso posterior
                        for it in items:
                            if isinstance(it, dict):
                                it["token"] = token
                                it["room"] = publication_target
                        tasks_accum.extend(items)
            else:
                # fallback: tenta buscar sem publication_target
                t_resp = fetch_tasks_for_room(token, publication_target=None, filter_expired=filter_expired)
                items = t_resp.get("data") if isinstance(t_resp, dict) else t_resp
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict):
                            it["token"] = token
                    tasks_accum.extend(items)

        except Exception as e:
            logging.exception("Erro agregando tasks")

        return jsonify({"success": True, "count": len(tasks_accum), "tasks": tasks_accum})

    except Exception as e:
        logging.exception("Erro em /tasks")
        return jsonify({"success": False, "message": str(e)}), 500

# ------------------ TRANSFORM JSON FOR SUBMISSION ------------------ #
def remove_html_tags(s):
    import re
    if not s:
        return ""
    # simples limpeza
    clean = re.sub(r"<[^>]+>", "", s)
    return clean

def transform_json_for_submission(task_full):
    """
    Implementa a lógica baseada em transformJson do frontend:
    - order-sentences -> array de frases (sentences[].value)
    - fill-words -> extrai valores nos índices ímpares da phrase
    - text_ai -> envia comentário limpo como {"0": "texto"}
    - fill-letters -> usa options.answer
    - cloud -> usa options.ids
    - multiple_choice -> se houver correct:true escolhe essa; senão primeira
    - outros tipos -> mapear options para objeto com answer (optionId: option.answer ou false)
    Sempre incluir accessed_on e executed_on no objeto final.
    """
    try:
        # espera-se que task_full contenha 'task' e 'answers' do frontend
        if not isinstance(task_full, dict):
            raise ValueError("task_full deve ser dict")

        task = task_full.get("task") or task_full
        answers_in = task_full.get("answers") or {}
        novo = {
            "accessed_on": task_full.get("accessed_on") or now_iso(),
            "executed_on": task_full.get("executed_on") or now_iso(),
            "answers": {}
        }

        # percorre perguntas indicadas em answers_in (mesmo comportamento do frontend)
        for qid_str, qdata in answers_in.items():
            try:
                # qdata geralmente contem question_id
                qid = int(qid_str) if isinstance(qid_str, str) and qid_str.isdigit() else qdata.get("question_id") or qid_str
                # encontra na lista de questões da task
                task_questions = task.get("questions") or []
                task_question = None
                for q in task_questions:
                    if q and (q.get("id") == qid or str(q.get("id")) == str(qid)):
                        task_question = q
                        break
                if not task_question:
                    # pula se não houver info
                    continue

                answer_payload = {
                    "question_id": qdata.get("question_id") or task_question.get("id"),
                    "question_type": task_question.get("type"),
                    "answer": None
                }

                qtype = task_question.get("type")
                options = task_question.get("options", {})

                if qtype == "order-sentences":
                    sentences = options.get("sentences") if isinstance(options, dict) else None
                    if sentences and isinstance(sentences, list):
                        answer_payload["answer"] = [s.get("value") for s in sentences]
                elif qtype == "fill-words":
                    phrase = options.get("phrase") if isinstance(options, dict) else None
                    if phrase and isinstance(phrase, list):
                        # pega índices ímpares
                        vals = [item.get("value") for idx, item in enumerate(phrase) if idx % 2 == 1]
                        answer_payload["answer"] = vals
                elif qtype == "text_ai":
                    comment = remove_html_tags(task_question.get("comment") or task_question.get("value") or "")
                    answer_payload["answer"] = {"0": comment}
                elif qtype == "fill-letters":
                    if "answer" in options:
                        answer_payload["answer"] = options.get("answer")
                elif qtype == "cloud":
                    if "ids" in options and isinstance(options.get("ids"), list):
                        answer_payload["answer"] = options.get("ids")
                elif qtype == "multiple_choice":
                    # tenta escolher opção com correct:true
                    chosen = None
                    if isinstance(options, dict):
                        for opt_k, opt_v in options.items():
                            if isinstance(opt_v, dict) and opt_v.get("correct") is True:
                                chosen = opt_k
                                break
                        if chosen is None:
                            # escolhe primeira opção
                            first_key = next(iter(options.keys()), None)
                            chosen = first_key
                    answer_payload["answer"] = chosen
                else:
                    # default: mapear options -> { optionId: option.answer || False }
                    if isinstance(options, dict):
                        mapped = {}
                        for opt_k, opt_v in options.items():
                            if isinstance(opt_v, dict):
                                mapped[opt_k] = opt_v.get("answer", False)
                            else:
                                mapped[opt_k] = bool(opt_v)
                        answer_payload["answer"] = mapped

                novo["answers"][str(qid)] = answer_payload

            except Exception as inner_e:
                logging.exception("Erro processando questão %s: %s", qid_str, inner_e)
                continue

        return novo
    except Exception as e:
        logging.exception("Erro em transform_json_for_submission")
        raise

# ------------------ TASK PROCESS ------------------ #
@app.route("/task/process", methods=["POST"])
def task_process():
    """
    Recebe { auth_token, task, time_min, time_max, is_draft }
    - faz GET /tms/task/{id}
    - constrói payload usando transform_json_for_submission
    - POST /tms/task/{id}/answer
    """
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        task_obj = data.get("task")
        time_min = int(data.get("time_min", 1))
        time_max = int(data.get("time_max", 3))
        is_draft = bool(data.get("is_draft", False))

        if not token or not task_obj:
            return jsonify({"success": False, "message": "auth_token e task obrigatórios"}), 400

        task_id = task_obj.get("id") or task_obj.get("task_id") or task_obj.get("taskId")
        if not task_id:
            return jsonify({"success": False, "message": "task sem id"}), 400

        # GET detalhes da tarefa
        get_url = f"{API_BASE}/tms/task/{task_id}"
        headers = default_headers({"x-api-key": token})
        r = requests.get(get_url, headers=headers, timeout=25)
        r.raise_for_status()
        task_details = r.json()

        # monta estrutura que transform_json_for_submission espera:
        # { task: <task_details>, answers: <task_obj.get('answers') or {}>, accessed_on, executed_on }
        composed = {
            "task": task_details if isinstance(task_details, dict) else {"questions": task_details},
            "answers": task_obj.get("answers") or {},
            "accessed_on": now_iso(),
            "executed_on": now_iso()
        }

        # transforma
        answers_payload_struct = transform_json_for_submission(composed)

        # payload final enviado ao /tms/task/{id}/answer
        payload = {
            "answers": answers_payload_struct.get("answers", {}),
            "final": not is_draft,
            "status": "draft" if is_draft else "submitted"
        }

        submit_url = f"{API_BASE}/tms/task/{task_id}/answer"
        resp = requests.post(submit_url, headers=default_headers({"x-api-key": token}), json=payload, timeout=30)
        resp.raise_for_status()

        return jsonify({"success": True, "task_id": task_id, "result": resp.json()})

    except requests.HTTPError as e:
        logging.exception("HTTPError em task_process")
        return jsonify({"success": False, "message": f"HTTP {e.response.status_code}", "body": e.response.text}), 500
    except Exception as e:
        logging.exception("Erro em /task/process")
        return jsonify({"success": False, "message": str(e)}), 500

# ------------------ COMPLETE (parallel) ------------------ #
@app.route("/complete", methods=["POST"])
def complete_mult():
    """
    Recebe { auth_token, tasks[], time_min, time_max, is_draft }
    Processa múltiplas tarefas em paralelo usando ThreadPoolExecutor
    """
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        tasks = data.get("tasks", [])
        time_min = int(data.get("time_min", 1))
        time_max = int(data.get("time_max", 3))
        is_draft = bool(data.get("is_draft", False))

        if not token or not isinstance(tasks, list) or len(tasks) == 0:
            return jsonify({"success": False, "message": "auth_token e tasks[] obrigatórios"}), 400

        results = []
        # limitar número de threads razoavelmente
        max_workers = min(8, max(2, len(tasks)))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = []
            for t in tasks:
                payload = {
                    "auth_token": token,
                    "task": t,
                    "time_min": time_min,
                    "time_max": time_max,
                    "is_draft": is_draft
                }
                futures.append(ex.submit(lambda p: requests.post(f"http://127.0.0.1:{os.environ.get('PORT','5000')}/task/process", json=p).json(), payload))

            for f in as_completed(futures):
                try:
                    results.append(f.result())
                except Exception as e:
                    logging.exception("Erro em future complete")
                    results.append({"success": False, "message": str(e)})

        return jsonify({"success": True, "message": f"Processed {len(results)} tasks", "results": results})

    except Exception as e:
        logging.exception("Erro em /complete")
        return jsonify({"success": False, "message": str(e)}), 500

# ------------------ HEALTH ------------------ #
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": now_iso()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
