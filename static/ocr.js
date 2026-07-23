document.addEventListener("DOMContentLoaded", function () {

    // ---------- DROPZONE / UPLOAD DE PDFS ----------
    const dropzone = document.getElementById("dropzone");
    const inputArquivos = document.getElementById("input-arquivos");
    const listaArquivos = document.getElementById("lista-arquivos");

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

    function atualizarListaArquivos() {
        const arquivos = Array.from(inputArquivos.files);
        statusDocumentos.innerHTML = "";

        arquivos.forEach((arquivo, indice) => criarStatusDocumento(arquivo.name, indice));

        listaArquivos.innerHTML = arquivos.length
            ? "<b>Selecionados:</b><br>" + arquivos.map(a => "📄 " + a.name).join("<br>")
            : "Nenhum arquivo foi selecionado.";
    }

	
});