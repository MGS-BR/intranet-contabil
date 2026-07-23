document.addEventListener("DOMContentLoaded", function () {
	const categorias = document.querySelectorAll(".nav-category");

	function fecharTodas(excetoEsta) {
		categorias.forEach(function (cat) {
			if (cat !== excetoEsta) {
				cat.classList.remove("open");
				const titulo = cat.querySelector(".category-title");
				if (titulo) titulo.setAttribute("aria-expanded", "false");
			}
		});
	}

	categorias.forEach(function (categoria) {
		const titulo = categoria.querySelector(".category-title");

		titulo.addEventListener("click", function (e) {
			e.stopPropagation();
			const jaAberta = categoria.classList.contains("open");

			fecharTodas(categoria);

			categoria.classList.toggle("open", !jaAberta);
			titulo.setAttribute("aria-expanded", String(!jaAberta));
		});

		// acessibilidade: abrir com Enter/Espaço via teclado
		titulo.addEventListener("keydown", function (e) {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				titulo.click();
			}
		});
	});

	// fecha ao clicar fora de qualquer categoria
	document.addEventListener("click", function () {
		fecharTodas(null);
	});

	// fecha ao pressionar ESC
	document.addEventListener("keydown", function (e) {
		if (e.key === "Escape") {
			fecharTodas(null);
		}
	});
	
	const overlay = document.getElementById("loading-overlay");

	function mostrarLoading() {
		overlay.classList.add("active");
	}

	function esconderLoading() {
		overlay.classList.remove("active");
	}

	// Forms que baixam arquivo (respostas com send_file) precisam de tratamento via fetch
	const formsDownload = document.querySelectorAll("form.form-download");

	formsDownload.forEach(function (form) {
		form.addEventListener("submit", async function (e) {
			e.preventDefault();
			mostrarLoading();

			try {
				const formData = new FormData(form);
				const resposta = await fetch(form.action, {
					method: "POST",
					body: formData,
				});

				if (!resposta.ok) {
					// Se o Flask redirecionou por erro (flash + redirect), a resposta ainda é 200
					// mas pode ser uma página HTML em vez do arquivo. Recarregamos pra mostrar o flash.
					window.location.reload();
					return;
				}

				const contentType = resposta.headers.get("Content-Type") || "";

				// Se voltou HTML em vez de um arquivo, é porque houve erro/flash no backend
				if (contentType.includes("text/html")) {
					const html = await resposta.text();
					document.open();
					document.write(html);
					document.close();
					return;
				}

				const blob = await resposta.blob();
				const nomeArquivo = extrairNomeArquivo(resposta.headers.get("Content-Disposition"));

				const url = window.URL.createObjectURL(blob);
				const a = document.createElement("a");
				a.href = url;
				a.download = nomeArquivo || "download.xlsx";
				document.body.appendChild(a);
				a.click();
				a.remove();
				window.URL.revokeObjectURL(url);
			} catch (erro) {
				alert("Erro ao gerar o arquivo. Tente novamente.");
				console.error(erro);
			} finally {
				esconderLoading();
			}
		});
	});

	function extrairNomeArquivo(disposition) {
		if (!disposition) return null;
		const match = disposition.match(/filename="?([^"]+)"?/);
		return match ? match[1] : null;
	}

	// Forms normais (que fazem redirect de verdade) continuam como antes
	document.querySelectorAll("form:not(.form-download):not(.form-async)").forEach(function (form) {
		form.addEventListener("submit", mostrarLoading);
	});

	document.querySelectorAll("a").forEach(function (link) {
		link.addEventListener("click", function (e) {
			const href = link.getAttribute("href");
			if (href && !href.startsWith("#") && link.target !== "_blank" && !e.ctrlKey && !e.metaKey) {
				mostrarLoading();
			}
		});
	});
	
	// Flashs
	setTimeout(() => {
		document.querySelectorAll('.flash').forEach(el => {
			el.style.opacity = '0';
			setTimeout(() => el.remove(), 500);
		});
	}, 3000);

	// ---------- Menu hambúrguer (mobile) ----------
	const btnHamburguer = document.getElementById("btnHamburguer");
	const navbarEl = document.querySelector(".navbar");

	if (btnHamburguer && navbarEl) {
		btnHamburguer.addEventListener("click", function (e) {
			e.stopPropagation();
			const aberto = navbarEl.classList.toggle("menu-aberto");
			btnHamburguer.setAttribute("aria-expanded", String(aberto));
			if (!aberto) fecharTodas(null); // fecha dropdowns abertos junto
		});
	}

	// fecha o menu mobile ao clicar fora (reaproveita o listener de clique fora que já existe)
	document.addEventListener("click", function () {
		if (navbarEl) {
			navbarEl.classList.remove("menu-aberto");
			if (btnHamburguer) btnHamburguer.setAttribute("aria-expanded", "false");
		}
	});

	// fecha o menu mobile com ESC também
	document.addEventListener("keydown", function (e) {
		if (e.key === "Escape" && navbarEl) {
			navbarEl.classList.remove("menu-aberto");
			if (btnHamburguer) btnHamburguer.setAttribute("aria-expanded", "false");
		}
	});

	// impede que clique DENTRO do menu aberto feche ele (só fecha clicando fora)
	document.querySelectorAll(".nav-center, .nav-right").forEach(function (el) {
		el.addEventListener("click", function (e) {
			e.stopPropagation();
		});
	});

});

window.addEventListener("pageshow", function (event) {
	const overlay = document.getElementById("loading-overlay");
	if (overlay) {
		overlay.classList.remove("active");
	}
});