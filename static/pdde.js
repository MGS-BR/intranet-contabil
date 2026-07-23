document.addEventListener("DOMContentLoaded", function () {
    // ---------- DROPZONE / UPLOAD DE PDFS ----------
    const dropzone = document.getElementById("dropzone");
    const inputArquivos = document.getElementById("input-arquivos");
    const listaArquivos = document.getElementById("lista-arquivos");
    const statusDocumentos = document.getElementById("status-documentos");
    const templateStatus = document.getElementById("template-status-documento");

    if (dropzone) {
        dropzone.addEventListener("click", () => inputArquivos.click());

        dropzone.addEventListener("dragover", (e) => {
            e.preventDefault();
            dropzone.classList.add("ativo");
        });

        dropzone.addEventListener("dragleave", () => dropzone.classList.remove("ativo"));

        dropzone.addEventListener("drop", (e) => {
            e.preventDefault();
            dropzone.classList.remove("ativo");
            inputArquivos.files = e.dataTransfer.files;
            atualizarListaArquivos();
        });

        inputArquivos.addEventListener("change", atualizarListaArquivos);
    }

    function criarStatusDocumento(nome, indice) {
        const clone = templateStatus.content.cloneNode(true);
        clone.querySelector(".nome-arquivo").textContent = nome;

        const inputs = clone.querySelectorAll("input");
        inputs[0].name = `conta_caixa_${indice}`;
        inputs[1].name = `conta_receita_${indice}`;

        statusDocumentos.appendChild(clone);
    }

    function atualizarListaArquivos() {
        const arquivos = Array.from(inputArquivos.files);
        statusDocumentos.innerHTML = "";

        arquivos.forEach((arquivo, indice) => criarStatusDocumento(arquivo.name, indice));

        listaArquivos.innerHTML = arquivos.length
            ? "<b>Selecionados:</b><br>" + arquivos.map(a => "📄 " + a.name).join("<br>")
            : "Nenhum arquivo foi selecionado.";
    }

    // ---------- LANÇAMENTOS MANUAIS ----------
    const lancamentosContainer = document.getElementById("lancamentos-manuais");
    const templateLancamento = document.getElementById("template-lancamento");
    const btnAdd = document.getElementById("btn-add-lancamento");
    const btnClear = document.getElementById("btn-clear-lancamentos");

    function adicionarLancamento() {
        const clone = templateLancamento.content.cloneNode(true);
        clone.querySelector(".btn-remover-lancamento").addEventListener("click", function (e) {
            e.target.closest(".manual-item").remove();
        });
        lancamentosContainer.appendChild(clone);
    }

    if (btnAdd) btnAdd.addEventListener("click", adicionarLancamento);
    if (btnClear) btnClear.addEventListener("click", () => lancamentosContainer.innerHTML = "");
});