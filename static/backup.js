document.addEventListener("DOMContentLoaded", function () {
	const btn = document.getElementById("btn-executar-backup");
	const statusValor = document.getElementById("statusValor");
	const ultimoBackupValor = document.getElementById("ultimoBackupValor");
	const ultimoBackupArquivo = document.getElementById("ultimoBackupArquivo");
	const logBackup = document.getElementById("logBackup");
	const erroBox = document.getElementById("erro-backup");

	let polling = null;

	function formatarData(timestamp) {
		if (!timestamp) return "sem registro";
		const dt = new Date(timestamp * 1000);
		return dt.toLocaleDateString("pt-BR") + " " + dt.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
	}

	async function consultarStatus() {
		try {
			const res = await fetch("/servidor/backup/status", { cache: "no-store" });
			const data = await res.json();

			logBackup.textContent = data.log;
			logBackup.scrollTop = logBackup.scrollHeight;

			ultimoBackupValor.textContent = formatarData(data.ultimo_backup_timestamp);
			ultimoBackupArquivo.textContent = data.ultimo_backup_arquivo || "";

			if (data.rodando) {
				statusValor.textContent = "Executando...";
				btn.disabled = true;
				btn.textContent = "Backup em execução...";
			} else {
				statusValor.textContent = "Ocioso";
				btn.disabled = false;
				btn.textContent = "Executar backup agora";

				if (polling) {
					clearInterval(polling);
					polling = null;
				}

				if (data.ultimo_erro) {
					erroBox.textContent = data.ultimo_erro;
					erroBox.style.display = "block";
				} else {
					erroBox.style.display = "none";
				}
			}
		} catch (err) {
			console.error("Erro ao consultar status do backup:", err);
		}
	}

	btn.addEventListener("click", async function () {
		btn.disabled = true;
		btn.textContent = "Iniciando...";
		erroBox.style.display = "none";

		try {
			const res = await fetch("/servidor/backup/executar", { method: "POST" });
			const data = await res.json();

			if (!data.ok) {
				erroBox.textContent = data.erro;
				erroBox.style.display = "block";
				btn.disabled = false;
				btn.textContent = "Executar backup agora";
				return;
			}

			// inicia o polling a cada 2s até o backup terminar
			polling = setInterval(consultarStatus, 2000);
			consultarStatus();

		} catch (err) {
			erroBox.textContent = "Erro ao iniciar o backup.";
			erroBox.style.display = "block";
			btn.disabled = false;
			btn.textContent = "Executar backup agora";
		}
	});

	// se a página carregar com o backup já rodando (ex: outro usuário iniciou), continua o polling
	if (btn.disabled) {
		polling = setInterval(consultarStatus, 2000);
	}
});