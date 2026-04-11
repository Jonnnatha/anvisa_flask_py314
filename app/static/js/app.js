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

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function field(label, value) {
  if (value === undefined || value === null || String(value).trim() === '') {
    return '';
  }
  return `<div class="field"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function alertField(label, value) {
  if (!value || String(value).trim() === '') return '';
  return `<p><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</p>`;
}

function render(data) {
  const product = data.product || {};
  const company = product.empresa || {};
  const alerts = Array.isArray(data.alerts) ? data.alerts : [];
  const materials = Array.isArray(data.materials_or_signals) ? data.materials_or_signals : [];

  const productFields = [
    field('Número do registro', product.numeroRegistro || data.registro_anvisa),
    field('Nome do produto', product.nomeProduto),
    field('Número do processo', product.numeroProcesso),
    field('Situação do registro/notificação', product.situacaoNotificacaoRegistro),
    field('Nome técnico', product.nomeTecnico),
    field('Marca', product.marca),
    field('Modelo', product.modelo),
    field('Fabricante', product.fabricante),
    field('Empresa (razão social)', company.razaoSocial),
    field('Empresa (CNPJ)', company.cnpj)
  ].filter(Boolean).join('');

  const alertsHtml = alerts.length
    ? alerts.map(item => `
      <article class="alert-item alert-item-partial">
        <h4>Alerta ${escapeHtml(item.numero_alerta || '')}</h4>
        <div class="meta">${escapeHtml(item.data || '')} · <a href="${escapeHtml(item.url || '#')}" target="_blank" rel="noopener noreferrer">Abrir alerta</a></div>
        ${alertField('Resumo', item.resumo)}
        ${alertField('Identificação do produto ou caso', item.identificacao_produto_ou_caso)}
        ${alertField('Problema', item.problema)}
        ${alertField('Ação', item.acao)}
        ${alertField('Recomendações', item.recomendacoes)}
        ${alertField('Empresa', item.empresa)}
        ${alertField('Nome comercial', item.nome_comercial)}
        ${alertField('Nome técnico', item.nome_tecnico)}
        ${alertField('Registro ANVISA', item.numero_registro_anvisa)}
        ${alertField('Tipo de produto', item.tipo_produto)}
        ${alertField('Classe de risco', item.classe_risco)}
        ${alertField('Modelo afetado', item.modelo_afetado)}
        ${alertField('Números de série afetados', item.numeros_serie_afetados)}
      </article>
    `).join('')
    : '<p>Nenhum alerta associado ao registro foi encontrado na base local indexada.</p>';

  const materialsHtml = materials.length
    ? materials.map(item => `
      <article class="alert-item alert-item-partial">
        <h4>${escapeHtml(item.titulo)}</h4>
        <div class="meta">Fonte: ${escapeHtml(item.fonte)} · Tipo: ${escapeHtml(item.tipo)} · Confiança: ${escapeHtml(item.nivel_confianca)}</div>
        ${item.resumo ? `<p>${escapeHtml(item.resumo)}</p>` : ''}
        <a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer">Abrir material</a>
      </article>
    `).join('')
    : '<p>Nenhuma evidência pública forte foi encontrada para materiais técnicos deste produto.</p>';

  resultado.innerHTML = `
    <div class="box">
      <h2>Dados do produto</h2>
      <p class="meta">Origem: ${escapeHtml(data.origens?.produto || 'API oficial ANVISA')}</p>
      <div class="grid">${productFields || '<p>Sem campos confiáveis para exibir.</p>'}</div>
    </div>

    <div class="box">
      <h2>Alertas (${alerts.length})</h2>
      <p class="meta">Origem: ${escapeHtml(data.origens?.alertas || '')}.</p>
      ${data.alerts_warning ? `<div class="feedback warning">${escapeHtml(data.alerts_warning)}</div>` : ''}
      ${alertsHtml}
    </div>

    <div class="box">
      <h2>Materiais / sinais públicos úteis (${materials.length})</h2>
      <p class="meta">Origem: ${escapeHtml(data.origens?.materiais || '')}.</p>
      ${data.materials_warning ? `<div class="feedback warning">${escapeHtml(data.materials_warning)}</div>` : ''}
      ${materialsHtml}
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

  setFeedback('Consultando API oficial, base local de alertas e materiais públicos...', 'ok');

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
