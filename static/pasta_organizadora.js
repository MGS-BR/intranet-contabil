document.addEventListener("DOMContentLoaded", () => {
    const dropzones = document.querySelectorAll(".organizadora-dropzone");

    function enviarArquivos(secao, arquivos) {
        if (!arquivos || arquivos.length === 0) return;

        const formData = new FormData();
        for (const arquivo of arquivos) {
            formData.append("arquivos", arquivo);
        }

        fetch(`/utilidades/pasta-organizadora/upload/${secao}`, {
            method: "POST",
            body: formData,
        })
            .then((resp) => resp.json())
            .then((dados) => {
                if (dados.ok) {
                    atualizarStatus();
                } else {
                    alert(dados.erro || "Falha ao enviar arquivo.");
                }
            })
            .catch(() => alert("Falha ao enviar arquivo."));
    }

    dropzones.forEach((zona) => {
        const secao = zona.dataset.secao;
        const input = zona.querySelector(".organizadora-input");

        zona.addEventListener("click", () => input.click());

        input.addEventListener("change", () => {
            enviarArquivos(secao, input.files);
            input.value = "";
        });

        zona.addEventListener("dragover", (ev) => {
            ev.preventDefault();
            zona.classList.add("ativo");
        });

        zona.addEventListener("dragleave", () => {
            zona.classList.remove("ativo");
        });

        zona.addEventListener("drop", (ev) => {
            ev.preventDefault();
            zona.classList.remove("ativo");
            enviarArquivos(secao, ev.dataTransfer.files);
        });
    });

    function atualizarListaDom(secao, arquivos) {
        const lista = document.getElementById(`lista-${secao}`);
        if (!lista) return;

        lista.innerHTML = "";
        if (!arquivos || arquivos.length === 0) {
            const li = document.createElement("li");
            li.className = "vazio";
            li.textContent = "Nenhum arquivo";
            lista.appendChild(li);
            return;
        }
        arquivos.forEach((nome) => {
            const li = document.createElement("li");
            li.textContent = nome;
            lista.appendChild(li);
        });
    }

    function atualizarStatus() {
        fetch("/utilidades/pasta-organizadora/status")
            .then((resp) => resp.json())
            .then((dados) => {
                document.getElementById("info-ultima").textContent = dados.ultima_organizacao || "—";
                document.getElementById("info-proxima").textContent = dados.proxima_organizacao || "—";

                Object.entries(dados.arquivos_por_secao || {}).forEach(([secao, arquivos]) => {
                    atualizarListaDom(secao, arquivos);
                });
            })
            .catch(() => {});
    }

    const btnOrganizar = document.getElementById("btn-organizar-agora");
    const statusBox = document.getElementById("organizadora-status");

    btnOrganizar.addEventListener("click", () => {
        btnOrganizar.disabled = true;
        statusBox.textContent = "Organizando...";
        statusBox.className = "organizadora-status";

        fetch("/utilidades/pasta-organizadora/organizar", { method: "POST" })
            .then((resp) => resp.json())
            .then((dados) => {
                if (dados.ok) {
                    statusBox.textContent = `Organização concluída: ${dados.movimentacoes} movimentação(ões).`;
                    statusBox.classList.add("ok");
                } else {
                    statusBox.textContent = "Falha ao organizar.";
                    statusBox.classList.add("erro");
                }
                atualizarStatus();
            })
            .catch(() => {
                statusBox.textContent = "Falha ao organizar.";
                statusBox.classList.add("erro");
            })
            .finally(() => {
                btnOrganizar.disabled = false;
            });
    });

    // Atualiza status (última/próxima organização + listas) a cada 30s,
    // já que a auto-organização roda em background a cada 20 min.
    setInterval(atualizarStatus, 30000);
});