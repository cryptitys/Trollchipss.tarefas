# app.py
import os
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# Config
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
CORS(app)

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
    try:
        data = request.get_json(force=True)
        ra = data.get("ra")
        password = data.get("password")
        if not ra or not password:
            return jsonify({"success": False, "message": "ra e password são obrigatórios"}), 400

        login_url = f"{API_BASE}/registration/edusp"
        payloads = [
            {"login": ra, "password": password},
            {"ra": ra, "password": password},
            {"username": ra, "password": password}
        ]
        headers = default_headers()

        for p in payloads:
            try:
                resp = requests.post(login_url, json=p, headers=headers, timeout=15)
                if resp.status_code == 200:
                    body = resp.json()
                    token = body.get("auth_token") or (body.get("data") and body["data"].get("token"))
                    nick = body.get("nick") or (body.get("data") and body["data"].get("nick", ""))
                    if token:
                        return jsonify({"success": True, "auth_token": token, "nick": nick, "debug_payload": p})
            except Exception as e_inner:
                logging.warning("Erro payload %s: %s", p, e_inner)

        return jsonify({"success": False, "message": "Todos formatos falharam"}), 400
    except Exception as e:
        logging.exception("Erro /auth")
        return jsonify({"success": False, "message": str(e)}), 500

# ------------------ TASKS ------------------ #
def fetch_rooms(auth_token):
    url = f"{API_BASE}/room/user?list_all=true&with_cards=true"
    headers = default_headers({"x-api-key": auth_token})
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_tasks_for_room(auth_token, publication_target=None, filter_expired=True):
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
        params["publication_target"] = publication_target

    url = f"{API_BASE}/tms/task/todo"
    headers = default_headers({"x-api-key": auth_token})
    r = requests.get(url, headers=headers, params=params, timeout=25)
    r.raise_for_status()
    return r.json()

@app.route("/tasks", methods=["POST"])
def tasks():
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        filter_type = data.get("filter", "pending")
        if not token:
            return jsonify({"success": False, "message": "auth_token obrigatório"}), 400

        filter_expired = (filter_type == "expired")
        rooms_resp = fetch_rooms(token)

        rooms = []
        if isinstance(rooms_resp, dict):
            rooms = rooms_resp.get("data") or rooms_resp.get("rooms") or []
            if isinstance(rooms, dict) and "rooms" in rooms:
                rooms = rooms["rooms"]
        elif isinstance(rooms_resp, list):
            rooms = rooms_resp

        tasks_accum = []
        if rooms:
            for r in rooms:
                pub_target = r.get("publication_target") or r.get("id") or r.get("room_id")
                try:
                    t_resp = fetch_tasks_for_room(token, publication_target=pub_target, filter_expired=filter_expired)
                    items = t_resp.get("data") if isinstance(t_resp, dict) else t_resp
                    if items:
                        for it in items:
                            if isinstance(it, dict):
                                it["token"] = token
                                it["room"] = pub_target
                        tasks_accum.extend(items)
                except Exception as e:
                    logging.warning("Falha tasks room %s: %s", pub_target, e)
        else:
            t_resp = fetch_tasks_for_room(token, publication_target=None, filter_expired=filter_expired)
            items = t_resp.get("data") if isinstance(t_resp, dict) else t_resp
            if items:
                for it in items:
                    if isinstance(it, dict):
                        it["token"] = token
                tasks_accum.extend(items)

        return jsonify({"success": True, "count": len(tasks_accum), "tasks": tasks_accum})

    except Exception as e:
        logging.exception("Erro /tasks")
        return jsonify({"success": False, "message": str(e)}), 500

# ------------------ TRANSFORM JSON ------------------ #
def remove_html_tags(s):
    import re
    return re.sub(r"<[^>]+>", "", s) if s else ""

