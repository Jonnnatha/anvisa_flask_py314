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

function renderStatusBadge(status) {
  if (!status) return '';
  const labelByStatus = {
    alerts_found: 'Alertas localizados',
    no_alerts_found: 'Sem alertas encontrados',
    blocked_source: 'Fonte bloqueada',
    partial_result: 'Resultado parcial',
    manual_validation_required: 'Validação manual necessária',
  };
  const label = labelByStatus[status] || status;
  return `<p class="meta">Status da busca de alertas: <strong>${escapeHtml(label)}</strong></p>`;
}

function render(data) {
  const product = data.product || {};
  const status = data.alerts_status;

  const warningHtml = data.alerts_warning
    ? `<div class="feedback warning">${escapeHtml(data.alerts_warning)}</div>`
    : '';

  const sourceHtml = Array.isArray(data.alerts_sources) && data.alerts_sources.length
    ? `<details class="alerts-sources"><summary>Fontes consultadas</summary><ul>${data.alerts_sources.map(s => {
      const statusLabel = s.status || 'desconhecido';
      const detail = s.details ? ` — ${escapeHtml(s.details)}` : '';
      return `<li><strong>${escapeHtml(s.name || 'fonte')}</strong> (${escapeHtml(statusLabel)}) · <a href="${escapeHtml(s.url || '#')}" target="_blank" rel="noopener noreferrer">abrir fonte</a>${detail}</li>`;
    }).join('')}</ul></details>`
    : '';

  const referenceLinksHtml = Array.isArray(data.alerts_reference_links) && data.alerts_reference_links.length
    ? `<div class="manual-links"><p>Referências oficiais para consulta manual:</p><ul>${data.alerts_reference_links.map(item => `
        <li><a href="${escapeHtml(item.link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title || item.link)}</a></li>
      `).join('')}</ul></div>`
    : '';

  const manualLinks = data.alerts_manual_links || {};
  const manualLinksHtml = (manualLinks.principal || manualLinks.listagem || manualLinks.tecnovigilancia)
    ? `<div class="manual-links"><p>Consulta manual recomendada:</p><ul>
        ${manualLinks.principal ? `<li><a href="${escapeHtml(manualLinks.principal)}" target="_blank" rel="noopener noreferrer">Portal de alertas (legado)</a></li>` : ''}
        ${manualLinks.listagem ? `<li><a href="${escapeHtml(manualLinks.listagem)}" target="_blank" rel="noopener noreferrer">Listagem de alertas (portal legado)</a></li>` : ''}
        ${manualLinks.tecnovigilancia ? `<li><a href="${escapeHtml(manualLinks.tecnovigilancia)}" target="_blank" rel="noopener noreferrer">Página oficial de Tecnovigilância (gov.br)</a></li>` : ''}
      </ul></div>`
    : '';


  const alertsResult = data.alerts_result || {};
  const alertsResultHtml = alertsResult && (alertsResult.source || alertsResult.confidence || Array.isArray(alertsResult.alert_ids))
    ? `<p class="meta">Camada: <strong>${escapeHtml(alertsResult.source || 'n/d')}</strong> · Confiança: <strong>${escapeHtml(alertsResult.confidence || 'n/d')}</strong>${Array.isArray(alertsResult.alert_ids) && alertsResult.alert_ids.length ? ` · IDs: ${escapeHtml(alertsResult.alert_ids.join(', '))}` : ''}</p>`
    : '';

  let alertsHtml = '';
  if (data.alerts && data.alerts.length) {
    alertsHtml = data.alerts.map(a => `
      <article class="alert-item">
        <h4>${escapeHtml(a.title || 'Alerta sem título')}</h4>
        <div class="meta">${escapeHtml(a.date || 'Data não informada')}${a.id ? ` • Alerta ${escapeHtml(a.id)}` : ''}</div>
        <p>${escapeHtml(a.summary || '')}</p>
        <a href="${escapeHtml(a.link)}" target="_blank" rel="noopener noreferrer">Abrir fonte oficial</a>
      </article>
    `).join('');
  } else if (status === 'no_alerts_found') {
    alertsHtml = '<p>Nenhum alerta de tecnovigilância encontrado para os termos consultados.</p>';
  } else {
    alertsHtml = '<p>A consulta automática de alertas não foi conclusiva. Use os links oficiais abaixo para validação manual.</p>';
  }

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
      ${renderStatusBadge(status)}
      ${warningHtml}
      ${alertsResultHtml}
      ${alertsHtml}
      ${sourceHtml}
      ${manualLinksHtml}
      ${referenceLinksHtml}
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
