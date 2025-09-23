// index.js - versão máxima
const API_BASE_URL = "https://edusp-api.ip.tv";
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/117 Safari/537.36";

// ===== LOGIN =====
async function login(ra, senha) {
    const loginData = {
        realm: "edusp",
        platform: "webclient",
        id: ra,
        password: senha
    };

    const response = await fetch(`${API_BASE_URL}/registration/edusp`, {
        method: "POST",
        headers: {
            "Accept": "application/json",
            "x-api-realm": "edusp",
            "x-api-platform": "webclient",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json"
        },
        body: JSON.stringify(loginData)
    });

    if (!response.ok) throw new Error(`Erro no login: ${response.status}`);
    const data = await response.json();
    return data.token;
}

// ===== BUSCAR TAREFAS =====
async function fetchTasks(token) {
    const response = await fetch(`${API_BASE_URL}/tms/task?with_cards=true`, {
        headers: {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "x-api-key": token
        }
    });

    if (!response.ok) throw new Error(`Erro ao buscar tarefas: ${response.status}`);
    return await response.json();
}

// ===== TODOS PAYLOADS E MÉTODOS =====
async function sendTaskAnswerAll(taskId, token) {
    const payloads = [
        { answers: [], finished: true },
        { response: [], finished: true },
        { content: [], finished: true },
        { solution: [], finished: true },
        { data: [], finished: true },
        { values: [], finished: true },
        { result: [], finished: true },
        { resposta: [], finished: true },
        { respostas: [], finished: true },
        { completed: true },
        { done: true },
        { status: "finished" },
        { status: "done" },
        { status: "completed" },
        { submit: true },
        { entregues: [] }
    ];

    const methods = ["PUT", "POST", "PATCH", "DELETE"];

    for (let i = 0; i < payloads.length; i++) {
        const payload = payloads[i];
        for (let m = 0; m < methods.length; m++) {
            const method = methods[m];
            console.log(`Tentando método ${method}, payload ${i + 1}/${payloads.length}:`, payload);

            try {
                const response = await fetch(`${API_BASE_URL}/tms/task/${taskId}`, {
                    method,
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": USER_AGENT,
                        "x-api-key": token
                    },
                    body: method !== "DELETE" ? JSON.stringify(payload) : null
                });

                if (response.ok) {
                    const data = await response.json().catch(() => ({}));
                    console.log(`✅ Sucesso com método ${method}, payload:`, payload);
                    console.log("Resposta do servidor:", data);
                    return data;
                } else {
                    console.warn(`❌ Falhou (${response.status}) com método ${method}, payload:`, payload);
                }
            } catch (err) {
                console.error(`Erro com método ${method}, payload:`, payload, err.message);
            }
        }
    }

    console.log("Nenhum payload/método funcionou 😢");
}

// ===== TESTE =====
(async () => {
    try {
        const ra = "SEU_RA_AQUI";
        const senha = "SUA_SENHA_AQUI";

        const token = await login(ra, senha);
        console.log("Token obtido:", token);

        const tasks = await fetchTasks(token);
        console.log("Tarefas encontradas:", tasks);

        if (tasks && tasks.length > 0) {
            const taskId = tasks[0].id; // pega a primeira tarefa para teste
            console.log("Testando envio para tarefa:", taskId);

            await sendTaskAnswerAll(taskId, token);
        }
    } catch (e) {
        console.error("Erro geral:", e.message);
    }
})();
