let MostrarSenha = document.getElementById("VerSenha");
let Senha = document.getElementById("senha");
const userAgent = navigator.userAgent;
let trava = false;

MostrarSenha.addEventListener("click", () => {
    Senha.type = Senha.type === "password" ? "text" : "password";
});

function Atividade(Titulo, Atividade) {
    const div = document.createElement("div");
    div.className = "Notificacao";

    const h1 = document.createElement("h1");
    h1.textContent = Titulo;

    const p = document.createElement("p");
    p.textContent = Atividade;

    div.appendChild(h1);
    div.appendChild(p);

    const article = document.getElementById("TamanhoN");
    article.appendChild(div);

    setTimeout(() => {
        div.style.animation = "sumir 1.5s ease";
        div.addEventListener("animationstart", () => {
          setTimeout(() => {
              const interval = setInterval(() => {
                  const currentScroll = article.scrollTop;
                  const targetScroll = article.scrollHeight;
                  const distance = targetScroll - currentScroll;
                  
                  article.scrollTop += distance * 0.4;
      
                  if (distance < 1) clearInterval(interval);
              }, 16);
          }, 200);
      });

        div.addEventListener("animationend", () => div.remove());
    }, 2500);
}

document.getElementById('Enviar').addEventListener('submit', (e) => {
  e.preventDefault();
  
  if(trava) return;
  trava = true;

  const options = {
    LOGIN_URL: 'https://sedintegracoes.educacao.sp.gov.br/credenciais/api/LoginCompletoToken',
    LOGIN_DATA: {
      user: document.getElementById('ra').value, 
      senha: document.getElementById('senha').value,
    },
  };

  async function makeRequest(url, method='GET', headers={}, body=null) {
    const opts = { method, headers: { 'User-Agent': userAgent, 'Content-Type': 'application/json', ...headers } };
    if (body) opts.body = JSON.stringify(body);

    const res = await fetch(url, opts);
    if (!res.ok) throw new Error(`HTTP ${method} ${url} => ${res.status}`);
    return res.json();
  }

  async function loginRequest() {
    const headers = { Accept: 'application/json, text/plain, */*', 'User-Agent': userAgent, 'Ocp-Apim-Subscription-Key': '2b03c1db3884488795f79c37c069381a' };
    try {
      const data = await makeRequest(options.LOGIN_URL, 'POST', headers, options.LOGIN_DATA);
      Atividade('SALA-DO-FUTURO','Logado com sucesso!');
      checkTasks(data.token);
    } catch(err) {
      Atividade('SALA-DO-FUTURO','❌ Não foi possível logar!');
      trava = false;
    }
  }

  async function checkTasks(token) {
    try {
      const userData = await makeRequest('https://edusp-api.ip.tv/registration/edusp/token', 'POST', { 'x-api-realm':'edusp','x-api-platform':'webclient','User-Agent':userAgent }, { token });
      const authToken = userData.auth_token;
      const roomsData = await makeRequest('https://edusp-api.ip.tv/room/user?list_all=true&with_cards=true', 'GET', { 'User-Agent':userAgent, 'x-api-key':authToken });

      if (!roomsData.rooms || roomsData.rooms.length===0) {
        Atividade('SALA-DO-FUTURO','⚠️ Nenhuma sala encontrada');
        trava = false;
        return;
      }

      const roomName = roomsData.rooms[0].name;
      const taskTypes = [
        { label:'Normal', url:`https://edusp-api.ip.tv/tms/task/todo?expired_only=false&filter_expired=true&with_answer=true&publication_target=${roomName}&answer_statuses=pending&with_apply_moment=false` },
        { label:'Expirada', url:`https://edusp-api.ip.tv/tms/task/todo?expired_only=true&filter_expired=false&with_answer=true&publication_target=${roomName}&answer_statuses=pending&with_apply_moment=true` },
        { label:'Rascunho', url:`https://edusp-api.ip.tv/tms/task/todo?expired_only=false&filter_expired=true&with_answer=true&publication_target=${roomName}&answer_statuses=draft&with_apply_moment=true` },
      ];

      for (let type of taskTypes) {
        try {
          const tasks = await makeRequest(type.url, 'GET', { 'User-Agent':userAgent,'x-api-key':authToken });
          if (tasks && tasks.length>0) {
            Atividade('TAREFAS',`✅ Tipo ${type.label} encontrado: ${tasks.length} tarefas`);
            for (let t of tasks) {
              try {
                // Tenta acessar detalhes da tarefa
                await makeRequest(`https://edusp-api.ip.tv/tms/task/${t.id}/apply?preview_mode=false`, 'GET', { 'User-Agent':userAgent, 'x-api-key':authToken });
                Atividade('TAREFA OK',`📝 Task ID ${t.id} - "${t.title}" acessível`);
              } catch(errTask) {
                Atividade('TAREFA BLOQUEADA',`❌ Task ID ${t.id} - "${t.title}" retornou 403 ou não acessível`);
              }
            }
          } else {
            Atividade('TAREFAS',`⚠️ Nenhuma tarefa do tipo ${type.label} encontrada`);
          }
        } catch(errType) {
          Atividade('TAREFAS',`❌ Erro ao buscar tarefas tipo ${type.label}: ${errType.message}`);
        }
      }
    } catch(err) {
      Atividade('SALA-DO-FUTURO','❌ Erro geral ao buscar salas ou token: '+err.message);
    }
    trava = false;
  }

  loginRequest();
});
