const form = document.getElementById('consulta-form');
const feedback = document.getElementById('feedback');
const resultado = document.getElementById('resultado');

function setFeedback(message, type = 'ok') {
  feedback.textContent = message;
  feedback.className = `feedback ${type}`;
  feedback.classList.remove('hidden');
}

function hideFeedback() {
  feedback.className = 'feedback hidden';
  feedback.textContent = '';
}

function field(label, value) {
  return `<div class="field"><span>${label}</span><strong>${value || '—'}</strong></div>`;
}

function render(data) {
  const product = data.product || {};
  const warningHtml = data.alerts_warning
    ? `<div class="feedback warning">${data.alerts_warning}<br/><a href="${data.alerts_manual_url}" target="_blank" rel="noopener noreferrer">Consultar alertas manualmente no portal oficial</a></div>`
    : '';

  const alertsHtml = data.alerts && data.alerts.length
    ? data.alerts.map(a => `
      <article class="alert-item">
        <h4>${a.title || 'Alerta sem título'}</h4>
        <div class="meta">${a.date || 'Data não informada'}${a.number ? ` • Alerta ${a.number}` : ''}</div>
        <p>${a.summary || ''}</p>
        <a href="${a.link}" target="_blank" rel="noopener noreferrer">Abrir fonte oficial</a>
      </article>
    `).join('')
    : '<p>Nenhum alerta de tecnovigilância encontrado para este registro.</p>';

  resultado.innerHTML = `
    <div class="box">
      <h2>Dados do equipamento</h2>
      <div class="grid">
        ${field('Registro ANVISA', product.registro_anvisa || data.registro_anvisa)}
        ${field('Nome do produto', product.nome_produto)}
        ${field('Marca', product.marca)}
        ${field('Modelo', product.modelo)}
        ${field('Fabricante', product.fabricante)}
        ${field('Detentor do registro', product.detentor_registro)}
        ${field('País de fabricação', product.pais_fabricacao)}
        ${field('Situação', product.situacao)}
        ${field('Processo', product.processo)}
        ${field('Classificação de risco', product.classificacao_risco)}
      </div>
    </div>
    <div class="box">
      <h2>Alertas de tecnovigilância (${data.alerts_count || 0})</h2>
      ${warningHtml}
      ${alertsHtml}
    </div>
  `;
  resultado.classList.remove('hidden');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  hideFeedback();
  resultado.classList.add('hidden');
  const registro = document.getElementById('registro').value.replace(/\D/g, '');

  if (registro.length !== 11) {
    setFeedback('O registro ANVISA deve conter exatamente 11 dígitos.', 'error');
    return;
  }

  setFeedback('Consultando fontes da Anvisa...', 'ok');

  try {
    const response = await fetch(`/api/consultar?registro=${encodeURIComponent(registro)}`);
    const data = await response.json();

    if (!response.ok && data.error) {
      setFeedback(data.error, 'error');
      return;
    }

    if (!data.found) {
      setFeedback(data.message || 'Registro não encontrado.', 'error');
      return;
    }

    setFeedback(data.message || 'Consulta realizada com sucesso.', 'ok');
    render(data);
  } catch (err) {
    setFeedback('Falha ao consultar o sistema. Tente novamente.', 'error');
  }
});
