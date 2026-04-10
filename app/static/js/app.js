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

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function render(data) {
  const product = data.product || {};
  const company = product.empresa || {};
  const alerts = Array.isArray(data.alerts) ? data.alerts : [];
  const signals = Array.isArray(data.complaints_or_signals) ? data.complaints_or_signals : [];

  const alertsHtml = alerts.length
    ? alerts.map(item => `
      <article class="alert-item alert-item-partial">
        <h4>Alerta ${escapeHtml(item.numero_alerta)}</h4>
        <div class="meta">Origem: ${escapeHtml(item.origem_da_descoberta || 'fonte externa')} · Confiança: ${escapeHtml(item.nivel_confianca || 'não informada')}</div>
        <a href="${escapeHtml(item.link_pesquisa_manual)}" target="_blank" rel="noopener noreferrer">Pesquisar manualmente no portal ANVISA</a>
      </article>
    `).join('')
    : '<p>Nenhum alerta foi encontrado na fonte externa de apoio.</p>';

  const signalsHtml = signals.length
    ? signals.map(item => `
      <article class="alert-item alert-item-partial">
        <h4>${escapeHtml(item.titulo)}</h4>
        <div class="meta">Fonte: ${escapeHtml(item.fonte)} · Tipo: ${escapeHtml(item.tipo)} · Confiança: ${escapeHtml(item.nivel_confianca)}</div>
        ${item.resumo ? `<p>${escapeHtml(item.resumo)}</p>` : ''}
        <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer">Abrir referência</a>
      </article>
    `).join('')
    : '<p>Nenhuma reclamação pública relevante foi encontrada.</p>';

  resultado.innerHTML = `
    <div class="box">
      <h2>Dados do produto</h2>
      <p class="meta">Origem: ${escapeHtml(data.origens?.produto || 'API oficial ANVISA')}</p>
      <div class="grid">
        ${field('Número do registro', product.numeroRegistro || data.registro_anvisa)}
        ${field('Nome do produto', product.nomeProduto)}
        ${field('Número do processo', product.numeroProcesso)}
        ${field('Situação do registro/notificação', product.situacaoNotificacaoRegistro)}
        ${field('Nome técnico', product.nomeTecnico)}
        ${field('Empresa (razão social)', company.razaoSocial)}
        ${field('Empresa (CNPJ)', company.cnpj)}
      </div>
    </div>

    <div class="box">
      <h2>Alertas (${alerts.length})</h2>
      <p class="meta">Origem: ${escapeHtml(data.origens?.alertas || '')}. Fonte externa de apoio (não oficial ANVISA).</p>
      ${data.alerts_warning ? `<div class="feedback warning">${escapeHtml(data.alerts_warning)}</div>` : ''}
      ${alertsHtml}
    </div>

    <div class="box">
      <h2>Reclamações / sinais públicos relacionados (${signals.length})</h2>
      <p class="meta">Origem: ${escapeHtml(data.origens?.sinais_publicos || '')}.</p>
      ${data.signals_warning ? `<div class="feedback warning">${escapeHtml(data.signals_warning)}</div>` : ''}
      ${signalsHtml}
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

  setFeedback('Consultando fontes configuradas...', 'ok');

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
