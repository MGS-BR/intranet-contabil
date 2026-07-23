document.addEventListener("DOMContentLoaded", function () {
    const overlay = document.getElementById("trello-overlay");
    const btnAbrir = document.getElementById("abrir-cartao");
    const btnFechar = document.getElementById("fechar-modal");
    const btnSalvar = document.getElementById("btn-salvar-cartao");
    const status = document.getElementById("trello-status");

    const inputTitulo = document.getElementById("card-titulo");
    const selectLista = document.getElementById("card-lista");
    const inputDescricao = document.getElementById("card-descricao");
    const inputData = document.getElementById("card-data");

    const listaChecklist = document.getElementById("checklist-itens");
    const inputNovoItem = document.getElementById("novo-item-checklist");
    const btnAddItem = document.getElementById("btn-add-item");
    const btnLimparChecklist = document.getElementById("btn-limpar-checklist");
    const percentualEl = document.getElementById("checklist-percentual");
    const progressoFill = document.getElementById("checklist-progresso-fill");

    let checklistItens = [];
    let labelsSelecionadas = new Set();
    let membrosSelecionados = new Set();

    function abrirModal() {
        overlay.classList.add("aberto");
        inputTitulo.focus();
    }

    function fecharModal() {
        overlay.classList.remove("aberto");
        limparFormulario();
    }

    function limparFormulario() {
        inputTitulo.value = "";
        if (selectLista) {
            selectLista.value = "";
            selectLista.classList.remove("trello-erro");
        }
        inputDescricao.value = "";
        inputData.value = "";
        checklistItens = [];
        labelsSelecionadas.clear();
        membrosSelecionados.clear();
        renderChecklist();
        document.querySelectorAll(".trello-label-chip.selecionado").forEach(el => el.classList.remove("selecionado"));
        document.querySelectorAll(".trello-membro-chip.selecionado").forEach(el => el.classList.remove("selecionado"));
        status.textContent = "";
        status.className = "trello-status";
    }

    btnAbrir && btnAbrir.addEventListener("click", abrirModal);
    btnFechar && btnFechar.addEventListener("click", fecharModal);
    overlay && overlay.addEventListener("click", function (e) {
        if (e.target === overlay) fecharModal();
    });

    // ---------- Botões de ação rápida (Etiquetas / Checklist / Membros) ----------
    document.querySelectorAll(".trello-acao-btn[data-scroll]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            const alvo = document.getElementById(btn.dataset.scroll);
            if (alvo) alvo.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    });

    // ---------- Botão "Editar" (foca no campo relacionado) ----------
    document.querySelectorAll(".trello-btn-editar[data-focus]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            const alvo = document.getElementById(btn.dataset.focus);
            if (alvo) {
                alvo.scrollIntoView({ behavior: "smooth", block: "center" });
                alvo.focus();
            }
        });
    });

    // ---------- Labels ----------
    document.querySelectorAll(".trello-label-chip").forEach(function (chip) {
        chip.addEventListener("click", function () {
            const id = chip.dataset.id;
            if (labelsSelecionadas.has(id)) {
                labelsSelecionadas.delete(id);
                chip.classList.remove("selecionado");
            } else {
                labelsSelecionadas.add(id);
                chip.classList.add("selecionado");
            }
        });
    });

    // ---------- Membros ----------
    document.querySelectorAll(".trello-membro-chip").forEach(function (chip) {
        chip.addEventListener("click", function () {
            const id = chip.dataset.id;
            if (membrosSelecionados.has(id)) {
                membrosSelecionados.delete(id);
                chip.classList.remove("selecionado");
            } else {
                membrosSelecionados.add(id);
                chip.classList.add("selecionado");
            }
        });
    });

    // ---------- Checklist ----------
    function atualizarProgresso() {
        const total = checklistItens.length;
        const concluidos = checklistItens.filter(i => i.concluido).length;
        const pct = total === 0 ? 0 : Math.round((concluidos / total) * 100);
        if (percentualEl) percentualEl.textContent = `${pct}%`;
        if (progressoFill) progressoFill.style.width = `${pct}%`;
    }

    function renderChecklist() {
        listaChecklist.innerHTML = "";
        checklistItens.forEach(function (item, idx) {
            const linha = document.createElement("div");
            linha.className = "trello-checklist-item" + (item.concluido ? " concluido" : "");
            linha.innerHTML = `
                <input type="checkbox" data-idx="${idx}" ${item.concluido ? "checked" : ""}>
                <span></span>
                <button type="button" class="remover-item" data-idx="${idx}">✕</button>
            `;
            linha.querySelector("span").textContent = item.texto;
            listaChecklist.appendChild(linha);
        });

        listaChecklist.querySelectorAll('input[type="checkbox"]').forEach(function (chk) {
            chk.addEventListener("change", function () {
                const idx = parseInt(chk.dataset.idx, 10);
                checklistItens[idx].concluido = chk.checked;
                renderChecklist();
            });
        });

        listaChecklist.querySelectorAll(".remover-item").forEach(function (btn) {
            btn.addEventListener("click", function () {
                const idx = parseInt(btn.dataset.idx, 10);
                checklistItens.splice(idx, 1);
                renderChecklist();
            });
        });

        atualizarProgresso();
    }

    function adicionarItemChecklist() {
        const valor = inputNovoItem.value.trim();
        if (!valor) return;
        checklistItens.push({ texto: valor, concluido: false });
        inputNovoItem.value = "";
        renderChecklist();
        inputNovoItem.focus();
    }

    btnAddItem && btnAddItem.addEventListener("click", adicionarItemChecklist);
    inputNovoItem && inputNovoItem.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
            e.preventDefault();
            adicionarItemChecklist();
        }
    });

    btnLimparChecklist && btnLimparChecklist.addEventListener("click", function () {
        checklistItens = [];
        renderChecklist();
    });

    // ---------- Salvar / criar cartão de verdade no Trello ----------
    function mostrarLoading(ativo) {
        const overlayLoading = document.getElementById("loading-overlay");
        if (!overlayLoading) return;
        overlayLoading.classList.toggle("active", ativo);
    }

    btnSalvar && btnSalvar.addEventListener("click", async function () {
        const titulo = inputTitulo.value.trim();
        if (!titulo) {
            status.textContent = "Digite um título para o cartão.";
            status.className = "trello-status erro";
            inputTitulo.focus();
            return;
        }

        const idLista = selectLista ? selectLista.value : "";
        if (!idLista) {
            status.textContent = "Selecione em qual lista o cartão deve ser criado.";
            status.className = "trello-status erro";
            selectLista && selectLista.classList.add("trello-erro");
            selectLista && selectLista.focus();
            return;
        }
        selectLista && selectLista.classList.remove("trello-erro");

        const payload = {
            titulo: titulo,
            idList: idLista,
            descricao: inputDescricao.value,
            dataEntrega: inputData.value || null,
            labelIds: Array.from(labelsSelecionadas),
            memberIds: Array.from(membrosSelecionados),
            checklist: checklistItens,
        };

        btnSalvar.disabled = true;
        mostrarLoading(true);
        status.textContent = "Criando cartão...";
        status.className = "trello-status";

        try {
            const resp = await fetch("/utilidades/trello/criar", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();

            if (data.ok) {
                status.innerHTML = `Cartão criado com sucesso! <a href="${data.url}" target="_blank" rel="noopener">Abrir no Trello</a>`;
                status.className = "trello-status ok";
                setTimeout(fecharModal, 2500);
            } else {
                status.textContent = data.erro || "Não foi possível criar o cartão.";
                status.className = "trello-status erro";
            }
        } catch (err) {
            status.textContent = "Erro de conexão ao criar o cartão.";
            status.className = "trello-status erro";
        } finally {
            btnSalvar.disabled = false;
            mostrarLoading(false);
        }
    });
});