def transform_json_for_submission(task_full):
    try:
        task = task_full.get("task") or task_full
        answers_in = task_full.get("answers") or {}
        novo = {"accessed_on": task_full.get("accessed_on") or now_iso(),
                "executed_on": task_full.get("executed_on") or now_iso(),
                "answers": {}}

        for qid_str, qdata in answers_in.items():
            qid = int(qid_str) if isinstance(qid_str, str) and qid_str.isdigit() else qdata.get("question_id") or qid_str
            task_questions = task.get("questions") or []
            task_question = next((q for q in task_questions if q and (q.get("id") == qid or str(q.get("id")) == str(qid))), None)
            if not task_question:
                continue

            answer_payload = {"question_id": task_question.get("id"), "question_type": task_question.get("type"), "answer": None}
            qtype = task_question.get("type")
            options = task_question.get("options", {})

            if qtype == "order-sentences":
                sentences = options.get("sentences") if isinstance(options, dict) else None
                answer_payload["answer"] = [s.get("value") for s in sentences] if sentences else []
            elif qtype == "fill-words":
                phrase = options.get("phrase") if isinstance(options, dict) else None
                if phrase:
                    answer_payload["answer"] = [item.get("value") for idx, item in enumerate(phrase) if idx % 2 == 1]
            elif qtype == "text_ai":
                answer_payload["answer"] = {"0": remove_html_tags(task_question.get("comment") or task_question.get("value") or "")}
            elif qtype == "fill-letters":
                if "answer" in options:
                    answer_payload["answer"] = options.get("answer")
            elif qtype == "cloud":
                answer_payload["answer"] = options.get("ids") if options.get("ids") else []
            elif qtype == "multiple_choice":
                chosen = next((k for k,v in options.items() if isinstance(v, dict) and v.get("correct")), next(iter(options.keys()), None))
                answer_payload["answer"] = chosen
            else:
                if isinstance(options, dict):
                    answer_payload["answer"] = {k: (v.get("answer") if isinstance(v, dict) else bool(v)) for k,v in options.items()}

            novo["answers"][str(qid)] = answer_payload
        return novo
    except Exception as e:
        logging.exception("Erro transform_json_for_submission")
        raise

# ------------------ TASK PROCESS ------------------ #
@app.route("/task/process", methods=["POST"])
def task_process():
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

        get_url = f"{API_BASE}/tms/task/{task_id}"
        headers = default_headers({"x-api-key": token})
        r = requests.get(get_url, headers=headers, timeout=25)
        r.raise_for_status()
        task_details = r.json()

        composed = {"task": task_details if isinstance(task_details, dict) else {"questions": task_details},
                    "answers": task_obj.get("answers") or {},
                    "accessed_on": now_iso(), "executed_on": now_iso()}

        answers_payload_struct = transform_json_for_submission(composed)
        payload = {"answers": answers_payload_struct.get("answers", {}), "final": not is_draft, "status": "draft" if is_draft else "submitted"}
        submit_url = f"{API_BASE}/tms/task/{task_id}/answer"
        resp = requests.post(submit_url, headers=default_headers({"x-api-key": token}), json=payload, timeout=30)
        resp.raise_for_status()
        return jsonify({"success": True, "task_id": task_id, "result": resp.json()})
    except Exception as e:
        logging.exception("Erro /task/process")
        return jsonify({"success": False, "message": str(e)}), 500

# ------------------ COMPLETE (parallel) ------------------ #
@app.route("/complete", methods=["POST"])
def complete_mult():
    try:
        data = request.get_json(force=True)
        token = data.get("auth_token")
        tasks = data.get("tasks", [])
        time_min = int(data.get("time_min", 1))
        time_max = int(data.get("time_max", 3))
        is_draft = bool(data.get("is_draft", False))
        if not token or not tasks:
            return jsonify({"success": False, "message": "auth_token e tasks[] obrigatórios"}), 400

        results = []
        max_workers = min(8, max(2, len(tasks)))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(lambda t: task_process_internal(token, t, time_min, time_max, is_draft), t) for t in tasks]
            for f in as_completed(futures):
                results.append(f.result())

        return jsonify({"success": True, "message": f"Processed {len(results)} tasks", "results": results})
    except Exception as e:
        logging.exception("Erro /complete")
        return jsonify({"success": False, "message": str(e)}), 500

def task_process_internal(token, task_obj, time_min, time_max, is_draft):
    # chamada direta sem HTTP interno
    data = {"auth_token": token, "task": task_obj, "time_min": time_min, "time_max": time_max, "is_draft": is_draft}
    with app.test_request_context(json=data):
        return task_process().get_json()

# ------------------ HEALTH ------------------ #
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": now_iso()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
